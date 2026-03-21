import os

SECRET_KEY = os.getenv("SECRET_KEY", "changeme-please-set-a-real-secret-key").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin").strip()
ADMIN_RESET = os.getenv("ADMIN_RESET", "false").strip().lower() == "true"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480
DATABASE_URL = "sqlite:////data/baumlabbackup.db"
BACKUP_TMP_DIR = "/tmp/baumlabbackup"
RCLONE_CONFIG_PATH = "/data/rclone.conf"
TZ = os.getenv("TZ", "America/New_York")

# ── Authentik SSO (OIDC) ───────────────────────────────────────────────────────
OIDC_ENABLED       = os.getenv("OIDC_ENABLED", "false").strip().lower() == "true"
OIDC_ISSUER        = os.getenv("OIDC_ISSUER", "").rstrip("/") + "/"
OIDC_CLIENT_ID     = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
OIDC_REDIRECT_URI  = os.getenv("OIDC_REDIRECT_URI", "").strip()
