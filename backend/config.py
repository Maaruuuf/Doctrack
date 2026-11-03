"""Central configuration — every value can be overridden with an environment variable."""
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-key-change-me-in-production-0123456789")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/records.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt"}

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@12345")

# Alerts
ALERT_HOUR = int(os.getenv("ALERT_HOUR", "8"))  # daily scan time (server local time)
CRITICAL_DAYS = int(os.getenv("CRITICAL_DAYS", "7"))
DISABLE_SCHEDULER = os.getenv("DISABLE_SCHEDULER", "0") == "1"

# Optional e-mail digest (leave SMTP_HOST empty to disable)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "doctrack@example.com")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
