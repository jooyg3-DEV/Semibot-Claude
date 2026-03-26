"""
4. 만료확인봇 (checker.py)
- 채용공고 시트에서 이미 처리된 행(H열이 AI대기/분석대기가 아닌 것) 조회
- 각 링크 방문 → 페이지 만료/삭제 여부 확인
- 만료된 공고: 해당 행 전체에 취소선 서식 적용
- 이미 취소선이 있는 행은 스킵
"""
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By

import config

MAX_WORKERS = 2  # 만료 확인은 순차적으로 진행 (과도한 요청 방지)
BATCH_SIZE  = None  # None = 전체 처리

# 만료/삭제 감지 키워드 (대소문자 무관)
_EXPIRED_KW = [
    # 영어
    "this job is no longer available",
    "this position is no longer available",
    "job is no longer accepting applications",
    "this posting has been closed",
    "posting is no longer available",
    "job posting has expired",
    "position has been filled",
    "this requisition is no longer active",
    "no longer available",
    "page not found",
    "404",
    "job not found",
    "position not found",
    "the page you requested could not be found",
    # 한국어
    "채용이 마감",
    "채용 마감",
    "마감된 공고",
    "접수가 마감",
    "모집이 마감",
    "공고가 종료",
    "해당 공고는 종료",
    "존재하지 않는 페이지",
    "페이지를 찾을 수 없",
]

# 만료로 판단하지 않을 도메인 (메인 채용 홈 리디렉션 감지용 제외)
_ALWAYS_VALID_DOMAINS = ()


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(25)
    return driver


def connect_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(config.CREDENTIALS_FILE, scope)
    wb = gspread.authorize(creds).open_by_url(config.SHEET_URL)
    sheet_main = wb.worksheet(config.SHEET_TAB)
    return sheet_main


def is_expired(driver, link: str) -> tuple[bool, str]:
    """
    링크를 방문해 만료 여부 판단.
    Returns: (expired: bool, reason: str)
    """
    _SPA_DOMAINS = ('workdayjobs.com', 'careers.amd.com', 'careers.micron.com',
                    'careers.tsmc.com', 'eightfold.ai', 'careers.lamresearch.com')
    try:
        driver.get(link)
        time.sleep(2)
        if any(d in link for d in _SPA_DOMAINS):
            time.sleep(3)

        current_url = driver.current_url
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        # 리디렉션: 원래 URL의 경로가 사라지고 루트/채용홈으로 이동
        from urllib.parse import urlparse
        orig_path = urlparse(link).path.rstrip('/')
        curr_path = urlparse(current_url).path.rstrip('/')
        orig_domain = urlparse(link).netloc
        curr_domain = urlparse(current_url).netloc

        # 도메인 변경(외부 리디렉션)은 만료 의심
        if orig_domain and curr_domain and orig_domain != curr_domain:
            return True, f"도메인 변경 리디렉션 ({orig_domain} → {curr_domain})"

        # 경로가 완전히 달라졌고 원래 경로의 주요 부분이 없는 경우
        if orig_path and len(orig_path) > 5:
            # 원래 경로의 마지막 세그먼트가 현재 URL에 없으면 리디렉션으로 판단
            orig_last = orig_path.split('/')[-1]
            if orig_last and len(orig_last) > 5 and orig_last not in current_url:
                # 단, 쿼리 파라미터 기반 검색 URL은 리디렉션 감지 제외
                if '?' not in link:
                    return True, f"페이지 리디렉션 (원래 경로 소실: {orig_last})"

        # 만료 키워드 탐지
        for kw in _EXPIRED_KW:
            if kw.lower() in body_text:
                return True, f"만료 키워드 감지: '{kw}'"

        return False, ""

    except Exception as e:
        return True, f"접속 오류: {str(e)[:80]}"


