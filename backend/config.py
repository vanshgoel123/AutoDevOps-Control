import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DOCKER_USERNAME = os.getenv("DOCKER_USERNAME", "")

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY", "")
REGION = os.getenv("AWS_REGION", "us-east-1")

AMI_ID = os.getenv("AMI_ID", "ami-0ec10929233384c7f")  # Ubuntu
INSTANCE_TYPE = os.getenv("INSTANCE_TYPE", "t3.micro")
ROOT_VOLUME_SIZE_GB = int(os.getenv("ROOT_VOLUME_SIZE_GB", "30"))

# Database Configuration
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR.parent / "database" / "db.sqlite3")))

# JWT & Authentication Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "autodevops-prod-jwt-secret-key-change-in-prod-8f4b2a9c1e")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))  # 7 days

# Credential Vault Encryption Key (Fernet 32 url-safe base64-encoded bytes)
# If not explicitly set, we derive or load from a secure local master key file in database/
CREDENTIAL_ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")

# Worker Concurrency (increased to 4 for production scaling)
WORKER_CONCURRENCY = int(os.getenv("CELERY_CONCURRENCY", "4"))
