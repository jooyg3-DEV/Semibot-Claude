import os

SHEET_URL        = os.environ.get("SHEET_URL", "")
SHEET_TAB        = "채용공고"
CREDENTIALS_FILE = "credentials.json"

# ── 회사 목록 ────────────────────────────────────────────────
COMPANIES = [
    {"name": "삼성전자",          "priority": 1, "search_kr": "삼성전자",          "search_en": "Samsung Electronics"},
    {"name": "SK하이닉스",        "priority": 1, "search_kr": "SK하이닉스",        "search_en": "SK Hynix"},
    {"name": "ASML",              "priority": 1, "search_kr": "ASML",             "search_en": "ASML"},
    {"name": "Applied Materials", "priority": 1, "search_kr": "어플라이드머티리얼즈","search_en": "Applied Materials"},
    {"name": "KLA",               "priority": 1, "search_kr": "KLA",              "search_en": "KLA"},
    {"name": "TSMC",              "priority": 2, "search_kr": "TSMC",             "search_en": "TSMC"},
    {"name": "Intel",             "priority": 2, "search_kr": "인텔",             "search_en": "Intel"},
    {"name": "Micron",            "priority": 2, "search_kr": "마이크론",          "search_en": "Micron Technology"},
    {"name": "Lam Research",      "priority": 2, "search_kr": "램리서치",          "search_en": "Lam Research"},
    {"name": "Tokyo Electron",    "priority": 2, "search_kr": "TEL",              "search_en": "Tokyo Electron"},
]

# ── 공식 채용 페이지 ─────────────────────────────────────────
OFFICIAL_URLS = {
    "삼성전자":          ["https://www.samsungcareers.com/"],
    "SK하이닉스":        ["https://recruit.skhynix.com/"],
    "ASML":              ["https://asmlkorea.careerlink.kr/jobs",
                          "https://www.asml.com/en/careers/find-your-job"],
    "Applied Materials": ["https://appliedkorea.applyin.co.kr/jobs/",
                          "https://jobs.appliedmaterials.com/"],
    "KLA":               ["https://kla.wd1.myworkdayjobs.com/Search"],
    "TSMC":              ["https://www.tsmc.com/english/careers/"],
    "Intel":             ["https://intel.wd1.myworkdayjobs.com/External"],
    "Micron":            ["https://careers.micron.com/careers"],
    "Lam Research":      ["https://lamresearch-recruit.com/jobs",
                          "https://careers.lamresearch.com/careers"],
    "Tokyo Electron":    ["https://tel.recruiter.co.kr/career/career",
                          "https://www.tel.com/careers/"],
}

# ── 시트 컬럼 인덱스 (0-based) ───────────────────────────────
# A: 수집일 / B: 상태 / C: 출처 / D: 우선순위 / E: 회사명 / F: 공고명
# G: 근무지 / H: 지원자격 / I: 매칭강도 / J: 박사우대 / K: 원문 / L: 링크
COL_수집일   = 0
COL_상태     = 1
COL_출처     = 2
COL_우선순위 = 3
COL_회사명   = 4
COL_공고명   = 5
COL_근무지   = 6
COL_지원자격 = 7
COL_매칭강도 = 8
COL_박사우대 = 9
COL_원문     = 10
COL_링크     = 11
NUM_COLS     = 12

STATUS_PENDING = "상세대기"
STATUS_DONE    = "수집완료"
STATUS_ERROR   = "오류"

# ── 직무 필터 키워드 ─────────────────────────────────────────
STRONG_KR = ["공정", "증착", "식각", "리소그래피", "세정", "계측", "확산", "이온주입", "산화", "cmp"]
STRONG_EN = ["process", "etch", "deposition", "lithograph", "cmp", "cvd", "pvd", "ald",
             "implant", "diffusion", "clean", "metrology", "oxidation", "fab"]

WEAK_KR = ["연구원", "엔지니어", "개발", "기술", "소재", "재료", "분석", "통합", "수율", "반도체"]
WEAK_EN = ["engineer", "r&d", "research", "scientist", "technology", "material",
           "analysis", "yield", "integration", "device", "semiconductor"]

EXCLUDE_KR = ["영업", "마케팅", "인사", "재무", "법무", "총무", "구매", "물류", "소프트웨어", "sw개발"]
EXCLUDE_EN = ["sales", "marketing", " hr ", "finance", "legal", "software", "procurement",
              "logistics", "supply chain", "accounting"]

# ── 중국 지역 제외 키워드 ────────────────────────────────────
CHINA_KEYWORDS = [
    "중국", "china", "beijing", "shanghai", "shenzhen", "guangzhou",
    "chengdu", "wuhan", "nanjing", "suzhou", "hangzhou",
    "베이징", "상하이", "선전", "광저우", "청두", "시안", "xian",
]

# ── 박사우대 감지 키워드 ─────────────────────────────────────
PHD_KEYWORDS = [
    "박사", "ph.d", "phd", "박사우대", "박사 우대", "doctoral",
    "doctorate", "박사학위", "박사 학위", "박사 과정",
]

# ── 실행 설정 ────────────────────────────────────────────────
MAX_WORKERS  = 4
BATCH_SIZE   = 10
MAX_TEXT_LEN = 3000
