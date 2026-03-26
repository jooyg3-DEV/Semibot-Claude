import os
import re
import time
import gspread
from concurrent.futures import ThreadPoolExecutor, as_completed

from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.common.by import By

import config

# ==========================================
# ⚙️ [설정]
# ==========================================
SHEET_URL   = config.SHEET_URL
BATCH_SIZE  = None  # None = 전체 처리
MAX_WORKERS = 3     # 병렬 처리

# ── 섹션 헤더 패턴 ────────────────────────────────────────────
# 각 필드 헤더를 라인 앞에서 감지 (re.IGNORECASE 적용)
_HEADERS = {
    "지원자격": [
        r"지원\s*자격", r"자격\s*요건", r"필수\s*요건", r"기본\s*자격",
        r"자격\s*조건", r"학력\s*요건", r"우대\s*사항",
        r"requirements?", r"qualifications?", r"must\s+have",
        r"basic\s+qualifications?", r"minimum\s+qualifications?",
        r"what\s+we.re\s+looking", r"what\s+we\s+need",
        r"who\s+you\s+are", r"about\s+you",
    ],
    "채용직무": [
        r"담당\s*업무", r"주요\s*업무", r"직무\s*내용", r"업무\s*내용",
        r"이런\s*일을", r"하시는\s*일", r"주요\s*역할",
        r"responsibilities?", r"what\s+you.ll\s+do", r"your\s+role",
        r"job\s+description", r"duties", r"what\s+the\s+role",
        r"the\s+role", r"key\s+responsibilities?", r"your\s+responsibilities?",
    ],
    "근무지": [
        r"근무\s*지", r"근무\s*위치", r"근무\s*지역",
        r"location", r"work\s+location", r"office\s+location", r"job\s+location",
    ],
    "채용형태": [
        r"채용\s*형태", r"고용\s*형태", r"근무\s*형태",
        r"employment\s+type", r"job\s+type", r"work\s+type",
        r"position\s+type",
    ],
}


