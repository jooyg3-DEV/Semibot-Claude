import os
import re
import time
import threading
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from utils import match_title, is_china
import config

# ==========================================
# ⚙️ [설정]
# ==========================================
SHEET_URL = os.environ.get("SHEET_URL", "여기에_구글_스프레드시트_URL을_붙여넣으세요")
MAX_WORKERS = 4  # 병렬로 처리할 회사 수

TARGET_COMPANIES = [
    "삼성전자", "SK하이닉스", "ASML", "Applied Materials",
    "KLA", "Lam Research", "Tokyo Electron", "Micron",
    "Intel", "TSMC", "NVIDIA", "AMD"
]

# 회사 우선순위 — config.py의 priority 그룹(1순위/2순위)을 사용
COMPANY_RANK = {c["name"]: c["priority"] for c in config.COMPANIES}

# 포털별 검색어 — config.py에서 관리
COMPANY_SEARCH_KR = {c["name"]: c["search_kr"] for c in config.COMPANIES}
COMPANY_SEARCH_EN = {c["name"]: c["search_en"] for c in config.COMPANIES}

# 공식 홈페이지 검색 쿼리 — config.py에서 관리
# 학력(석사/박사/신입/Master/PhD/Entry Level) + 직무 키워드 조합으로 3개씩 순회
KOREAN_COMPANIES = config.KOREAN_COMPANY_NAMES
SEARCH_QUERIES_KR = config.SEARCH_QUERIES_KR
SEARCH_QUERIES_EN = config.SEARCH_QUERIES_EN

LINKEDIN_COOKIE = os.environ.get("LINKEDIN_COOKIE", "")  # li_at 쿠키값

OFFICIAL_URLS = {
    "삼성전자":          ["https://www.samsungcareers.com/hr/"],
    "SK하이닉스":        ["https://recruit.skhynix.com/"],           # SK그룹 통합 포털(skcareers.com) 아닌 전용 사이트
    "ASML":              ["https://asmlkorea.careerlink.kr/jobs",
                          "https://www.asml.com/en/careers/find-your-job"],
    "Applied Materials": ["https://appliedkorea.applyin.co.kr/jobs/",
                          "https://jobs.appliedmaterials.com/"],
    "Lam Research":      ["https://lamresearch-recruit.com/jobs",
                          "https://careers.lamresearch.com/careers"],  # 글로벌 채용 사이트 추가
    "KLA":               ["https://kla.wd1.myworkdayjobs.com/Search"],
    "Micron":            ["https://careers.micron.com/careers"],       # 루트 → 직무 목록 페이지로
    "TSMC":              ["https://www.tsmc.com/english/careers/"],    # 구버전 static 페이지 → 현행 페이지로
    "Intel":             ["https://intel.wd1.myworkdayjobs.com/External"],
    "NVIDIA":            ["https://nvidia.eightfold.ai/careers"],
    "AMD":               ["https://careers.amd.com/careers-home/jobs"],
    "Tokyo Electron":    ["https://tel.recruiter.co.kr/career/career"],  # OFFICIAL_URLS 누락 추가
}

