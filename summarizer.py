import os
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import anthropic

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# ==========================================
# ⚙️ [설정]
# ==========================================
SHEET_URL = os.environ.get("SHEET_URL", "여기에_구글_스프레드시트_URL을_붙여넣으세요")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
BATCH_SIZE = 10   # 한 번에 처리할 공고 수
MAX_WORKERS = 3   # 병렬 AI 호출 수 (API 속도 제한 고려)

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None

_driver_path = None
_driver_path_lock = threading.Lock()


def get_driver_path():
    global _driver_path
    with _driver_path_lock:
        if _driver_path is None:
            _driver_path = ChromeDriverManager().install()
    return _driver_path


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    driver = webdriver.Chrome(service=Service(get_driver_path()), options=options)
    driver.set_page_load_timeout(15)
    return driver


def connect_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    return gspread.authorize(creds).open_by_url(SHEET_URL).worksheet("채용 공고 (박사)")


def get_ai_extracted_data(text_content):
    if not text_content or len(text_content) < 50 or not client:
        return None

    prompt = f"""다음 채용 공고 텍스트를 읽고, **반드시 아래의 JSON 양식으로만** 답변해 줘.

{{
  "지원자격": "원문 그대로 복사",
  "채용직무": "원문 그대로 복사",
  "근무지": "원문 그대로 복사",
  "채용형태": "원문 그대로 복사 (예: 정규직, 계약직, 인턴, Full-time, Contract 등)",
  "직무설명": "원문 그대로 복사",
  "박사우대": "원문 그대로 복사 (없으면 '해당 내용 없음')"
}}

[절대 규칙]
1. 모든 항목: 절대 요약/번역 금지. 영어면 영어 원문 100% 복사.
2. 텍스트가 채용 공고가 아니면 모든 항목에 "확인 불가" 기재.
3. JSON만 출력. 다른 텍스트 없이.

공고 내용: {text_content[:3000]}
"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("\n", 1)[0]
            return json.loads(raw_text.strip())
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"      [API 속도 제한] {wait}초 대기 중... ({attempt+1}/{max_retries})")
            time.sleep(wait)
        except Exception as e:
            print(f"      [오류] {e}")
            return None
    return None


def process_single_job(task):
    """단일 공고의 페이지 수집 + AI 요약을 독립 드라이버로 처리 (스레드 안전)"""
    row_num, row_data = task
    company_name = row_data[5]   # F열: 회사
    job_link = row_data[13]      # N열: 링크
    print(f"  ▶ [{company_name}] 상세 분석 중... (행: {row_num})")

    driver = make_driver()
    try:
        driver.get(job_link)
        time.sleep(3)
        detail_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return row_num, None, "페이지 접속 불가"
    finally:
        driver.quit()

    ai_data = get_ai_extracted_data(detail_text)
    if ai_data:
        print(f"      [성공] {company_name} 요약 완료")
        return row_num, ai_data, None
    else:
        return row_num, None, "AI 추출 실패"


if __name__ == "__main__":
    print("📊 [요약봇] 구글 시트 연결 중...")
    sheet = connect_google_sheet()

    print("🔧 ChromeDriver 준비 중...")
    get_driver_path()

    print("\n🤖 [요약봇] 시트의 빈칸(AI 대기)을 채우러 갑니다...")
    all_rows = sheet.get_all_values()
    pending_tasks = []

    for i, row in enumerate(all_rows):
        if len(row) >= 14 and row[7] == "AI 대기":  # H열(index 7): 지원자격
            pending_tasks.append((i + 1, row))

    if not pending_tasks:
        print("✨ 요약할 밀린 숙제가 없습니다! 모두 완벽하게 채워져 있습니다.")
    else:
        tasks_to_process = pending_tasks[:BATCH_SIZE]
        print(f"🚦 밀린 숙제 {len(pending_tasks)}개 중, {len(tasks_to_process)}개를 {MAX_WORKERS}개 병렬로 처리합니다.")

        results = {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_single_job, task): task for task in tasks_to_process}
            for future in as_completed(futures):
                row_num, ai_data, error = future.result()
                results[row_num] = (ai_data, error)

        print("\n📝 처리 결과를 시트에 일괄 업데이트 중...")
        all_cells_to_update = []

        for row_num, (ai_data, error) in results.items():
            if ai_data:
                # H(8):지원자격, I(9):채용직무, J(10):근무지, K(11):채용형태, L(12):직무설명, M(13):박사우대
                cell_list = sheet.range(f'H{row_num}:M{row_num}')
                cell_list[0].value = ai_data.get("지원자격", "미상")
                cell_list[1].value = ai_data.get("채용직무", "미상")
                cell_list[2].value = ai_data.get("근무지", "미상")
                cell_list[3].value = ai_data.get("채용형태", "미상")
                cell_list[4].value = ai_data.get("직무설명", "확인 불가")
                cell_list[5].value = ai_data.get("박사우대", "해당 내용 없음")
                all_cells_to_update.extend(cell_list)
            elif error:
                sheet.update_cell(row_num, 8, error)  # H열에 오류 기재

        if all_cells_to_update:
            sheet.update_cells(all_cells_to_update)
            print(f"  ✓ {len(results)}개 행 업데이트 완료")

    print("\n🛑 [요약봇] 안전하게 종료되었습니다.")
