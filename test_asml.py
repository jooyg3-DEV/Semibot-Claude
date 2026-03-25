"""ASML 공식 페이지 수집 빠른 검증 스크립트 (시트 미기록)"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from utils import match_title, is_china

URL = "https://www.asml.com/en/careers/find-your-job"
QUERIES = ["process engineer Master PhD", "field service engineer semiconductor", "application engineer"]
VALID_URL_KW = ['/job', '/req', 'jobid=', '/career', '/position', 'detail', 'posting', 'recruit']

def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(15)
    return driver

def scroll_to_load(driver):
    for _ in range(4):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

def collect_links(driver):
    found = []
    for elem in driver.find_elements(By.TAG_NAME, 'a'):
        try:
            link = elem.get_attribute('href') or ''
            title = elem.text.strip()
            if len(title) < 5 or not any(kw in link.lower() for kw in VALID_URL_KW):
                continue
            strength = match_title(title)
            if strength is None or is_china(title + ' ' + link):
                continue
            found.append((strength, title, link))
        except Exception:
            continue
    return found

driver = make_driver()
all_found = {}

for query in QUERIES:
    print(f"\n🔍 검색: '{query}'")
    driver.get(URL)
    time.sleep(3)
    scroll_to_load(driver)

    # 검색창 시도
    searched = False
    for sel in ['input[type="search"]', 'input[placeholder*="Search" i]', 'input[placeholder*="Job" i]']:
        try:
            box = driver.find_element(By.CSS_SELECTOR, sel)
            if box.is_displayed():
                box.clear()
                box.send_keys(query)
                box.send_keys(Keys.RETURN)
                time.sleep(2)
                scroll_to_load(driver)
                searched = True
                break
        except Exception:
            continue

    if not searched:
        print("  ⚠️  검색창 없음 — 전체 링크 수집")

    for strength, title, link in collect_links(driver):
        if link not in all_found:
            all_found[link] = (strength, title)

driver.quit()

print(f"\n{'='*60}")
print(f"총 {len(all_found)}개 발견")
print(f"{'='*60}")
for link, (strength, title) in sorted(all_found.items(), key=lambda x: x[1][0]):
    print(f"  [{strength}] {title}")
    print(f"       {link}")
