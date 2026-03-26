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
SHEET_URL        = config.SHEET_URL
LINKEDIN_COOKIE  = os.environ.get("LINKEDIN_COOKIE", "")
MAX_WORKERS      = 4  # 병렬로 처리할 회사 수

TARGET_COMPANIES = [
    "삼성전자", "SK하이닉스", "ASML", "Applied Materials",
    "KLA", "Lam Research", "Tokyo Electron", "Micron",
    "Intel", "TSMC", "NVIDIA", "AMD"
]

# 회사 우선순위 — config.py의 priority 그룹(1순위/2순위)을 사용
COMPANY_RANK = {c["name"]: c["priority"] for c in config.COMPANIES}

# 공식 홈페이지 검색 쿼리 — config.py에서 관리
# 학력(석사/박사/신입/Master/PhD/Entry Level) + 직무 키워드 조합으로 3개씩 순회
KOREAN_COMPANIES = config.KOREAN_COMPANY_NAMES
SEARCH_QUERIES_KR = config.SEARCH_QUERIES_KR
SEARCH_QUERIES_EN = config.SEARCH_QUERIES_EN

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
    driver = webdriver.Chrome(options=options)
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


def _get_company_cfg(company_name):
    return next((c for c in config.COMPANIES if c["name"] == company_name), {})


def _set_linkedin_cookie(driver):
    """li_at 쿠키로 LinkedIn 로그인 상태 설정. 성공 여부 반환."""
    if not LINKEDIN_COOKIE:
        print("    [LinkedIn] LINKEDIN_COOKIE 미설정 → 건너뜀")
        return False
    try:
        driver.get("https://www.linkedin.com")
        time.sleep(1)
        driver.add_cookie({
            "name": "li_at",
            "value": LINKEDIN_COOKIE,
            "domain": ".linkedin.com",
            "path": "/",
            "secure": True,
        })
        return True
    except Exception as e:
        print(f"    [LinkedIn] 쿠키 설정 실패: {e}")
        return False


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


