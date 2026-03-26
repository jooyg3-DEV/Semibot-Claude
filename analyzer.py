"""
3. 분석봇 (analyzer.py)
- 채용공고 시트에서 H열 == "분석대기" 행을 읽음
- 원문 시트에서 링크 기준으로 직무설명 원문을 조회
- 원문에서 지원자격/채용직무/근무지/채용형태 규칙 기반 추출
- 채용공고 시트 H(지원자격), I(채용직무), J(근무지), K(채용형태) 업데이트
"""
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials

import config

BATCH_SIZE = None  # None = 전체 처리


def connect_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(config.CREDENTIALS_FILE, scope)
    wb = gspread.authorize(creds).open_by_url(config.SHEET_URL)
    sheet_main = wb.worksheet(config.SHEET_TAB)      # 채용공고
    sheet_raw  = wb.worksheet(config.SHEET_TAB_RAW)  # 원문
    return sheet_main, sheet_raw


# ── 섹션 헤더 패턴 (한국어 / 영어) ──────────────────────────────
_SECTION_PATTERNS = {
    "지원자격": [
        r"(?:지원\s*자격|자격\s*요건|필수\s*요건|요구\s*사항|Required Qualifications?|"
        r"Minimum Qualifications?|Basic Qualifications?|Requirements?)",
    ],
    "채용직무": [
        r"(?:채용\s*직무|담당\s*업무|주요\s*업무|직무\s*소개|업무\s*내용|"
        r"Job\s*Description|Responsibilities|What\s+you['']ll\s+do|Role\s*&?\s*Responsibilities)",
    ],
    "근무지": [
        r"(?:근무\s*지|근무\s*위치|위치|Location|Work\s*Location|Office\s*Location)",
    ],
    "채용형태": [
        r"(?:채용\s*형태|고용\s*형태|근무\s*형태|Employment\s*Type|Job\s*Type|Work\s*Type)",
    ],
}

# 단일 줄에서 직접 값 추출 (짧은 필드용)
_INLINE_PATTERNS = {
    "근무지": [
        r"(?:근무지|근무\s*위치|Location)[^\n:：]*[:：]\s*(.+)",
        r"(?:Location|Office)[^\n:：]*[:：]\s*(.+)",
    ],
    "채용형태": [
        r"(?:채용\s*형태|고용\s*형태|Employment\s*Type|Job\s*Type)[^\n:：]*[:：]\s*(.+)",
        r"\b(정규직|계약직|인턴|Full[- ]?[Tt]ime|Part[- ]?[Tt]ime|Contract|Permanent)\b",
    ],
}


def _extract_section(text: str, field: str) -> str:
    """섹션 헤더 이후 텍스트 블록을 추출한다."""
    patterns = _SECTION_PATTERNS.get(field, [])
    for pat in patterns:
        m = re.search(
            r"(?:" + pat + r")\s*[:\n]+([\s\S]{10,600}?)(?=\n\s*[A-Z가-힣][^\n]{0,30}[:\n]|\Z)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return ""


def _extract_inline(text: str, field: str) -> str:
    """인라인 패턴(한 줄)으로 값을 추출한다."""
    for pat in _INLINE_PATTERNS.get(field, []):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_fields(text: str) -> dict:
    """원문 텍스트에서 4개 필드를 규칙 기반으로 추출한다."""
    result = {}
    for field in ("지원자격", "채용직무", "근무지", "채용형태"):
        val = _extract_section(text, field)
        if not val and field in _INLINE_PATTERNS:
            val = _extract_inline(text, field)
        result[field] = val[:500] if val else "확인 불가"
    return result


if __name__ == "__main__":
    print("📊 [분석봇] 구글 시트 연결 중...")
    sheet_main, sheet_raw = connect_sheets()

    # ── 원문 시트 → {링크: 직무설명} 딕셔너리 구축 ──────────────
    print("  원문 시트 로드 중...")
    raw_rows = sheet_raw.get_all_values()
    # 원문 시트 컬럼: 검색일(0) 순위(1) 출처(2) 마감일(3) 상시(4) 회사(5)
    #                공고명(6) 직무설명(7) 박사우대(8) 링크(9)
    raw_text_by_link = {}
    for row in raw_rows[1:]:  # 헤더 제외
        if len(row) >= 10 and row[9]:
            raw_text_by_link[row[9].strip()] = row[7]  # 링크 → 직무설명
    print(f"  원문 {len(raw_text_by_link)}개 로드 완료")

    # ── 채용공고에서 분석대기 행 수집 ────────────────────────────
    print("\n🤖 [분석봇] '분석대기' 항목 처리 시작...")
    all_rows = sheet_main.get_all_values()
    pending = []
    for i, row in enumerate(all_rows):
        # 채용공고 컬럼: H(7)=지원자격 I(8)=채용직무 J(9)=근무지 K(10)=채용형태 L(11)=박사우대 M(12)=링크
        if len(row) >= 13 and row[7] == "분석대기":
            pending.append((i + 1, row))  # 1-based row number

    if not pending:
        print("✨ 처리할 항목이 없습니다.")
    else:
        tasks = pending if BATCH_SIZE is None else pending[:BATCH_SIZE]
        print(f"🚦 총 {len(pending)}개 분석 시작...")

        cells = []
        for row_num, row_data in tasks:
            link = row_data[12].strip()  # M열 링크
            company = row_data[5]
            raw_text = raw_text_by_link.get(link, "")

            if not raw_text:
                print(f"  ⚠ [{company}] 원문 없음 (행 {row_num})")
                cells.append(gspread.Cell(row_num, 8, "원문 없음"))
                continue

            fields = extract_fields(raw_text)
            print(f"  ✓ [{company}] 필드 추출 완료 (행 {row_num})")

            # H(8):지원자격, I(9):채용직무, J(10):근무지, K(11):채용형태
            cells.append(gspread.Cell(row_num, 8,  fields["지원자격"]))
            cells.append(gspread.Cell(row_num, 9,  fields["채용직무"]))
            cells.append(gspread.Cell(row_num, 10, fields["근무지"]))
            cells.append(gspread.Cell(row_num, 11, fields["채용형태"]))

        if cells:
            sheet_main.update_cells(cells, value_input_option='USER_ENTERED')
            print(f"\n  ✓ 채용공고 시트 {len(tasks)}개 행 업데이트 완료")

    print("\n🛑 [분석봇] 완료.")
