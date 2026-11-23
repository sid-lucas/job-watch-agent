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