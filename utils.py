from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver

import config


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-extensions")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(15)
    return driver


def connect_sheet():
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        config.CREDENTIALS_FILE, scope
    )
    return gspread.authorize(creds).open_by_url(config.SHEET_URL).worksheet(config.SHEET_TAB)


def is_china(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in config.CHINA_KEYWORDS)


def match_title(title: str):
    """Returns '강', '약', or None."""
    if not title:
        return None
    t = title.lower()
    if any(kw in t for kw in config.EXCLUDE_EN) or \
       any(kw in title for kw in config.EXCLUDE_KR):
        return None
    if any(kw in t for kw in config.STRONG_EN) or \
       any(kw in title for kw in config.STRONG_KR):
        return "강"
    if any(kw in t for kw in config.WEAK_EN) or \
       any(kw in title for kw in config.WEAK_KR):
        return "약"
    return None


def has_phd(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in config.PHD_KEYWORDS)


def make_row(source, priority, company, title, location, match_strength, link):
    today = datetime.today().strftime("%Y-%m-%d")
    row = [""] * config.NUM_COLS
    row[config.COL_수집일]   = today
    row[config.COL_상태]     = config.STATUS_PENDING
    row[config.COL_출처]     = source
    row[config.COL_우선순위] = f"{priority}순위"
    row[config.COL_회사명]   = company
    row[config.COL_공고명]   = title
    row[config.COL_근무지]   = location or ""
    row[config.COL_지원자격] = config.STATUS_PENDING
    row[config.COL_매칭강도] = match_strength
    row[config.COL_박사우대] = "미확인"
    row[config.COL_원문]     = ""
    row[config.COL_링크]     = link
    return row
