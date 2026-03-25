import os
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

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

OFFICIAL_URLS = {
    "삼성전자": ["https://www.samsungcareers.com/hr/"],
    "SK하이닉스": ["https://www.skcareers.com/Recruit/Index?searchText="],
    "ASML": ["https://asmlkorea.careerlink.kr/jobs", "https://www.asml.com/en/careers/find-your-job"],
    "Applied Materials": ["https://appliedkorea.applyin.co.kr/jobs/", "https://jobs.appliedmaterials.com/"],
    "Lam Research": ["https://lamresearch-recruit.com/jobs", "https://careers.lamresearch.com/careers"],
    "KLA": ["https://kla.wd1.myworkdayjobs.com/Search"],
    "Tokyo Electron": ["https://tel.recruiter.co.kr/career/career"],
    "Micron": ["https://careers.micron.com/careers"],
    "TSMC": ["https://www.tsmc.com/static/english/careers/index.htm"],
    "Intel": ["https://intel.wd1.myworkdayjobs.com/External"],
    "NVIDIA": ["https://nvidia.eightfold.ai/careers"],
    "AMD": ["https://careers.amd.com/careers-home/jobs"]
}

_driver_path = None
_driver_path_lock = threading.Lock()


def get_driver_path():
    global _driver_path
    with _driver_path_lock:
        if _driver_path is None:
            _driver_path = ChromeDriverManager().install()
    return _driver_path


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    driver = webdriver.Chrome(service=Service(get_driver_path()), options=options)
    driver.set_page_load_timeout(15)
    return driver


def connect_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    sheet = gspread.authorize(creds).open_by_url(SHEET_URL).worksheet("채용 공고 (박사)")
    try:
        existing_links = set(sheet.col_values(13))
    except Exception:
        existing_links = set()
    return sheet, existing_links


def is_target_company(actual, target):
    return target.lower().replace(" ", "") in actual.lower().replace(" ", "")


def create_job_row(source, company, title, link):
    today = datetime.today().strftime('%Y-%m-%d')
    return [today, source, today, "상시", company, title, "AI 대기", "AI 대기", "AI 대기", "AI 대기", "AI 대기", "AI 대기", link]


def load_page(driver, url):
    try:
        driver.get(url)
        time.sleep(1.5)
        return True
    except Exception:
        return False


def scrape_portal_info(company_name, driver, local_links):
    job_list = []

    if load_page(driver, f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={company_name}+석박사"):
        try:
            for job in driver.find_elements(By.CSS_SELECTOR, '.item_recruit')[:5]:
                link = job.find_element(By.CSS_SELECTOR, '.job_tit a').get_attribute('href')
                if link in local_links:
                    continue
                if is_target_company(job.find_element(By.CSS_SELECTOR, '.corp_name').text, company_name):
                    title = job.find_element(By.CSS_SELECTOR, '.job_tit a').text.strip()
                    job_list.append(create_job_row("사람인", company_name, title, link))
                    local_links.add(link)
        except Exception:
            pass

    if load_page(driver, f"https://www.jobkorea.co.kr/Search/?stext={company_name}+석박사"):
        try:
            for job in driver.find_elements(By.CSS_SELECTOR, '.list-default .post')[:5]:
                title_elem = job.find_element(By.CSS_SELECTOR, '.title')
                link = title_elem.get_attribute('href')
                if link in local_links:
                    continue
                if is_target_company(job.find_element(By.CSS_SELECTOR, '.name').text, company_name):
                    job_list.append(create_job_row("잡코리아", company_name, title_elem.text.strip(), link))
                    local_links.add(link)
        except Exception:
            pass

    if load_page(driver, f"https://www.linkedin.com/jobs/search/?keywords={company_name}%20Master%20OR%20Ph.D"):
        try:
            time.sleep(1)
            for job in driver.find_elements(By.CSS_SELECTOR, '.base-card')[:5]:
                link = job.find_element(By.CSS_SELECTOR, 'a.base-card__full-link').get_attribute('href')
                if link.split('?')[0] in {e.split('?')[0] for e in local_links}:
                    continue
                if is_target_company(job.find_element(By.CSS_SELECTOR, '.base-search-card__subtitle').text, company_name):
                    title = job.find_element(By.CSS_SELECTOR, '.base-search-card__title').text.strip()
                    job_list.append(create_job_row("LinkedIn", company_name, title, link))
                    local_links.add(link)
        except Exception:
            pass

    return job_list


def scrape_official_pages(company_name, driver, local_links):
    job_list = []
    urls = OFFICIAL_URLS.get(company_name, [])
    for url in urls:
        if load_page(driver, url):
            time.sleep(1.5)
            found_count = 0
            for elem in driver.find_elements(By.TAG_NAME, 'a'):
                if found_count >= 3:
                    break
                try:
                    link = elem.get_attribute('href')
                    title = elem.text.strip()
                    if not link or len(title) < 5 or link in local_links:
                        continue
                    valid_keywords = ['/job', '/req', 'jobid=', '/career', '/position', 'detail', 'posting', 'recruit']
                    if any(keyword in link.lower() for keyword in valid_keywords):
                        job_list.append(create_job_row("공식 홈페이지", company_name, title, link))
                        local_links.add(link)
                        found_count += 1
                except Exception:
                    continue
    return job_list


def scrape_company(company, existing_links_snapshot):
    driver = make_driver()
    local_links = set(existing_links_snapshot)
    job_list = []
    try:
        print(f"  \u25b6 [{company}] 수집 시작...")
        job_list.extend(scrape_portal_info(company, driver, local_links))
        job_list.extend(scrape_official_pages(company, driver, local_links))
        print(f"  \u2713 [{company}] {len(job_list)}개 발견")
    except Exception as e:
        print(f"  \u2717 [{company}] 오류: {e}")
    finally:
        driver.quit()
    return job_list


if __name__ == "__main__":
    print("📊 [수집봇] 구글 시트 연결 중...")
    sheet, existing_links = connect_google_sheet()
    existing_links_snapshot = frozenset(existing_links)

    print("🔧 ChromeDriver 준비 중...")
    get_driver_path()

    print(f"\n🤖 [수집봇] {MAX_WORKERS}개 병렬 스레드로 탐색 시작 (직 {len(TARGET_COMPANIES)}개 회사)...")
    all_results = []
    dedup_lock = threading.Lock()
    seen_links = set(existing_links)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scrape_company, company, existing_links_snapshot): company
            for company in TARGET_COMPANIES
        }
        for future in as_completed(futures):
            jobs = future.result()
            with dedup_lock:
                for job in jobs:
                    link = job[12]
                    if link not in seen_links:
                        seen_links.add(link)
                        all_results.append(job)

    if all_results:
        print(f"\n📝 새로운 공고 {len(all_results)}개를 시트에 일괄 등록합니다.")
        sheet.append_rows(all_results, value_input_option='USER_ENTERED')
    else:
        print("\n✨ 새로 올라온 공고가 없습니다.")

    print("\n🛑 [수집봇] 안전하게 종료되었습니다.")
