import os

SHEET_URL        = os.environ.get("SHEET_URL", "")
SHEET_TAB        = "채용공고"   # 분석 결과 시트
SHEET_TAB_RAW    = "원문"       # 직무설명 원문 시트
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
    {"name": "NVIDIA",            "priority": 2, "search_kr": "NVIDIA",           "search_en": "NVIDIA"},
    {"name": "AMD",               "priority": 2, "search_kr": "AMD",              "search_en": "AMD"},
]

# ── 공식 채용 페이지 ─────────────────────────────────────────
OFFICIAL_URLS = {
    "삼성전자":          ["https://www.samsungcareers.com/hr/",
                          "https://careers.samsung.com/"],
    "SK하이닉스":        ["https://recruit.skhynix.com/"],
    "ASML":              ["https://asmlkorea.careerlink.kr/jobs",
                          "https://www.asml.com/en/careers/find-your-job"],
    "Applied Materials": ["https://appliedkorea.applyin.co.kr/jobs/",
                          "https://jobs.appliedmaterials.com/"],
    "KLA":               ["https://kla.wd1.myworkdayjobs.com/Search?q=process+engineer+master",
                          "https://kla.wd1.myworkdayjobs.com/Search?q=process+engineer+phd"],
    "TSMC":              ["https://careers.tsmc.com/careers?q=process+engineer+master",
                          "https://careers.tsmc.com/careers?q=process+engineer+phd"],
    "Intel":             ["https://intel.wd1.myworkdayjobs.com/External?q=process+engineer+master",
                          "https://intel.wd1.myworkdayjobs.com/External?q=process+engineer+phd"],
    "Micron":            ["https://careers.micron.com/careers?q=process+engineer+master",
                          "https://careers.micron.com/careers?q=process+engineer+phd"],
    "Lam Research":      ["https://lamresearch-recruit.com/jobs",
                          "https://careers.lamresearch.com/careers?q=process+engineer+master",
                          "https://careers.lamresearch.com/careers?q=process+engineer+phd"],
    "Tokyo Electron":    ["https://tel.recruiter.co.kr/career/career",
                          "https://www.tel.com/careers/"],
    "NVIDIA":            ["https://nvidia.eightfold.ai/careers?query=process+engineer+master",
                          "https://nvidia.eightfold.ai/careers?query=process+engineer+phd"],
    "AMD":               ["https://careers.amd.com/careers-home/jobs?q=process+engineer+master",
                          "https://careers.amd.com/careers-home/jobs?q=process+engineer+phd"],
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
STRONG_KR = [
    "공정", "증착", "식각", "리소그래피", "세정", "계측", "확산", "이온주입", "산화", "cmp",
    "연구원", "엔지니어", "개발", "기술", "소재", "재료", "분석", "수율", "반도체", "석사", "신입",
]
STRONG_EN = [
    "process", "etch", "deposition", "lithograph", "cmp", "cvd", "pvd", "ald",
    "implant", "diffusion", "clean", "metrology", "oxidation", "fab",
    "engineer", "r&d", "research", "scientist", "technology", "material",
    "analysis", "yield", "device", "semiconductor",
    "master", "master's", "masters", "fresh graduate", "entry level", "new graduate",
]

EXCLUDE_KR = ["영업", "마케팅", "인사", "재무", "법무", "총무", "구매", "물류", "소프트웨어", "sw개발",
              "설치", "인턴", "인공지능", "IT", "알고리즘", "안전", "광학"]
              # IT: 대문자로 정보기술 직군 제외 (대명사 'it'와 구분)
EXCLUDE_EN = ["sales", "marketing", " hr ", "finance", "legal", "software", "procurement",
              "logistics", "supply chain", "accounting",
              "install", "intern", " ai ", " it ", "algorithm", "safe", "optic"]
              # " ai "/" it ": 공백으로 감싸 대명사·복합어 오매칭 방지

# ── 중국 지역 제외 키워드 ────────────────────────────────────
CHINA_KEYWORDS = [
    # 국가
    "중국", "china",
    # 직할시
    "beijing", "베이징",
    "shanghai", "상하이",
    "tianjin", "텐진",
    "chongqing", "충칭",
    # 주요 도시
    "shenzhen", "선전",
    "guangzhou", "광저우",
    "chengdu", "청두",
    "wuhan", "우한",
    "nanjing", "난징",
    "suzhou", "쑤저우",
    "hangzhou", "항저우",
    "xian", "xi'an", "시안",
    "dalian", "다롄",
    "qingdao", "칭다오",
    "xiamen", "샤먼",
    "zhengzhou", "정저우",
    "changsha", "창사",
    "hefei", "허페이",
    "kunming", "쿤밍",
    "shenyang", "선양",
    "harbin", "하얼빈",
    "foshan", "포산",
    "dongguan", "둥관",
    "ningbo", "닝보",
    "wuxi", "우시",
    "wenzhou", "원저우",
    "jinan", "지난",
    "zhongshan", "중산",
]

# ── 박사우대 감지 키워드 ─────────────────────────────────────
PHD_KEYWORDS = [
    "박사", "ph.d", "phd", "박사우대", "박사 우대", "doctoral",
    "doctorate", "박사학위", "박사 학위", "박사 과정",
]

# ── 공식 채용 페이지 키워드 검색 쿼리 ────────────────────────
# 각 사이트 검색창에 순서대로 입력, 쿼리별로 최대 5건 수집
KOREAN_COMPANY_NAMES = {"삼성전자", "SK하이닉스", "Tokyo Electron"}

SEARCH_QUERIES_KR = [
    "반도체 공정 석사",
    "반도체 공정 박사",
    "엔지니어 연구원 석사",
    "엔지니어 연구원 박사",
]

SEARCH_QUERIES_EN = [
    "process engineer master",
    "process engineer phd",
    "etch deposition CMP metrology master",
    "etch deposition CMP metrology phd",
    "application engineer semiconductor",
    "research engineer semiconductor",
]

# ── 실행 설정 ────────────────────────────────────────────────
MAX_WORKERS  = 4
BATCH_SIZE   = 10
MAX_TEXT_LEN = 3000
