import sqlite3
import uuid
from typing import Optional, List, Dict, Any
from config import DB_PATH
import crypto


def get_db_connection() -> sqlite3.Connection:
    """Return an active SQLite connection configured with WAL and foreign keys."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initialize database tables with schema migrations for user multi-tenancy."""
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")

    # 2. User credentials vault table (Encrypted at rest with Fernet AES-256)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            encrypted_aws_key TEXT NOT NULL,
            encrypted_aws_secret TEXT NOT NULL,
            masked_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Apps table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            repo TEXT,
            url TEXT,
            status TEXT,
            instance_id TEXT,
            app_type TEXT DEFAULT 'python',
            custom_dockerfile TEXT,
            encrypted_ssh_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration check: Ensure user_id column exists if table was previously created without it
    cur.execute("PRAGMA table_info(apps);")
    existing_columns = [col["name"] for col in cur.fetchall()]

    if "user_id" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN user_id TEXT DEFAULT 'system';")
    if "app_type" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN app_type TEXT DEFAULT 'python';")
    if "custom_dockerfile" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN custom_dockerfile TEXT;")
    if "encrypted_ssh_key" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN encrypted_ssh_key TEXT;")
    if "created_at" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
    if "updated_at" not in existing_columns:
        cur.execute("ALTER TABLE apps ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_apps_id_unique ON apps(id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_apps_user_id ON apps(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_apps_instance_id ON apps(instance_id);")

    conn.commit()
    conn.close()


# ── User Operations ────────────────────────────────────────────────────────────

def create_user(email: str, password_hash: str) -> Dict[str, Any]:
    """Create a new user with a unique ID."""
    user_id = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
        (user_id, email.lower().strip(), password_hash)
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "email": email.lower().strip()}


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve user record including password hash by email."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
        (email.lower().strip(),)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve safe user profile (without password hash) by ID."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, created_at FROM users WHERE id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


# ── Credential Vault Operations (AES-256 Fernet Encrypted) ────────────────────

def save_user_credentials(user_id: str, aws_key: str, aws_secret: str) -> Dict[str, Any]:
    """
    Encrypt AWS credentials using AES-256 Fernet and save to user_credentials table.
    Returns masked key preview.
    """
    enc_key = crypto.encrypt_secret(aws_key.strip())
    enc_secret = crypto.encrypt_secret(aws_secret.strip())
    masked = crypto.mask_access_key(aws_key.strip())

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_credentials (user_id, encrypted_aws_key, encrypted_aws_secret, masked_key, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            encrypted_aws_key = excluded.encrypted_aws_key,
            encrypted_aws_secret = excluded.encrypted_aws_secret,
            masked_key = excluded.masked_key,
            updated_at = CURRENT_TIMESTAMP
    """, (user_id, enc_key, enc_secret, masked))
    conn.commit()
    conn.close()
    return {"configured": True, "masked_key": masked}


def get_user_credentials(user_id: str) -> Optional[Dict[str, str]]:
    """
    Retrieve and decrypt AWS credentials for internal task execution.
    Never exposed directly in API responses.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT encrypted_aws_key, encrypted_aws_secret, masked_key FROM user_credentials WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    try:
        dec_key = crypto.decrypt_secret(row["encrypted_aws_key"])
        dec_secret = crypto.decrypt_secret(row["encrypted_aws_secret"])
        return {
            "aws_key": dec_key,
            "aws_secret": dec_secret,
            "masked_key": row["masked_key"]
        }
    except Exception:
        return None


def get_user_credentials_status(user_id: str) -> Dict[str, Any]:
    """Return safe credentials status (whether configured and masked key) for UI."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT masked_key, updated_at FROM user_credentials WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    if row and row["masked_key"]:
        return {
            "configured": True,
            "masked_key": row["masked_key"],
            "updated_at": row["updated_at"]
        }
    return {"configured": False, "masked_key": None, "updated_at": None}


def delete_user_credentials(user_id: str) -> bool:
    """Delete saved AWS credentials for user."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_credentials WHERE user_id = ?", (user_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ── App Management Operations (Multi-Tenant Scoped) ───────────────────────────

def save_app(
    app_id: str,
    repo: str,
    url: str,
    instance_id: str,
    user_id: str = "system",
    status: str = "RUNNING",
    app_type: str = "python",
    custom_dockerfile: Optional[str] = None,
    ssh_key: Optional[str] = None
):
    """Save newly provisioned app linked to user_id, optionally encrypting SSH key."""
    enc_ssh_key = crypto.encrypt_secret(ssh_key.strip()) if ssh_key and ssh_key.strip() else None

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO apps (id, user_id, repo, url, status, instance_id, app_type, custom_dockerfile, encrypted_ssh_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            repo = excluded.repo,
            url = excluded.url,
            status = excluded.status,
            instance_id = excluded.instance_id,
            app_type = excluded.app_type,
            custom_dockerfile = excluded.custom_dockerfile,
            encrypted_ssh_key = COALESCE(excluded.encrypted_ssh_key, apps.encrypted_ssh_key),
            updated_at = CURRENT_TIMESTAMP
        """,
        (app_id, user_id, repo, url, status, instance_id, app_type, custom_dockerfile, enc_ssh_key)
    )
    conn.commit()
    conn.close()


def get_app_ssh_key(app_id: str, user_id: str) -> Optional[str]:
    """Retrieve and decrypt the SSH private key for an app owned by user_id."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT encrypted_ssh_key FROM apps WHERE id = ? AND user_id = ?",
        (app_id, user_id)
    )
    row = cur.fetchone()
    conn.close()

    if not row or not row["encrypted_ssh_key"]:
        return None

    try:
        return crypto.decrypt_secret(row["encrypted_ssh_key"])
    except Exception:
        return None


def get_apps_by_user(user_id: str) -> List[List[Any]]:
    """
    Retrieve apps belonging strictly to the specified user_id.
    Returns in list-of-tuples format matching frontend expectations:
    [ [app_id, repo, url, status, instance_id, created_at, app_type], ... ]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, repo, url, status, instance_id, created_at, app_type
        FROM apps
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    conn.close()

    return [
        [
            row["id"],
            row["repo"],
            row["url"],
            row["status"],
            row["instance_id"],
            row["created_at"],
            row["app_type"] if "app_type" in row.keys() and row["app_type"] else "python"
        ]
        for row in rows
    ]


def get_app_by_id(app_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve app details by app_id."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM apps WHERE id = ?", (app_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_app_by_instance(instance_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch app by instance_id, optionally validating ownership by user_id."""
    conn = get_db_connection()
    cur = conn.cursor()
    if user_id:
        cur.execute(
            "SELECT * FROM apps WHERE instance_id = ? AND user_id = ?",
            (instance_id, user_id)
        )
    else:
        cur.execute("SELECT * FROM apps WHERE instance_id = ?", (instance_id,))

    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def update_status(instance_id: str, status: str, user_id: Optional[str] = None):
    """Update status of an instance, optionally validating user ownership."""
    conn = get_db_connection()
    cur = conn.cursor()
    if user_id:
        cur.execute(
            "UPDATE apps SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE instance_id = ? AND user_id = ?",
            (status, instance_id, user_id)
        )
    else:
        cur.execute(
            "UPDATE apps SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE instance_id = ?",
            (status, instance_id)
        )
    conn.commit()
    conn.close()


# Legacy helper for backward compatibility
def get_apps():
    """Legacy helper returning all apps (deprecated in favor of get_apps_by_user)."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, repo, url, status, instance_id FROM apps ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [[r["id"], r["repo"], r["url"], r["status"], r["instance_id"]] for r in rows]
