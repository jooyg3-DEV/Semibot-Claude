import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium.webdriver.common.by import By

import config
import utils


def process_job(task):
    row_num, row = task
    company = row[config.COL_회사명]
    link    = row[config.COL_링크]
    print(f"  ▶ [{company}] 원문 수집 중... (행: {row_num})")

    driver = utils.make_driver()
    try:
        driver.get(link)
        time.sleep(3)
        body_text = driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception as e:
        print(f"      [오류] 접속 실패: {e}")
        return row_num, None, None
    finally:
        driver.quit()

    if not body_text or len(body_text) < 30:
        return row_num, None, None

    phd_flag = "✓" if utils.has_phd(body_text) else "-"
    truncated = body_text[:config.MAX_TEXT_LEN]
    print(f"      [완료] {company} | 박사우대: {phd_flag} | {len(body_text)}자")
    return row_num, truncated, phd_flag


if __name__ == "__main__":
    print("📊 구글 시트 연결 중...")
    sheet = utils.connect_sheet()
    all_rows = sheet.get_all_values()

    pending = [
        (i + 1, row)
        for i, row in enumerate(all_rows)
        if len(row) > config.COL_상태 and row[config.COL_상태] == config.STATUS_PENDING
    ]

    if not pending:
        print("✨ 처리할 항목 없음")
    else:
        batch = pending[:config.BATCH_SIZE]
        print(f"🚦 대기 {len(pending)}개 중 {len(batch)}개를 {config.MAX_WORKERS}개 병렬 처리...")

        results = {}
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
            futures = {ex.submit(process_job, task): task for task in batch}
            for future in as_completed(futures):
                row_num, text, phd = future.result()
                results[row_num] = (text, phd)

        print("\n📝 시트 업데이트 중...")
        # Range B:K = 10 cells (indices 0~9)
        # B(0)=상태 / H(6)=지원자격 / J(8)=박사우대 / K(9)=원문
        cells = []
        for row_num, (text, phd) in results.items():
            row_cells = sheet.range(f"B{row_num}:K{row_num}")
            if text:
                row_cells[0].value = config.STATUS_DONE  # B: 상태
                row_cells[6].value = "원문 참조"          # H: 지원자격
                row_cells[8].value = phd                 # J: 박사우대
                row_cells[9].value = text                # K: 원문
            else:
                row_cells[0].value = config.STATUS_ERROR # B: 상태
            cells.extend(row_cells)

        if cells:
            sheet.update_cells(cells)
            success = sum(1 for t, _ in results.values() if t)
            print(f"  ✓ {success}/{len(results)}개 업데이트 완료")

    print("\n🛑 요약봇 완료")
