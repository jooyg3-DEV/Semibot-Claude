"""
5. 분배봇 (distribute.py)
- 채용공고 시트의 모든 행을 회사별 탭으로 분배
- 탭이 없으면 자동 생성, 있으면 내용 갱신
- 취소선(N열=="만료") 서식도 그대로 복제
- 채용공고 시트는 그대로 유지 (마스터 시트)
"""
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

import config

# 채용공고 헤더 (13열)
HEADER = ["검색일", "순위", "출처", "마감일", "상시", "회사", "공고명",
          "지원자격", "채용직무", "근무지", "채용형태", "박사우대", "링크"]

COL_COMPANY = 5   # F열 (0-based): 회사명
COL_EXPIRED = 13  # N열 (1-based=14): "만료" 표시 (checker.py가 기록)


def connect_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(config.CREDENTIALS_FILE, scope)
    wb = gspread.authorize(creds).open_by_url(config.SHEET_URL)
    sheet_main = wb.worksheet(config.SHEET_TAB)
    return wb, sheet_main


def get_or_create_tab(wb, tab_name: str):
    """탭이 없으면 새로 생성, 있으면 반환."""
    try:
        ws = wb.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = wb.add_worksheet(title=tab_name, rows=500, cols=14)
        print(f"  📄 새 탭 생성: {tab_name}")
    return ws


def write_company_tab(wb, company: str, rows: list, expired_set: set):
    """
    회사별 탭에 헤더 + 행 데이터 쓰기.
    expired_set: 원본 채용공고에서 해당 회사 행의 row_num(1-based) 집합
    """
    ws = get_or_create_tab(wb, company)

    # 기존 내용 초기화
    ws.clear()
    time.sleep(0.5)

    # 헤더 + 데이터 한번에 쓰기
    all_data = [HEADER] + [r["data"] for r in rows]
    ws.update(all_data, value_input_option='USER_ENTERED')
    time.sleep(0.5)

    # 취소선 서식 복제 (만료 행)
    expired_in_tab = [i + 2 for i, r in enumerate(rows) if r["expired"]]  # 헤더(1행) 제외, 1-based
    for tab_row_num in expired_in_tab:
        ws.format(f"A{tab_row_num}:M{tab_row_num}", {
            "textFormat": {"strikethrough": True}
        })
        time.sleep(0.2)

    status = f"{len(rows)}개 공고"
    if expired_in_tab:
        status += f" (만료 {len(expired_in_tab)}개 취소선)"
    print(f"  ✓ [{company}] {status}")


if __name__ == "__main__":
    print("📊 [분배봇] 구글 시트 연결 중...")
    wb, sheet_main = connect_sheets()

    # ── 마스터 시트 전체 읽기 ────────────────────────────────
    print("  채용공고 시트 읽는 중...")
    all_rows = sheet_main.get_all_values()
    if not all_rows:
        print("❌ 채용공고 시트가 비어 있습니다.")
        exit(0)

    # N열(만료 표시) 읽기
    n_col = sheet_main.col_values(14)  # 1-based → 14 = N열

    # 헤더 행 스킵
    data_rows = all_rows[1:]

    # ── 회사별 행 분류 ────────────────────────────────────────
    company_map: dict[str, list] = {}
    for i, row in enumerate(data_rows):
        if len(row) < 13:
            continue
        company = row[COL_COMPANY].strip()
        if not company:
            continue
        # N열 만료 여부 (원본 행 번호 = i+2, 1-based, 헤더 제외)
        n_val = n_col[i + 1] if (i + 1) < len(n_col) else ""
        is_expired = (n_val == "만료")

        if company not in company_map:
            company_map[company] = []
        company_map[company].append({
            "data": row[:13],     # A~M 열만 (13열)
            "expired": is_expired,
        })

    # ── 회사 정렬: config.COMPANIES 순서 우선 ────────────────
    config_order = [c["name"] for c in config.COMPANIES]
    known   = [c for c in config_order if c in company_map]
    unknown = sorted(c for c in company_map if c not in config_order)
    ordered_companies = known + unknown

    print(f"\n🏢 총 {len(ordered_companies)}개 회사 탭 분배 시작...")

    for company in ordered_companies:
        rows = company_map[company]
        write_company_tab(wb, company, rows, set())
        time.sleep(0.3)  # API rate limit 방지

    print(f"\n✅ [분배봇] 완료 — {len(ordered_companies)}개 탭 갱신됨.")