def scrape_portal_info(company_name, driver, local_links):
    job_list = []
    cfg        = _get_company_cfg(company_name)
    search_kr  = cfg.get("search_kr", company_name)
    search_en  = cfg.get("search_en", company_name)

    # ── 사람인 (한국어 검색어) ──────────────────────────────────
    saramin_q = urllib.parse.quote(f"{search_kr} 석박사")
    if load_page(driver, f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={saramin_q}"):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, '.item_recruit')
            print(f"    [사람인] {company_name}({search_kr}): 카드 {len(cards)}개")
            for job in cards[:10]:
                try:
                    link  = job.find_element(By.CSS_SELECTOR, '.job_tit a').get_attribute('href')
                    title = job.find_element(By.CSS_SELECTOR, '.job_tit a').text.strip()
                    corp  = job.find_element(By.CSS_SELECTOR, '.corp_name').text
                    if link in local_links or not is_target_company(corp, search_kr):
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("사람인", company_name, title, link))
                    local_links.add(link)
                except Exception:
                    continue
        except Exception as e:
            print(f"    [사람인] {company_name} 파싱 오류: {e}")

    # ── 잡코리아 (한국어 검색어) ───────────────────────────────
    jobkorea_q = urllib.parse.quote(f"{search_kr} 석박사")
    if load_page(driver, f"https://www.jobkorea.co.kr/Search/?stext={jobkorea_q}"):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, '.list-default .post')
            print(f"    [잡코리아] {company_name}({search_kr}): 카드 {len(cards)}개")
            for job in cards[:10]:
                try:
                    title_elem = job.find_element(By.CSS_SELECTOR, '.title')
                    link  = title_elem.get_attribute('href')
                    title = title_elem.text.strip()
                    corp  = job.find_element(By.CSS_SELECTOR, '.name').text
                    if link in local_links or not is_target_company(corp, search_kr):
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("잡코리아", company_name, title, link))
                    local_links.add(link)
                except Exception:
                    continue
        except Exception as e:
            print(f"    [잡코리아] {company_name} 파싱 오류: {e}")

    # ── LinkedIn (cookie 인증 + 영어 검색어) ───────────────────
    if _set_linkedin_cookie(driver):
        li_q = urllib.parse.quote(f'"{search_en}" semiconductor engineer OR scientist OR researcher')
        li_url = f"https://www.linkedin.com/jobs/search/?keywords={li_q}&sortBy=DD&f_TPR=r604800"
        if load_page(driver, li_url):
            time.sleep(3)
            # 로그인 상태 카드 셀렉터 (순서대로 시도)
            cards = []
            for sel in ['.job-card-container', '.jobs-search__results-list > li',
                        '.scaffold-layout__list-item']:
                cards = driver.find_elements(By.CSS_SELECTOR, sel)
                if cards:
                    break
            print(f"    [LinkedIn] {company_name}({search_en}): 카드 {len(cards)}개")
            for card in cards[:15]:
                try:
                    title = ""
                    for sel in ['.job-card-list__title--link',
                                 '.job-card-container__link span[aria-hidden="true"]',
                                 'h3 a', 'h3']:
                        try:
                            title = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if title:
                                break
                        except Exception:
                            pass
                    corp = ""
                    for sel in ['.job-card-container__primary-description',
                                 '.artdeco-entity-lockup__subtitle span', 'h4']:
                        try:
                            corp = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if corp:
                                break
                        except Exception:
                            pass
                    link = ""
                    for sel in ['a.job-card-container__link',
                                 'a.job-card-list__title--link', 'a']:
                        try:
                            link = card.find_element(By.CSS_SELECTOR, sel).get_attribute('href') or ''
                            if link:
                                break
                        except Exception:
                            pass
                    location = ""
                    for sel in ['.job-card-container__metadata-item',
                                 '.artdeco-entity-lockup__caption', 'li']:
                        try:
                            location = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if location:
                                break
                        except Exception:
                            pass
                    base_link = link.split('?')[0]
                    if not title or not link:
                        continue
                    if base_link in {e.split('?')[0] for e in local_links}:
                        continue
                    if corp and not is_target_company(corp, search_en):
                        continue
                    if match_title(title) is None or is_china(title + ' ' + location):
                        continue
                    job_list.append(create_job_row("LinkedIn", company_name, title, link))
                    local_links.add(link)
                except Exception:
                    continue

    # ── 잡다 (한국어 검색어) ───────────────────────────────────
    jobda_q = urllib.parse.quote(search_kr)
    if load_page(driver, f"https://www.jobda.im/position?keyword={jobda_q}"):
        try:
            time.sleep(2)
            cards = driver.find_elements(By.CSS_SELECTOR,
                        'li.position-item, li[class*="position"], li[class*="card"]')
            if not cards:
                cards = driver.find_elements(By.CSS_SELECTOR, 'li')
            print(f"    [잡다] {company_name}({search_kr}): 카드 {len(cards)}개")
            for item in cards[:15]:
                try:
                    a = item.find_element(By.CSS_SELECTOR, 'a')
                    link = a.get_attribute('href') or ''
                    if link and not link.startswith('http'):
                        link = 'https://www.jobda.im' + link
                    title = ''
                    for sel in ['.position-name', '.title', 'h3', 'h4', 'strong']:
                        try:
                            title = item.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if title:
                                break
                        except Exception:
                            pass
                    if not title or len(title) < 3 or link in local_links:
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    if is_target_company(item.text, search_kr) or is_target_company(item.text, search_en):
                        job_list.append(create_job_row("잡다", company_name, title, link))
                        local_links.add(link)
                except Exception:
                    continue
        except Exception as e:
            print(f"    [잡다] {company_name} 파싱 오류: {e}")

    # ── Indeed (영어 검색어, 해외 직무) ───────────────────────
    indeed_q = urllib.parse.quote(f'"{search_en}" semiconductor engineer OR scientist')
    if load_page(driver, f"https://www.indeed.com/jobs?q={indeed_q}&sort=date"):
        try:
            time.sleep(2)
            cards = driver.find_elements(By.CSS_SELECTOR, '.job_seen_beacon')
            print(f"    [Indeed] {company_name}({search_en}): 카드 {len(cards)}개")
            for job in cards[:10]:
                try:
                    title_elem = job.find_element(
                        By.CSS_SELECTOR, '[data-testid="jobTitle"] a, h2.jobTitle a')
                    link  = title_elem.get_attribute('href') or ''
                    if link and not link.startswith('http'):
                        link = 'https://www.indeed.com' + link
                    title = title_elem.text.strip()
                    corp  = job.find_element(
                        By.CSS_SELECTOR, '[data-testid="company-name"], .companyName').text
                    if link in local_links or not title or len(title) < 5:
                        continue
                    if not is_target_company(corp, search_en):
                        continue
                    if match_title(title) is None or is_china(title):
                        continue
                    job_list.append(create_job_row("Indeed", company_name, title, link))
                    local_links.add(link)
                except Exception:
                    continue
        except Exception as e:
            print(f"    [Indeed] {company_name} 파싱 오류: {e}")

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
    sheet.update(result, 'A1', value_input_option='USER_ENTERED')
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
