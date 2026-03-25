import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from selenium.webdriver.common.by import By

import config
import utils


def load(driver, url, wait=2):
    try:
        driver.get(url)
        time.sleep(wait)
        return True
    except Exception:
        return False


def company_match(text, company):
    t = text.lower().replace(" ", "")
    return (
        company["name"].lower().replace(" ", "") in t or
        company["search_kr"].lower().replace(" ", "") in t or
        company["search_en"].lower().replace(" ", "") in t
    )


# ── 사람인 ───────────────────────────────────────────────────
def scrape_saramin(company, driver, seen):
    results = []
    kw = quote(company["search_kr"])
    if not load(driver, f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={kw}&recruitPageCount=40"):
        return results
    try:
        for item in driver.find_elements(By.CSS_SELECTOR, ".item_recruit"):
            try:
                a = item.find_element(By.CSS_SELECTOR, ".job_tit a")
                title, link = a.text.strip(), a.get_attribute("href")
                if not title or not link or link in seen:
                    continue
                corp = item.find_element(By.CSS_SELECTOR, ".corp_name").text
                if not company_match(corp, company):
                    continue
                try:
                    loc = item.find_element(By.CSS_SELECTOR, ".work_place").text.strip()
                except Exception:
                    loc = "한국"
                if utils.is_china(loc):
                    continue
                strength = utils.match_title(title)
                if not strength:
                    continue
                results.append(utils.make_row("사람인", company["priority"], company["name"], title, loc, strength, link))
                seen.add(link)
            except Exception:
                continue
    except Exception:
        pass
    return results


# ── 잡코리아 ─────────────────────────────────────────────────
def scrape_jobkorea(company, driver, seen):
    results = []
    kw = quote(company["search_kr"])
    if not load(driver, f"https://www.jobkorea.co.kr/Search/?stext={kw}"):
        return results
    try:
        for item in driver.find_elements(By.CSS_SELECTOR, ".list-default .post"):
            try:
                a = item.find_element(By.CSS_SELECTOR, ".title")
                title, link = a.text.strip(), a.get_attribute("href")
                if not title or not link or link in seen:
                    continue
                try:
                    corp = item.find_element(By.CSS_SELECTOR, ".name").text
                except Exception:
                    corp = ""
                if corp and not company_match(corp, company):
                    continue
                try:
                    loc = item.find_element(By.CSS_SELECTOR, ".loc").text.strip()
                except Exception:
                    loc = "한국"
                if utils.is_china(loc):
                    continue
                strength = utils.match_title(title)
                if not strength:
                    continue
                results.append(utils.make_row("잡코리아", company["priority"], company["name"], title, loc, strength, link))
                seen.add(link)
            except Exception:
                continue
    except Exception:
        pass
    return results


# ── LinkedIn ─────────────────────────────────────────────────
def scrape_linkedin(company, driver, seen):
    results = []
    kw = quote(company["search_en"])
    if not load(driver, f"https://www.linkedin.com/jobs/search/?keywords={kw}&f_TPR=r2592000", wait=3):
        return results
    try:
        for card in driver.find_elements(By.CSS_SELECTOR, ".base-card"):
            try:
                a = card.find_element(By.CSS_SELECTOR, "a.base-card__full-link")
                title = card.find_element(By.CSS_SELECTOR, ".base-search-card__title").text.strip()
                link = a.get_attribute("href").split("?")[0]
                if not title or not link or link in seen:
                    continue
                try:
                    loc = card.find_element(By.CSS_SELECTOR, ".job-search-card__location").text.strip()
                except Exception:
                    loc = ""
                if utils.is_china(loc):
                    continue
                strength = utils.match_title(title)
                if not strength:
                    continue
                results.append(utils.make_row("LinkedIn", company["priority"], company["name"], title, loc, strength, link))
                seen.add(link)
            except Exception:
                continue
    except Exception:
        pass
    return results


# ── 잡다 ─────────────────────────────────────────────────────
def scrape_jobda(company, driver, seen):
    results = []
    kw = quote(company["search_kr"])
    if not load(driver, f"https://www.jobda.im/position?keyword={kw}", wait=3):
        return results
    try:
        for item in driver.find_elements(By.CSS_SELECTOR, "li"):
            try:
                a = item.find_element(By.CSS_SELECTOR, "a")
                link = a.get_attribute("href") or ""
                if not link.startswith("http"):
                    link = "https://www.jobda.im" + link
                title = ""
                for sel in [".position-name", ".title", "h3", "h4", "h2", "strong"]:
                    try:
                        title = item.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if title:
                            break
                    except Exception:
                        continue
                if not title or len(title) < 3 or link in seen:
                    continue
                if not company_match(item.text, company):
                    continue
                strength = utils.match_title(title)
                if not strength:
                    continue
                results.append(utils.make_row("잡다", company["priority"], company["name"], title, "", strength, link))
                seen.add(link)
            except Exception:
                continue
    except Exception:
        pass
    return results


# ── 공식 채용 페이지 ─────────────────────────────────────────
JOB_URL_PATTERNS = [
    "/job", "/req", "jobid=", "/career", "/position",
    "detail", "posting", "recruit", "/apply", "jobdetail",
    "/opening", "/vacancy", "/opportunity",
]

def scrape_official(company, driver, seen):
    results = []
    for url in config.OFFICIAL_URLS.get(company["name"], []):
        try:
            if not load(driver, url, wait=3):
                continue
            for a in driver.find_elements(By.TAG_NAME, "a"):
                try:
                    link = a.get_attribute("href") or ""
                    title = a.text.strip()
                    if not link or len(title) < 4 or link in seen:
                        continue
                    if not any(p in link.lower() for p in JOB_URL_PATTERNS):
                        continue
                    if utils.is_china(title) or utils.is_china(link):
                        continue
                    strength = utils.match_title(title)
                    if not strength:
                        continue
                    results.append(utils.make_row("공식홈페이지", company["priority"], company["name"], title, "", strength, link))
                    seen.add(link)
                except Exception:
                    continue
        except Exception:
            continue
    return results


# ── 회사 1개 처리 (스레드 워커) ──────────────────────────────
def scrape_company(company, seen_snapshot):
    driver = utils.make_driver()
    seen = set(seen_snapshot)
    jobs = []
    name = company["name"]
    try:
        print(f"  ▶ [{name}] 수집 시작...")
        jobs += scrape_saramin(company, driver, seen)
        jobs += scrape_jobkorea(company, driver, seen)
        jobs += scrape_linkedin(company, driver, seen)
        jobs += scrape_jobda(company, driver, seen)
        jobs += scrape_official(company, driver, seen)
        print(f"  ✓ [{name}] {len(jobs)}개 수집")
    except Exception as e:
        print(f"  ✗ [{name}] 오류: {e}")
    finally:
        driver.quit()
    return jobs


# ── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("📊 구글 시트 연결 중...")
    sheet = utils.connect_sheet()
    existing = sheet.get_all_values()
    seen_links = {
        row[config.COL_링크]
        for row in existing
        if len(row) > config.COL_링크 and row[config.COL_링크]
    }
    print(f"  기존 공고: {len(seen_links)}개")

    print(f"\n🤖 {config.MAX_WORKERS}개 병렬 스레드 | {len(config.COMPANIES)}개 회사 수집 시작...")
    all_results = []
    lock = threading.Lock()
    global_seen = set(seen_links)

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        futures = {
            ex.submit(scrape_company, c, frozenset(seen_links)): c
            for c in config.COMPANIES
        }
        for future in as_completed(futures):
            jobs = future.result()
            with lock:
                for job in jobs:
                    link = job[config.COL_링크]
                    if link not in global_seen:
                        global_seen.add(link)
                        all_results.append(job)

    if all_results:
        print(f"\n📝 새 공고 {len(all_results)}개 저장 중...")
        sheet.append_rows(all_results, value_input_option="USER_ENTERED")
    else:
        print("\n✨ 새 공고 없음")

    print("\n🛑 스크래퍼 완료")