def _extract_fields(text):
    """
    원문 텍스트에서 지원자격/채용직무/근무지/채용형태를 규칙 기반으로 추출.
    영문·한국어 모두 처리. 못 찾으면 빈 문자열 반환.
    """
    result = {"지원자격": "", "채용직무": "", "근무지": "", "채용형태": ""}
    lines = text.split('\n')

    # ── 1. 근무지: 인라인 패턴 우선 (Location: Seoul) ──────────
    loc_pat = re.compile(
        r'(?:근무\s*지|근무\s*위치|location|work\s+location|site)\s*[:\-]\s*(.{2,80})',
        re.IGNORECASE)
    m = loc_pat.search(text)
    if m:
        val = m.group(1).strip().split('\n')[0].rstrip(',').strip()
        if 2 < len(val) < 100:
            result["근무지"] = val

    # ── 2. 채용형태: 인라인 패턴 우선, 없으면 키워드 감지 ──────
    type_pat = re.compile(
        r'(?:채용\s*형태|고용\s*형태|employment\s+type|job\s+type|position\s+type)\s*[:\-]\s*(.{2,60})',
        re.IGNORECASE)
    m = type_pat.search(text)
    if m:
        val = m.group(1).strip().split('\n')[0].strip()
        if len(val) < 60:
            result["채용형태"] = val
    else:
        t_lo = text.lower()
        if any(k in t_lo for k in ["정규직", "permanent", "full-time", "full time"]):
            result["채용형태"] = "정규직 (Full-time)"
        elif any(k in t_lo for k in ["계약직", "contract position", "fixed-term", "fixed term"]):
            result["채용형태"] = "계약직 (Contract)"
        elif "part-time" in t_lo or "part time" in t_lo:
            result["채용형태"] = "파트타임 (Part-time)"

    # ── 3. 섹션 추출: 지원자격·채용직무 ───────────────────────
    # 모든 헤더의 등장 위치를 순서대로 수집
    all_header_pats = {
        field: re.compile(r'^\s*(?:' + '|'.join(pats) + r')\s*[\:\-]?\s*$',
                          re.IGNORECASE)
        for field, pats in _HEADERS.items()
    }
    # 헤더 뒤에 콘텐츠가 같은 라인에 붙는 경우 처리
    all_header_inline_pats = {
        field: re.compile(r'^\s*(?:' + '|'.join(pats) + r')\s*[\:\-]\s*(.+)',
                          re.IGNORECASE)
        for field, pats in _HEADERS.items()
    }
    # 섹션 경계를 나타내는 모든 헤더 통합 패턴 (내용 종료 판단용)
    any_header_pat = re.compile(
        r'^\s*(?:' + '|'.join(p for pats in _HEADERS.values() for p in pats) + r')\s*[\:\-]?',
        re.IGNORECASE)

    section_starts = []  # (line_idx, field)
    for i, line in enumerate(lines):
        for field, pat in all_header_pats.items():
            if pat.match(line):
                section_starts.append((i, field))
                break
        else:
            # 인라인 헤더: "Requirements: PhD or MS..."
            for field, pat in all_header_inline_pats.items():
                m = pat.match(line)
                if m:
                    section_starts.append((i, field))
                    break

    section_starts.sort(key=lambda x: x[0])

    for idx, (line_idx, field) in enumerate(section_starts):
        if field not in ("지원자격", "채용직무"):
            continue
        if result[field]:  # 이미 채워졌으면 skip
            continue

        # 다음 섹션 헤더까지가 이 섹션의 범위
        next_start = (section_starts[idx + 1][0]
                      if idx + 1 < len(section_starts) else len(lines))
        end = min(next_start, line_idx + 40)  # 최대 40줄

        content = []
        # 헤더 라인 자체에 인라인 내용이 있으면 추가
        m = all_header_inline_pats[field].match(lines[line_idx])
        if m:
            inline = m.group(1).strip()
            if inline:
                content.append(inline)

        for li in range(line_idx + 1, end):
            stripped = lines[li].strip()
            if not stripped:
                continue
            # 다른 섹션 헤더가 나오면 중단
            if any_header_pat.match(stripped):
                break
            content.append(stripped)

        combined = '\n'.join(content).strip()
        if combined:
            result[field] = combined[:800]

    # ── 4. 못 찾은 필드 fallback ────────────────────────────────
    # 지원자격: 학위 요구사항 문장이 있으면 첫 단락 사용
    if not result["지원자격"]:
        degree_pat = re.compile(
            r'.{0,40}(?:ph\.?d|박사|석사|master.s?|bachelor.s?|학사|degree).{0,200}',
            re.IGNORECASE)
        m = degree_pat.search(text)
        if m:
            result["지원자격"] = m.group(0).strip()[:400]

    return result


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
    """페이지 원문 수집 후 규칙 기반으로 4개 필드 추출."""
    row_num, row_data = task
    company_name = row_data[5]   # F열: 회사
    job_link     = row_data[13]  # N열: 링크
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

    t_lo = text.lower()
    has_phd = any(kw in t_lo for kw in config.PHD_KEYWORDS)

    fields = _extract_fields(text)
    print(f"      [완료] {company_name} | 근무지:{bool(fields['근무지'])} "
          f"채용형태:{bool(fields['채용형태'])} "
          f"지원자격:{bool(fields['지원자격'])} "
          f"채용직무:{bool(fields['채용직무'])}")

    return row_num, {
        "지원자격": fields["지원자격"] or "원문참조",
        "채용직무": fields["채용직무"] or "원문참조",
        "근무지":   fields["근무지"]   or "원문참조",
        "채용형태": fields["채용형태"] or "원문참조",
        "직무설명": text[:5000],
        "박사우대": "있음" if has_phd else "없음",
    }, None


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
            futures = {executor.submit(process_single_job, task): task
                       for task in tasks_to_process}
            for future in as_completed(futures):
                row_num, data, error = future.result()
                results[row_num] = (data, error)

        print("\n📝 처리 결과를 시트에 일괄 업데이트 중...")
        all_cells = []
        # H(8):지원자격, I(9):채용직무, J(10):근무지, K(11):채용형태, L(12):직무설명, M(13):박사우대
        for row_num, (data, error) in results.items():
            if data:
                values = [
                    data["지원자격"],
                    data["채용직무"],
                    data["근무지"],
                    data["채용형태"],
                    data["직무설명"],
                    data["박사우대"],
                ]
            else:
                values = [error or "오류", "", "", "", "", ""]
            for col_offset, value in enumerate(values):
                all_cells.append(gspread.Cell(row_num, 8 + col_offset, value))

        if all_cells:
            sheet.update_cells(all_cells, value_input_option='USER_ENTERED')
            print(f"  ✓ {len(results)}개 행 업데이트 완료")

    print("\n🛑 [수집봇] 안전하게 종료되었습니다.")
