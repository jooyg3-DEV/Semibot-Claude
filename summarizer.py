"""
2. 원문 수집봇 (summarizer.py)
- 채용공고 시트에서 H열 == "AI 대기" 행을 읽음
- 각 링크 페이지 방문 → 원문 텍스트 수집
- 원문 시트에 텍스트 기록
- 채용공고 시트 H열 = "분석대기", L열 = 박사우대 업데이트
"""
import time
import gspread
from concurrent.futures import ThreadPoolExecutor, as_completed

from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By

import config

BATCH_SIZE  = None  # None = 전체 처리
MAX_WORKERS = 3


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)  # Workday/SPA 페이지 대비 (기존 15s)
    return driver


def connect_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(config.CREDENTIALS_FILE, scope)
    wb = gspread.authorize(creds).open_by_url(config.SHEET_URL)
    sheet_main = wb.worksheet(config.SHEET_TAB)      # 채용공고
    sheet_raw  = wb.worksheet(config.SHEET_TAB_RAW)  # 원문
    return sheet_main, sheet_raw


def process_single_job(task):
    """페이지 원문 수집."""
    row_num, row_data = task
    company = row_data[5]   # F열 (0-based)
    link    = row_data[12]  # M열 (0-based) — 13열 구조
    print(f"  ▶ [{company}] 원문 수집 중... (행: {row_num})")

    # Workday/Eightfold SPA는 JS 렌더링에 추가 시간 필요
    _SPA_DOMAINS = ('workdayjobs.com', 'careers.amd.com', 'careers.micron.com',
                    'careers.tsmc.com', 'eightfold.ai', 'careers.lamresearch.com')

    driver = make_driver()
    try:
        driver.get(link)
        time.sleep(3)
        if any(d in link for d in _SPA_DOMAINS):
            time.sleep(4)  # SPA 추가 대기
        text = driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception:
        return row_num, row_data, None, "페이지 접속 불가"
    finally:
        driver.quit()

    if not text or len(text) < 50:
        return row_num, row_data, None, "내용 없음"

    has_phd = any(kw in text.lower() for kw in config.PHD_KEYWORDS)
    print(f"      [완료] {company} {len(text)}자 수집 / 박사우대: {'있음' if has_phd else '없음'}")
    return row_num, row_data, {"text": text[:5000], "has_phd": has_phd}, None


if __name__ == "__main__":
    print("📊 [원문수집봇] 구글 시트 연결 중...")
    sheet_main, sheet_raw = connect_sheets()

    # ── 원문 시트 헤더 확인/초기화 ──────────────────────────────
    raw_header = sheet_raw.row_values(1)
    if not raw_header or raw_header[0] != "검색일":
        sheet_raw.insert_row(
            ["검색일", "순위", "출처", "마감일", "회사", "공고명", "직무설명", "링크"],
            index=1
        )
        print("  원문 시트 헤더 초기화 완료")

    # ── 채용공고에서 AI 대기 행 수집 ────────────────────────────
    print("\n🤖 [원문수집봇] 'AI 대기' 항목 수집 시작...")
    all_rows = sheet_main.get_all_values()
    pending = []
    RETRY_STATUSES = {"페이지 접속 불가", "내용 없음", "오류"}
    for i, row in enumerate(all_rows):
        if len(row) < 13:
            continue
        status = row[7]
        link = row[12]
        # 링크가 URL 형식이 아니면 14열 구조 구버전 행 → 건너뜀
        if not link.startswith("http"):
            continue
        if status == "AI 대기" or status in RETRY_STATUSES:
            pending.append((i + 1, row))  # 1-based row number

    if not pending:
        print("✨ 처리할 항목이 없습니다.")
    else:
        tasks = pending if BATCH_SIZE is None else pending[:BATCH_SIZE]
        print(f"🚦 총 {len(pending)}개 처리 시작 ({MAX_WORKERS}개 병렬)...")

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_single_job, t): t for t in tasks}
            for future in as_completed(futures):
                row_num, row_data, data, error = future.result()
                results[row_num] = (row_data, data, error)

        # ── 원문 시트에 일괄 append ──────────────────────────────
        print("\n📝 원문 시트에 기록 중...")
        raw_rows = []
        for row_num in sorted(results):
            row_data, data, error = results[row_num]
            if data:
                raw_rows.append([
                    row_data[0],   # 검색일
                    row_data[1],   # 순위
                    row_data[2],   # 출처
                    row_data[3],   # 마감일
                    row_data[5],   # 회사
                    row_data[6],   # 공고명
                    data["text"],  # 직무설명 (원문)
                    row_data[12],  # 링크
                ])
        if raw_rows:
            sheet_raw.append_rows(raw_rows, value_input_option='USER_ENTERED')
            print(f"  ✓ 원문 시트 {len(raw_rows)}개 행 추가")

        # ── 채용공고 시트 업데이트 ───────────────────────────────
        print("📝 채용공고 시트 상태 업데이트 중...")
        main_cells = []
        for row_num, (row_data, data, error) in results.items():
            if data:
                # H(8): "분석대기" → analyzer가 처리할 것임을 표시
                # L(12): 박사우대
                main_cells.append(gspread.Cell(row_num, 8,  "분석대기"))
                main_cells.append(gspread.Cell(row_num, 12, "있음" if data["has_phd"] else "없음"))
            else:
                # 오류: H에 오류 메시지
                main_cells.append(gspread.Cell(row_num, 8, error or "오류"))

        if main_cells:
            sheet_main.update_cells(main_cells, value_input_option='USER_ENTERED')
            print(f"  ✓ 채용공고 시트 {len(results)}개 행 업데이트")

    print("\n🛑 [원문수집봇] 완료.")