def get_row_formats(sheet_main) -> dict:
    """
    현재 시트에서 취소선이 적용된 행 번호 세트를 반환.
    gspread의 spreadsheet.get() 대신 batch get formats 사용.
    """
    try:
        # gspread 저수준 API로 A열 서식 조회
        spreadsheet = sheet_main.spreadsheet
        result = spreadsheet.fetch_sheet_metadata()
        # 취소선 정보는 cells API로 가져옴
        # 간단하게: 메모 대신 별도 열(N열)에 "만료" 표시로 관리
        # → N열(14번째) 값이 "만료"인 행은 이미 처리됨
        n_col_vals = sheet_main.col_values(14)  # N열
        strikethrough_rows = set()
        for i, val in enumerate(n_col_vals):
            if val == "만료":
                strikethrough_rows.add(i + 1)  # 1-based
        return strikethrough_rows
    except Exception:
        return set()


if __name__ == "__main__":
    print("📊 [만료확인봇] 구글 시트 연결 중...")
    sheet_main = connect_sheets()

    # ── 이미 처리된 행(N열=="만료") 로드 ───────────────────────
    print("  기존 만료 표시 행 확인 중...")
    already_expired = get_row_formats(sheet_main)
    print(f"  이미 만료 표시된 행: {len(already_expired)}개")

    # ── 확인 대상 행 수집 ────────────────────────────────────
    print("\n🔍 [만료확인봇] 공고 상태 확인 시작...")
    all_rows = sheet_main.get_all_values()

    SKIP_STATUSES = {"AI 대기", "분석대기", ""}
    targets = []
    for i, row in enumerate(all_rows):
        row_num = i + 1
        if row_num in already_expired:
            continue
        if len(row) < 13:
            continue
        status = row[7]   # H열
        link   = row[12]  # M열
        if not link.startswith("http"):
            continue
        if status in SKIP_STATUSES:
            continue
        # 헤더 행 스킵
        if row[0] == "검색일":
            continue
        targets.append((row_num, row))

    if BATCH_SIZE is not None:
        targets = targets[:BATCH_SIZE]

    print(f"🚦 총 {len(targets)}개 링크 확인 예정...")

    if not targets:
        print("✨ 확인할 항목이 없습니다.")
    else:
        expired_rows = []
        driver = make_driver()
        try:
            for idx, (row_num, row_data) in enumerate(targets, 1):
                company = row_data[5] if len(row_data) > 5 else "?"
                link    = row_data[12]
                print(f"  [{idx}/{len(targets)}] {company} (행 {row_num}) {link[:60]}")

                expired, reason = is_expired(driver, link)
                if expired:
                    expired_rows.append((row_num, company, reason))
                    print(f"    ❌ 만료 감지: {reason}")
                else:
                    print(f"    ✓ 유효")

                time.sleep(1)  # 과도한 요청 방지
        finally:
            driver.quit()

        # ── 만료 행에 취소선 + N열 "만료" 표시 ──────────────────
        if expired_rows:
            print(f"\n📝 {len(expired_rows)}개 만료 공고 처리 중...")
            num_cols = config.NUM_COLS  # 12 (A~L) → M포함하면 13

            cells_to_update = []
            format_requests = []

            for row_num, company, reason in expired_rows:
                print(f"  ✗ 행 {row_num} [{company}]: {reason}")
                # N열(14)에 "만료" 기록
                cells_to_update.append(gspread.Cell(row_num, 14, "만료"))

            # N열 값 업데이트
            sheet_main.update_cells(cells_to_update, value_input_option='USER_ENTERED')

            # 취소선 서식 적용 (A~M 열, 각 만료 행)
            # gspread format()은 A1 notation 사용
            for row_num, company, reason in expired_rows:
                range_notation = f"A{row_num}:M{row_num}"
                sheet_main.format(range_notation, {
                    "textFormat": {"strikethrough": True}
                })
                time.sleep(0.3)  # API rate limit 방지

            print(f"\n  ✓ {len(expired_rows)}개 행에 취소선 및 만료 표시 완료")
        else:
            print("\n✨ 만료된 공고가 없습니다.")

    print("\n🛑 [만료확인봇] 완료.")
