import os

SECRET_KEY = os.getenv("SECRET_KEY", "changeme-please-set-a-real-secret-key")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480
DATABASE_URL = "sqlite:////data/baumlabbackup.db"
BACKUP_TMP_DIR = "/tmp/baumlabbackup"
RCLONE_CONFIG_PATH = "/data/rclone.conf"
TZ = os.getenv("TZ", "America/New_York")
