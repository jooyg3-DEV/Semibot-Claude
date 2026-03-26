"""
포털 스크래핑 진단 스크립트 (test_portals.py)
- 사람인/잡코리아/잡다/LinkedIn 각각 테스트
- CSS 셀렉터 매칭 여부, 페이지 로딩, 회사명 매칭 상세 출력
- 실행: python test_portals.py [회사명]  (기본값: 삼성전자)
"""
import os
import sys
import time
import urllib.parse

from selenium import webdriver
from selenium.webdriver.common.by import By

# 테스트할 회사 (인자로 지정 가능)
COMPANY_KR = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
COMPANY_EN = {
    "삼성전자": "Samsung Electronics",
    "SK하이닉스": "SK Hynix",
    "ASML": "ASML",
    "Applied Materials": "Applied Materials",
    "KLA": "KLA",
}.get(COMPANY_KR, COMPANY_KR)

LINKEDIN_COOKIE = os.environ.get("LINKEDIN_COOKIE", "")


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(20)
    return driver


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def check_saramin(driver):
    sep(f"사람인 | {COMPANY_KR} (회사명만 검색 → 결과에서 키워드 필터)")
    q = urllib.parse.quote(COMPANY_KR)
    url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={q}"
    print(f"URL: {url}")
    try:
        driver.get(url)
        time.sleep(3)
        print(f"페이지 제목: {driver.title}")
        print(f"현재 URL: {driver.current_url}")

        # 셀렉터 테스트
        selectors = {
            ".item_recruit": "공고 카드",
            ".job_tit a": "공고 제목 링크",
            ".corp_name": "회사명",
            ".company_name": "회사명(대체)",
            "h2.job_tit": "제목(h2)",
        }
        for sel, desc in selectors.items():
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"  [{desc}] '{sel}' → {len(elems)}개 발견")
            for e in elems[:3]:
                print(f"    텍스트: {e.text[:80]!r}")

        # 회사명 매칭 확인
        items = driver.find_elements(By.CSS_SELECTOR, '.item_recruit')
        if items:
            print(f"\n첫 번째 카드 전체 텍스트:\n{items[0].text[:300]}")
        else:
            # 대안 셀렉터 탐색
            print("\n⚠️  .item_recruit 없음. 페이지 내 주요 셀렉터 탐색:")
            for tag in ['article', 'li.item', 'div.list_item', '.recruit_list li']:
                found = driver.find_elements(By.CSS_SELECTOR, tag)
                if found:
                    print(f"  대안 '{tag}' → {len(found)}개")
                    print(f"    샘플: {found[0].text[:100]!r}")
    except Exception as e:
        print(f"❌ 오류: {e}")


def check_jobkorea(driver):
    sep(f"잡코리아 | {COMPANY_KR} (회사명만 검색 → 링크 패턴 추출 → 키워드 필터)")
    q = urllib.parse.quote(COMPANY_KR)
    url = f"https://www.jobkorea.co.kr/Search/?stext={q}"
    print(f"URL: {url}")
    try:
        driver.get(url)
        time.sleep(3)
        print(f"페이지 제목: {driver.title}")
        print(f"현재 URL: {driver.current_url}")

        selectors = {
            ".list-default .post": "공고 카드",
            ".post .title": "공고 제목",
            ".post .name": "회사명",
            ".recruiting-item": "공고 카드(대체)",
            ".list_recruiting .item": "공고 리스트",
            "article.list-item": "공고 article",
        }
        for sel, desc in selectors.items():
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"  [{desc}] '{sel}' → {len(elems)}개 발견")
            for e in elems[:2]:
                print(f"    텍스트: {e.text[:80]!r}")

        # 결과 없음 문구 확인
        body = driver.find_element(By.TAG_NAME, "body").text
        if "검색 결과가 없" in body or "결과가 없습니다" in body:
            print("⚠️  검색 결과 없음 메시지 감지")
        print(f"\n페이지 body 일부:\n{body[:500]}")
    except Exception as e:
        print(f"❌ 오류: {e}")