def make_driver():
    """각 스레드마다 독립적인 드라이버 생성 (이미지 차단으로 속도 향상)"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    })
    driver.set_page_load_timeout(15)
    return driver


def connect_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    sheet = gspread.authorize(creds).open_by_url(SHEET_URL).worksheet("채용공고")
    try:
        existing_links = set(sheet.col_values(14))  # N열(14)이 링크
    except Exception:
        existing_links = set()
    return sheet, existing_links


def is_target_company(actual, target):
    return target.lower().replace(" ", "") in actual.lower().replace(" ", "")


def create_job_row(source, company, title, link):
    today = datetime.today().strftime('%Y-%m-%d')
    rank = COMPANY_RANK.get(company, 99)
    # A:검색일, B:순위, C:출처, D:마감일, E:상시, F:회사, G:공고명
    # H:지원자격, I:채용직무, J:근무지, K:채용형태, L:직무설명, M:박사우대, N:링크
    return [today, rank, source, today, "상시", company, title,
            "AI 대기", "AI 대기", "AI 대기", "AI 대기", "AI 대기", "AI 대기", link]


def try_keyword_search(driver, keyword):
    """페이지 내 검색창을 찾아 키워드 입력 후 결과 대기. 성공 여부 반환."""
    selectors = [
        'input[type="search"]',
        'input[placeholder*="Search" i]',
        'input[placeholder*="Job" i]',
        'input[placeholder*="검색" i]',
        'input[placeholder*="직무" i]',
        'input[placeholder*="keyword" i]',
        'input[name*="search" i]',
        'input[id*="search" i]',
        'input[class*="search" i]',
    ]
    for sel in selectors:
        try:
            box = driver.find_element(By.CSS_SELECTOR, sel)
            if not box.is_displayed():
                continue
            box.clear()
            box.send_keys(keyword)
            box.send_keys(Keys.RETURN)
            time.sleep(2)
            return True
        except Exception:
            continue
    return False


def load_page(driver, url):
    try:
        driver.get(url)
        time.sleep(1.5)  # 기존 2초 → 1.5초
        return True
    except Exception:
        return False


def _match_company(displayed_text, company_name):
    """영문명 + 한국어 검색명 둘 다로 회사 매칭."""
    kr_name = COMPANY_SEARCH_KR.get(company_name, company_name)
    en_name = COMPANY_SEARCH_EN.get(company_name, company_name)
    return (is_target_company(displayed_text, company_name) or
            is_target_company(displayed_text, kr_name) or
            is_target_company(displayed_text, en_name))


def scrape_portal_info(company_name, driver, local_links):
    job_list = []
    kr_query = COMPANY_SEARCH_KR.get(company_name, company_name)  # 한국 포털용
    en_query = COMPANY_SEARCH_EN.get(company_name, company_name)  # 글로벌 포털용

    # 사람인 (한국어 검색)
    saramin_count = 0
    if load_page(driver, f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={kr_query}+석박사"):
        try:
            for job in driver.find_elements(By.CSS_SELECTOR, '.item_recruit')[:5]:
                link = job.find_element(By.CSS_SELECTOR, '.job_tit a').get_attribute('href')
                if link in local_links:
                    continue
                if _match_company(job.find_element(By.CSS_SELECTOR, '.corp_name').text, company_name):
                    title = job.find_element(By.CSS_SELECTOR, '.job_tit a').text.strip()
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("사람인", company_name, title, link))
                    local_links.add(link)
                    saramin_count += 1
        except Exception:
            pass
    print(f"      [사람인] {company_name}: {saramin_count}개")

    # 잡코리아 (한국어 검색)
    jobkorea_count = 0
    if load_page(driver, f"https://www.jobkorea.co.kr/Search/?stext={kr_query}+석박사"):
        try:
            for job in driver.find_elements(By.CSS_SELECTOR, '.list-default .post')[:5]:
                title_elem = job.find_element(By.CSS_SELECTOR, '.title')
                link = title_elem.get_attribute('href')
                if link in local_links:
                    continue
                if _match_company(job.find_element(By.CSS_SELECTOR, '.name').text, company_name):
                    title = title_elem.text.strip()
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("잡코리아", company_name, title, link))
                    local_links.add(link)
                    jobkorea_count += 1
        except Exception:
            pass
    print(f"      [잡코리아] {company_name}: {jobkorea_count}개")

    # LinkedIn (쿠키 인증)
    linkedin_count = 0
    if not LINKEDIN_COOKIE:
        print(f"      [LinkedIn] LINKEDIN_COOKIE 미설정 - 건너뜀")
    else:
        li_kw = urllib.parse.quote(f"{en_query} process engineer semiconductor")
        li_url = f"https://www.linkedin.com/jobs/search/?keywords={li_kw}&sortBy=DD"
        try:
            driver.get("https://www.linkedin.com")
            driver.add_cookie({"name": "li_at", "value": LINKEDIN_COOKIE, "domain": ".linkedin.com"})
            driver.get(li_url)
            time.sleep(2)
            cur = driver.current_url
            if "login" in cur or "authwall" in cur or "signup" in cur:
                print(f"      [LinkedIn] {company_name}: 쿠키 만료 - 건너뜀")
            else:
                for job in driver.find_elements(By.CSS_SELECTOR, '.base-card, .job-search-card')[:10]:
                    try:
                        link_elem = job.find_element(By.CSS_SELECTOR, 'a[href*="linkedin.com/jobs"]')
                        link = link_elem.get_attribute('href').split('?')[0]
                        if link in local_links:
                            continue
                        title = job.find_element(By.CSS_SELECTOR, '.base-search-card__title, .job-search-card__title').text.strip()
                        company_elem = job.find_element(By.CSS_SELECTOR, '.base-search-card__subtitle, .job-search-card__company-name')
                        if not _match_company(company_elem.text, company_name):
                            continue
                        try:
                            location = job.find_element(By.CSS_SELECTOR, '.job-search-card__location').text
                        except Exception:
                            location = ''
                        if match_title(title) is None or is_china(title + ' ' + location):
                            continue
                        job_list.append(create_job_row("LinkedIn", company_name, title, link))
                        local_links.add(link)
                        linkedin_count += 1
                    except Exception:
                        continue
        except Exception as e:
            print(f"      [LinkedIn] {company_name}: 오류 - {e}")
    print(f"      [LinkedIn] {company_name}: {linkedin_count}개")

    # 잡다 (한국어 검색)
    jobda_count = 0
    if load_page(driver, f"https://www.jobda.im/position?keyword={kr_query}"):
        try:
            time.sleep(1)
            for item in driver.find_elements(By.CSS_SELECTOR, 'li')[:10]:
                try:
                    a = item.find_element(By.CSS_SELECTOR, 'a')
                    link = a.get_attribute('href') or ''
                    if not link.startswith('http'):
                        link = 'https://www.jobda.im' + link
                    title = ''
                    for sel in ['.position-name', '.title', 'h3', 'h4', 'strong']:
                        try:
                            title = item.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if title:
                                break
                        except Exception:
                            continue
                    if not title or len(title) < 3 or link in local_links:
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    if _match_company(item.text, company_name):
                        job_list.append(create_job_row("잡다", company_name, title, link))
                        local_links.add(link)
                        jobda_count += 1
                except Exception:
                    continue
        except Exception:
            pass
    print(f"      [잡다] {company_name}: {jobda_count}개")

    # Indeed (영문 검색, 해외 직무)
    indeed_count = 0
    indeed_q = urllib.parse.quote(f"{en_query} process engineer semiconductor phd")
    if load_page(driver, f"https://www.indeed.com/jobs?q={indeed_q}&sort=date"):
        try:
            time.sleep(2)
            for job in driver.find_elements(By.CSS_SELECTOR, '.job_seen_beacon')[:5]:
                try:
                    title_elem = job.find_element(By.CSS_SELECTOR, '[data-testid="jobTitle"] a, h2.jobTitle a')
                    link = title_elem.get_attribute('href') or ''
                    if not link.startswith('http'):
                        link = 'https://www.indeed.com' + link
                    title = title_elem.text.strip()
                    company_elem = job.find_element(By.CSS_SELECTOR, '[data-testid="company-name"], .companyName')
                    if link in local_links or not title or len(title) < 5:
                        continue
                    if not _match_company(company_elem.text, company_name):
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("Indeed", company_name, title, link))
                    local_links.add(link)
                    indeed_count += 1
                except Exception:
                    continue
        except Exception:
            pass
    print(f"      [Indeed] {company_name}: {indeed_count}개")

    return job_list


# Google 검색에서 이미 수집 중인 사이트는 중복 제외
_SKIP_DOMAINS = [
    'saramin.co.kr', 'jobkorea.co.kr', 'jobda.im',
    'indeed.com', 'linkedin.com', 'google.com',
    'googleapis.com', 'gstatic.com',
]


def _is_skip_domain(url):
    return any(d in url for d in _SKIP_DOMAINS)


def scrape_google_jobs(company_name, driver, local_links):
    """Google 검색으로 공채/구직 사이트 외 캐싱된 공고 수집."""
    job_list = []
    en_query = COMPANY_SEARCH_EN.get(company_name, company_name)

    queries = [
        f'"{en_query}" process engineer semiconductor jobs',
        f'"{en_query}" engineer phd semiconductor "apply"',
    ]

    for q in queries:
        gq = urllib.parse.quote(q)
        if not load_page(driver, f"https://www.google.com/search?q={gq}&num=10"):
            continue
        time.sleep(1.5)
        try:
            for result in driver.find_elements(By.CSS_SELECTOR, 'div.g'):
                try:
                    a = result.find_element(By.CSS_SELECTOR, 'a')
                    link = a.get_attribute('href') or ''
                    if not link.startswith('http') or _is_skip_domain(link):
                        continue
                    link = link.split('?')[0]
                    if link in local_links:
                        continue
                    title = result.find_element(By.CSS_SELECTOR, 'h3').text.strip()
                    if not title or len(title) < 5:
                        continue
                    if match_title(title) is None or is_china(title + ' ' + link):
                        continue
                    job_list.append(create_job_row("Google", company_name, title, link))
                    local_links.add(link)
                except Exception:
                    continue
        except Exception:
            continue

    print(f"      [Google] {company_name}: {len(job_list)}개")
    return job_list


def _collect_links_from_page(driver, company_name, local_links, job_list):
    """현재 드라이버 페이지에서 공고 링크를 모두 추출해 job_list에 추가."""
    valid_url_kw = ['/job', '/req', 'jobid=', '/career', '/position', 'detail', 'posting', 'recruit']
    for elem in driver.find_elements(By.TAG_NAME, 'a'):
        try:
            link = elem.get_attribute('href')
            title = elem.text.strip()
            if not link or len(title) < 5 or link in local_links:
                continue
            if any(kw in link.lower() for kw in valid_url_kw):
                if match_title(title) is None or is_china(title + ' ' + link):
                    continue
                job_list.append(create_job_row("공식 홈페이지", company_name, title, link))
                local_links.add(link)
        except Exception:
            continue


def _scroll_to_load(driver):
    """SPA/lazy-load 페이지에서 스크롤로 콘텐츠 렌더링 트리거."""
    try:
        for _ in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.8)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)
    except Exception:
        pass


def scrape_official_pages(company_name, driver, local_links):
    job_list = []
    urls = OFFICIAL_URLS.get(company_name, [])
    queries = SEARCH_QUERIES_KR if company_name in KOREAN_COMPANIES else SEARCH_QUERIES_EN

    for url in urls:
        if not load_page(driver, url):
            continue
        time.sleep(3)  # SPA 초기 렌더링 대기 (1.5 → 3초)
        _scroll_to_load(driver)  # lazy load 트리거

        # 검색창 유무 확인 (첫 번째 쿼리로 테스트)
        first_query = queries[0]
        searched = try_keyword_search(driver, first_query)

        if searched:
            print(f"      [검색] {company_name}: '{first_query}' 검색 성공")
            _scroll_to_load(driver)
            _collect_links_from_page(driver, company_name, local_links, job_list)

            # 나머지 쿼리도 순차 검색 (검색창이 있을 때만)
            for query in queries[1:]:
                if load_page(driver, url) and try_keyword_search(driver, query):
                    print(f"      [검색] {company_name}: '{query}' 검색")
                    _scroll_to_load(driver)
                    _collect_links_from_page(driver, company_name, local_links, job_list)
        else:
            # 검색창 없음 → 페이지 전체 링크에서 수집 (fallback)
            _collect_links_from_page(driver, company_name, local_links, job_list)

    return job_list


def scrape_company(company, existing_links_snapshot):
    """단일 회사의 모든 소스를 독립 드라이버로 수집 (스레드 안전)"""
    driver = make_driver()
    local_links = set(existing_links_snapshot)  # 스냅샷 복사본 사용
    job_list = []
    try:
        print(f"  ▶ [{company}] 수집 시작...")
        job_list.extend(scrape_portal_info(company, driver, local_links))
        job_list.extend(scrape_official_pages(company, driver, local_links))
        job_list.extend(scrape_google_jobs(company, driver, local_links))
        print(f"  ✓ [{company}] {len(job_list)}개 발견")
    except Exception as e:
        print(f"  ✗ [{company}] 오류: {e}")
    finally:
        driver.quit()
    return job_list


def sort_sheet(sheet):
    """날짜 → 순위 → 출처 순으로 시트 정렬"""
    all_rows = sheet.get_all_values()
    if len(all_rows) <= 1:
        return
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if not date_pattern.match(str(all_rows[0][0])):
        header = all_rows[0]
        data = all_rows[1:]
    else:
        header = None
        data = all_rows

    def sort_key(row):
        date = row[0] if len(row) > 0 else ''
        rank = int(row[1]) if len(row) > 1 and str(row[1]).isdigit() else 999
        source = row[2] if len(row) > 2 else ''
        return (date, rank, source)

    data.sort(key=sort_key)
    result = ([header] if header else []) + data
    sheet.clear()
    sheet.update(result, 'A1')
    print(f"  ✓ 시트 정렬 완료 ({len(data)}개 행)")


if __name__ == "__main__":
    print("📊 [수집봇] 구글 시트 연결 중...")
    sheet, existing_links = connect_google_sheet()
    existing_links_snapshot = frozenset(existing_links)  # 불변 스냅샷 (스레드 공유)

    print(f"\n🤖 [수집봇] {MAX_WORKERS}개 병렬 스레드로 탐색 시작 (총 {len(TARGET_COMPANIES)}개 회사)...")
    all_results = []  # (link, row) 쌍
    dedup_lock = threading.Lock()
    seen_links = set(existing_links)
    company_status = {}  # 기업별 수집 결과 추적

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scrape_company, company, existing_links_snapshot): company
            for company in TARGET_COMPANIES
        }
        for future in as_completed(futures):
            company = futures[future]
            try:
                jobs = future.result()
                new_count = 0
                with dedup_lock:
                    for job in jobs:
                        link = job[13]  # N열 링크
                        if link not in seen_links:
                            seen_links.add(link)
                            all_results.append(job)
                            new_count += 1
                company_status[company] = {"found": new_count, "error": None}
            except Exception as e:
                company_status[company] = {"found": 0, "error": str(e)}

    if all_results:
        print(f"\n📝 새로운 공고 {len(all_results)}개를 시트에 일괄 등록합니다.")
        # append_rows()로 한 번에 쓰기 (기존 N회 × sleep(1) 제거)
        sheet.append_rows(all_results, value_input_option='USER_ENTERED')
        print("\n🔃 시트 정렬 중...")
        sort_sheet(sheet)
    else:
        print("\n✨ 새로 올라온 공고가 없습니다.")

    print("\n📋 [수집봇] 기업별 수집 결과:")
    checked = 0
    for company in TARGET_COMPANIES:
        status = company_status.get(company)
        if status is None:
            print(f"  ⚠️  {company}: 미실행")
        elif status["error"]:
            print(f"  ✗ {company}: 오류 - {status['error']}")
        else:
            print(f"  ✓ {company}: 신규 {status['found']}개")
            checked += 1
    print(f"\n  → 전체 {len(TARGET_COMPANIES)}개 중 {checked}개 정상 완료")
    print("\n🛑 [수집봇] 안전하게 종료되었습니다.")
