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
    """Initialize database tables with schema migrations for user multi-tenancy and audit tracking."""
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")

    # Migration check for users table
    cur.execute("PRAGMA table_info(users);")
    user_columns = [col["name"] for col in cur.fetchall()]
    if "is_admin" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0;")

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

    # 4. Activity & Attempts Log table (Auditing all deploy attempts, signups, logins, errors)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            user_email TEXT,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_logs(action);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id);")

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

def create_user(email: str, password_hash: str, is_admin: int = 0) -> Dict[str, Any]:
    """Create a new user with a unique ID."""
    user_id = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (id, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
        (user_id, email.lower().strip(), password_hash, is_admin)
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "email": email.lower().strip(), "is_admin": is_admin}


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve user record including password hash and admin status by email."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, is_admin, created_at FROM users WHERE email = ?",
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
        "SELECT id, email, is_admin, created_at FROM users WHERE id = ?",
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


# ── Audit & Activity Logging ──────────────────────────────────────────────────

def log_activity(
    action: str,
    status: str,
    details: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    ip_address: Optional[str] = None
):
    """Record an audit trail event (deploy attempt, signup, login, error, termination)."""
    try:
        log_id = str(uuid.uuid4())
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO activity_logs (id, user_id, user_email, action, status, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, user_id, user_email, action, status, details, ip_address)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to record activity: {e}")


# ── Admin Account Provisioning ─────────────────────────────────────────────────

def seed_admin_user(email: str = "vanshg247776@gmail.com", plain_password: str = "vansh@20012006") -> Dict[str, Any]:
    """
    Ensure the super-admin account exists with admin privileges and specified credentials.
    Called on system boot/init_db to guarantee the admin always has immediate access.
    """
    import bcrypt
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")
    clean_email = email.lower().strip()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, is_admin FROM users WHERE email = ?", (clean_email,))
    row = cur.fetchone()

    if row:
        user_id = row["id"]
        cur.execute(
            """
            UPDATE users 
            SET password_hash = ?, is_admin = 1, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
            """,
            (pw_hash, user_id)
        )
    else:
        user_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO users (id, email, password_hash, is_admin)
            VALUES (?, ?, ?, 1)
            """,
            (user_id, clean_email, pw_hash)
        )

    conn.commit()
    conn.close()

    log_activity(
        action="ADMIN_SEEDED",
        status="SUCCESS",
        details=f"Super-admin account verified/seeded for {clean_email}",
        user_id=user_id,
        user_email=clean_email
    )

    return {"id": user_id, "email": clean_email, "is_admin": 1}


# ── Admin Dashboard Analytics & Database Inspection ───────────────────────────

def get_admin_overview() -> Dict[str, Any]:
    """
    Return comprehensive platform analytics across users, deployments, vaults,
    and runtime activities.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. User stats
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    total_users = cur.fetchone()["cnt"]

    # 2. Vault stats
    cur.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM user_credentials")
    users_with_vault = cur.fetchone()["cnt"]

    # 3. App stats
    cur.execute("SELECT COUNT(*) as cnt FROM apps")
    total_apps = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM apps WHERE status = 'RUNNING'")
    running_instances = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM apps WHERE status = 'DELETED'")
    deleted_instances = cur.fetchone()["cnt"]

    # 4. App type distribution
    cur.execute("SELECT app_type, COUNT(*) as cnt FROM apps GROUP BY app_type")
    app_types_raw = cur.fetchall()
    app_types = {"python": 0, "nodejs": 0, "custom": 0}
    for row in app_types_raw:
        k = (row["app_type"] or "python").lower()
        app_types[k] = row["cnt"]

    # 5. Activity log stats
    cur.execute("SELECT COUNT(*) as cnt FROM activity_logs WHERE action LIKE 'DEPLOY%'")
    total_deploy_attempts = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM activity_logs WHERE action = 'DEPLOY_SUCCESS'")
    successful_deploys = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM activity_logs WHERE action = 'DEPLOY_FAILED'")
    failed_deploys = cur.fetchone()["cnt"]

    # 6. Database disk metrics
    db_size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    cur.execute("PRAGMA page_count;")
    page_count = cur.fetchone()[0]
    cur.execute("PRAGMA page_size;")
    page_size = cur.fetchone()[0]
    cur.execute("PRAGMA journal_mode;")
    journal_mode = cur.fetchone()[0]

    conn.close()

    return {
        "total_users": total_users,
        "users_with_vault": users_with_vault,
        "total_apps": total_apps,
        "running_instances": running_instances,
        "deleted_instances": deleted_instances,
        "app_types": app_types,
        "deploy_attempts": {
            "total": total_deploy_attempts,
            "success": successful_deploys,
            "failed": failed_deploys
        },
        "database": {
            "path": str(DB_PATH),
            "size_bytes": db_size_bytes,
            "size_formatted": f"{db_size_bytes / 1024:.1f} KB" if db_size_bytes < 1048576 else f"{db_size_bytes / (1024*1024):.2f} MB",
            "page_count": page_count,
            "page_size": page_size,
            "journal_mode": str(journal_mode).upper() if journal_mode else "WAL"
        }
    }


def get_all_users_admin() -> List[Dict[str, Any]]:
    """Return detailed list of all registered users with deployment & vault counts."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            u.id,
            u.email,
            u.is_admin,
            u.created_at,
            u.updated_at,
            CASE WHEN c.user_id IS NOT NULL THEN 1 ELSE 0 END AS has_vault,
            c.masked_key,
            (SELECT COUNT(*) FROM apps a WHERE a.user_id = u.id) AS total_apps,
            (SELECT COUNT(*) FROM apps a WHERE a.user_id = u.id AND a.status = 'RUNNING') AS running_apps
        FROM users u
        LEFT JOIN user_credentials c ON u.id = c.user_id
        ORDER BY u.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_apps_admin() -> List[Dict[str, Any]]:
    """Return all applications deployed across the entire platform."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            a.id,
            a.user_id,
            COALESCE(u.email, 'system/anonymous') AS user_email,
            a.repo,
            a.url,
            a.status,
            a.instance_id,
            a.app_type,
            a.created_at,
            a.updated_at
        FROM apps a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_activity_admin(limit: int = 200) -> List[Dict[str, Any]]:
    """Return recent activity, attempts, and audit events."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, user_email, action, status, details, ip_address, created_at
        FROM activity_logs
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_database_diagnostics() -> Dict[str, Any]:
    """Return raw table names, row counts, and schema breakdown for SQLite."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [r["name"] for r in cur.fetchall()]

    table_stats = []
    for table in tables:
        cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        count = cur.fetchone()["cnt"]
        cur.execute(f"PRAGMA table_info({table});")
        columns = [{"name": c["name"], "type": c["type"], "pk": c["pk"]} for c in cur.fetchall()]
        table_stats.append({
            "name": table,
            "row_count": count,
            "columns": columns
        })

    cur.execute("SELECT sqlite_version();")
    sqlite_ver = cur.fetchone()[0]
    conn.close()

    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "sqlite_version": sqlite_ver,
        "db_path": str(DB_PATH),
        "db_size_bytes": db_size,
        "db_size_formatted": f"{db_size / 1024:.1f} KB" if db_size < 1048576 else f"{db_size / (1024*1024):.2f} MB",
        "tables": table_stats
    }