def check_jobda(driver):
    sep(f"잡다 | {COMPANY_KR} (회사명만 검색 후 회사 매칭)")
    q = urllib.parse.quote(COMPANY_KR)
    url = f"https://www.jobda.im/position?keyword={q}"
    print(f"URL: {url}")
    try:
        driver.get(url)
        time.sleep(4)  # 잡다는 SPA
        print(f"페이지 제목: {driver.title}")
        print(f"현재 URL: {driver.current_url}")

        selectors = {
            "li": "리스트 아이템(현재 사용중)",
            ".position-card": "포지션 카드",
            "[class*=position]": "position 포함 클래스",
            "[class*=card]": "card 포함 클래스",
            "[class*=item]": "item 포함 클래스",
            "article": "article",
        }
        for sel, desc in selectors.items():
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"  [{desc}] '{sel}' → {len(elems)}개 발견")
            for e in elems[:2]:
                t = e.text.strip()
                if t:
                    print(f"    텍스트: {t[:80]!r}")

        body = driver.find_element(By.TAG_NAME, "body").text
        if "검색 결과" in body or "포지션" in body:
            print(f"\n페이지 body 일부:\n{body[:500]}")
        else:
            print(f"\n⚠️ 페이지 내용이 비어있거나 SPA 렌더링 실패 가능성")
            print(f"body 앞부분: {body[:200]!r}")
    except Exception as e:
        print(f"❌ 오류: {e}")


def check_linkedin(driver):
    sep(f"LinkedIn | {COMPANY_EN} (회사명만 검색 → 키워드 필터)")
    if not LINKEDIN_COOKIE:
        print("⚠️  LINKEDIN_COOKIE 환경변수가 없음 → 건너뜀")
        print("   실행 방법: LINKEDIN_COOKIE=xxx python test_portals.py")
        return

    try:
        driver.get("https://www.linkedin.com")
        time.sleep(2)
        driver.add_cookie({
            "name": "li_at", "value": LINKEDIN_COOKIE,
            "domain": ".linkedin.com", "path": "/", "secure": True
        })

        kw = urllib.parse.quote(f'"{COMPANY_EN}"')
        url = f"https://www.linkedin.com/jobs/search/?keywords={kw}&sortBy=DD&f_TPR=r2592000"
        print(f"URL: {url}")
        driver.get(url)
        time.sleep(6)
        try:
            driver.execute_script("window.scrollTo(0, 600);")
            time.sleep(1.5)
        except Exception:
            pass
        print(f"페이지 제목: {driver.title}")
        cur = driver.current_url
        print(f"현재 URL: {cur}")

        if "login" in cur or "authwall" in cur or "signup" in cur:
            print("❌ 쿠키 만료 또는 인증 실패 → 로그인 페이지로 리디렉션됨")
            return

        print("✓ 쿠키 인증 성공 (로그인 페이지 아님)")

        selectors = {
            "li.jobs-search-results__list-item": "2024+ 검색결과 리스트",
            ".jobs-search-results-list li": "검색결과 리스트(ul>li)",
            "[data-occludable-job-id]": "job-id 속성",
            ".job-card-container": "job-card-container(구)",
            ".jobs-search__results-list > li": "검색결과 리스트(구)",
            ".scaffold-layout__list-item": "scaffold 리스트(구)",
            ".base-card": "base-card(구)",
        }
        for sel, desc in selectors.items():
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"  [{desc}] '{sel}' → {len(elems)}개 발견")
            for e in elems[:2]:
                t = e.text.strip()
                if t:
                    print(f"    텍스트: {t[:100]!r}")

        # 셀렉터 전부 0이면 body 출력으로 원인 진단
        total_found = sum(len(driver.find_elements(By.CSS_SELECTOR, s)) for s in selectors)
        if total_found == 0:
            body = driver.find_element(By.TAG_NAME, "body").text
            print(f"\n⚠️  모든 셀렉터 0개. body 앞 500자:\n{body[:500]}")
    except Exception as e:
        print(f"❌ 오류: {e}")


if __name__ == "__main__":
    print(f"\n🔍 포털 스크래핑 진단 시작 (테스트 회사: {COMPANY_KR})")
    driver = make_driver()
    try:
        check_saramin(driver)
        check_jobkorea(driver)
        check_jobda(driver)
        check_linkedin(driver)
    finally:
        driver.quit()
    print("\n\n✅ 진단 완료")
