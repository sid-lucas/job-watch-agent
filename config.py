from checks import is_german_ad, names_pattern
from pathlib import Path

# Display
MIN_SCORE = 20      # new offers below this score are not displayed
MAX_DISPLAY = 10    # maximum number of offers displayed

# Local database
DB_PATH = Path(__file__).parent / "data" / "offers.db"

# Verification
MIN_VERIFY_SCORE = 30       # only offers with at least this score are verified
MAX_VERIFY_PER_RUN = 10     # hard limit of web searches per run (Serper credits)

# Web access
USER_AGENT = "job-watch/0.1 (personal job search project)"
MAX_PAGE_CHARS = 8000   # page text is truncated to this size

# RSS source
FEED_URL = "https://swissdevjobs.ch/rss"
SOURCE_NAME = "swissdevjobs"

# Keyword filter: an offer is kept if its title or description contains at least one keyword
# Matched as whole words, case-insensitive
KEYWORDS = [
    # Security, general.
    "security", "cybersecurity", "cyber", "infosec",
    "sécurité", "cybersécurité",

    # Security operations
    "soc", "siem", "edr", "xdr", "incident response", "threat", "threat intelligence",
    "forensic", "forensics", "malware", "blue team",
    "security operations", "security analyst", "detection", "threat hunting",
    "splunk", "sentinel", "qradar", "crowdstrike",

    # Offensive security
    "pentest", "pentester", "penetration testing", "red team", "ethical hacking",
    "vulnerability", "vulnerabilities",

    # Identity and access
    "iam", "identity and access", "pam", "zero trust",

    # Governance, risk and compliance
    "grc", "nist", "risk management", "compliance", "audit",

    # Secure engineering
    "devsecops", "appsec", "application security", "cloud security", "network security",
    "cryptography",

    # AI (for the AI security angle)
    "ai", "llm", "genai", "machine learning", "artificial intelligence",
]


# Target companies, in two tiers
TOP_COMPANIES = [
    # Geneva and Swiss private banks
    "Pictet", "Lombard Odier", "UBP", "Union Bancaire Privée", "Mirabaud",
    "Edmond de Rothschild", "Bordier", "Gonet", "Syz", "Julius Baer", "Julius Bär",
    "J. Safra Sarasin", "EFG", "Vontobel", "REYL", "CBH",
    # Privacy and AI companies in Geneva
    "Proton", "Infomaniak",
]

GOOD_COMPANIES = [
    # Large and public banks
    "UBS", "BCGE", "BCV", "Banque Cantonale Vaudoise", "Zürcher Kantonalbank", "ZKB",
    "PostFinance", "Raiffeisen", "Swissquote",
    # Cantonal banks in French-speaking Switzerland
    "BCN", "Banque Cantonale Neuchâteloise", "BCF", "Banque Cantonale de Fribourg",
    "BCVs", "Banque Cantonale du Valais",
    # Financial infrastructure
    "SIX",
    # Consulting and audit
    "Deloitte", "KPMG", "PwC", "EY",
    # Security companies and SOCs
    "Kudelski", "Kudelski Security", "SCRT", "Swiss Post Cybersecurity", "Hacknowledge",
    "Orange Cyberdefense", "Navixia",
    # Public sector and international organisations
    "Swiss Post", "La Poste", "État de Genève", "Etat de Genève", "État de Vaud", "Etat de Vaud",
    "Cyber-Defence Campus", "CERN", "ICRC", "CICR", "WIPO", "OMPI", "ITU", "UIT",
    # Tech companies
    "ELCA", "Swisscom", "Nexthink", "Google", "Microsoft", "IBM",
]


# Reject rules: an offer is rejected if the rule matches
# A rule uses either a regex "pattern" or a "check" function
REJECT_RULES = [
    # Senior, management and architecture positions
    {"name": "senior title", "field": "title",
     "pattern": r"\b(senior|sr\.?|lead|principal|head of|staff|manager|director|architect|cto)\b"},

    # German ad
    {"name": "german ad", "field": "description",
     "check": is_german_ad},
]

# Score rules: points added (or removed) when the pattern matches the field
SCORE_RULES = [
    # === POSITIVE POINTS ===
    # AI related
    {"name": "ai engineer", "field": "title", "points": 30,
     "pattern": r"\b(ai|ml|machine learning|llm) engineer\b"},

    # Security related
    {"name": "security title", "field": "title", "points": 30,
     "pattern": r"\b(security|cyber|cybersecurity|cybersécurité|sécurité|soc|siem|pentest|threat|iam)\b"},

    # Entry-level position
    {"name": "entry-level", "field": "title", "points": 30,
     "pattern": r"\b(entry-level|junior|trainee|graduate)\b"},

    # Target location
    {"name": "target city", "field": "description", "points": 20,
     "pattern": r"\b(geneva|genève|lausanne|zurich|zürich|remote)\b"},

    # Target company
    {"name": "top company", "field": "company", "points": 20,
     "pattern": names_pattern(TOP_COMPANIES)},
    {"name": "good company", "field": "company", "points": 10,
     "pattern": names_pattern(GOOD_COMPANIES)},

    # === NEGATIVE POINTS ===
    # German ad
    {"name": "german mentioned", "field": "description", "points": -10,
     "pattern": r"\b(german|deutsch|allemand)\b"},

    # Internship / student position
    {"name": "internship", "field": "title", "points": -10,
     "pattern": r"\b(intern|internship|stage|stagiaire|praktikum)\b"},
]