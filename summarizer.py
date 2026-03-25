import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By

import config

# ==========================================
# ⚙️ [설정]
# ==========================================
SHEET_URL = os.environ.get("SHEET_URL", "여기에_구글_스프레드시트_URL을_붙여넣으세요")
BATCH_SIZE = None   # None = 전체 처리
MAX_WORKERS = 3     # 병렬 처리 (API 제한 없으므로 확대)


def make_driver():
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
    return gspread.authorize(creds).open_by_url(SHEET_URL).worksheet("채용공고")


def process_single_job(task):
    """페이지 원문을 그대로 추출 (AI 없음)"""
    row_num, row_data = task
    company_name = row_data[5]   # F열: 회사
    job_link = row_data[13]      # N열: 링크
    print(f"  ▶ [{company_name}] 원문 수집 중... (행: {row_num})")

    driver = make_driver()
    try:
        driver.get(job_link)
        time.sleep(3)
        text = driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception:
        return row_num, None, "페이지 접속 불가"
    finally:
        driver.quit()

    if not text or len(text) < 50:
        return row_num, None, "내용 없음"

    t = text.lower()
    has_phd = any(kw in t for kw in config.PHD_KEYWORDS)
    print(f"      [완료] {company_name} {len(text)}자 수집")
    return row_num, {"직무설명": text[:5000], "박사우대": "있음" if has_phd else "없음"}, None


if __name__ == "__main__":
    print("📊 [수집봇] 구글 시트 연결 중...")
    sheet = connect_google_sheet()

    print("\n🤖 [수집봇] AI 대기 항목 원문 수집 시작...")
    all_rows = sheet.get_all_values()
    pending_tasks = []

    for i, row in enumerate(all_rows):
        if len(row) >= 14 and row[7] == "AI 대기":  # H열: 지원자격
            pending_tasks.append((i + 1, row))

    if not pending_tasks:
        print("✨ 처리할 항목이 없습니다.")
    else:
        tasks_to_process = pending_tasks if BATCH_SIZE is None else pending_tasks[:BATCH_SIZE]
        print(f"🚦 총 {len(pending_tasks)}개 처리 시작 ({MAX_WORKERS}개 병렬)...")

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_single_job, task): task for task in tasks_to_process}
            for future in as_completed(futures):
                row_num, data, error = future.result()
                results[row_num] = (data, error)

        print("\n📝 처리 결과를 시트에 일괄 업데이트 중...")
        all_cells = []
        for row_num, (data, error) in results.items():
            # H(8):지원자격, I(9):채용직무, J(10):근무지, K(11):채용형태, L(12):직무설명, M(13):박사우대
            cell_list = sheet.range(f'H{row_num}:M{row_num}')
            if data:
                cell_list[0].value = "원문참조"
                cell_list[1].value = "원문참조"
                cell_list[2].value = "원문참조"
                cell_list[3].value = "원문참조"
                cell_list[4].value = data["직무설명"]
                cell_list[5].value = data["박사우대"]
            else:
                cell_list[0].value = error or "오류"
            all_cells.extend(cell_list)

        if all_cells:
            sheet.update_cells(all_cells)
            print(f"  ✓ {len(results)}개 행 업데이트 완료")

    print("\n🛑 [수집봇] 안전하게 종료되었습니다.")
