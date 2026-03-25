import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By

# ==========================================
# ⚙️ [설정]
# ==========================================
SHEET_URL = os.environ.get("SHEET_URL", "여기에_구글_스프레드시트_URL을_붙여넣으세요")
BATCH_SIZE = 10
MAX_WORKERS = 3
MAX_TEXT_LEN = 3000  # 시트 셀 한도 고려


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
    return gspread.authorize(creds).open_by_url(SHEET_URL).worksheet("채용 공고 (박사)")


def process_single_job(task):
    row_num, row_data = task
    company_name = row_data[4]
    job_link = row_data[12]
    print(f"  \u25b6 [{company_name}] 원문 수집 중... (행: {row_num})")

    driver = make_driver()
    try:
        driver.get(job_link)
        time.sleep(3)
        raw_text = driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception as e:
        print(f"      [오류] 페이지 접속 실패: {e}")
        return row_num, None, "페이지 접속 불가"
    finally:
        driver.quit()

    if not raw_text or len(raw_text) < 30:
        return row_num, None, "텍스트 없음"

    truncated = raw_text[:MAX_TEXT_LEN]
    print(f"      [성공] {company_name} 원문 {len(raw_text)}자 수집 (저장: {len(truncated)}자)")
    return row_num, truncated, None


if __name__ == "__main__":
    print("📊 [수집봇] 구글 시트 연결 중...")
    sheet = connect_google_sheet()

    print("\n🤖 [수집봇] 시트의 빈칸(AI 대기)을 채용 원문으로 채웁니다...")
    all_rows = sheet.get_all_values()
    pending_tasks = []

    for i, row in enumerate(all_rows):
        if len(row) >= 13 and row[6] == "AI 대기":
            pending_tasks.append((i + 1, row))

    if not pending_tasks:
        print("✨ 처리할 항목이 없습니다!")
    else:
        tasks_to_process = pending_tasks[:BATCH_SIZE]
        print(f"🚦 밀린 숙제 {len(pending_tasks)}개 중, {len(tasks_to_process)}개를 {MAX_WORKERS}개 병렬로 처리합니다.")

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_single_job, task): task for task in tasks_to_process}
            for future in as_completed(futures):
                row_num, text, error = future.result()
                results[row_num] = (text, error)

        print("\n📝 처리 결과를 시트에 일괄 업데이트 중...")
        all_cells_to_update = []

        for row_num, (text, error) in results.items():
            if text:
                cell_list = sheet.range(f'G{row_num}:L{row_num}')
                cell_list[0].value = "원문 참조"  # 근무지
                cell_list[1].value = "원문 참조"  # 근무형태
                cell_list[2].value = "원문 참조"  # 지원자격
                cell_list[3].value = "원문 참조"  # 박사우대
                cell_list[4].value = "원문 참조"  # 채용직무
                cell_list[5].value = text         # 직무설명 → 원문 텍스트
                all_cells_to_update.extend(cell_list)
            elif error:
                sheet.update_cell(row_num, 7, error)

        if all_cells_to_update:
            sheet.update_cells(all_cells_to_update)
            success_count = sum(1 for t, e in results.values() if t)
            print(f"  ✓ {success_count}개 행 업데이트 완료")

    print("\n🛑 [수집봇] 안전하게 종료되었습니다.")
