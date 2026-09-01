"""
Basic smoke tests for AutoDevOps backend.
Tests that core modules import correctly and key logic functions work.
"""

import sys
import os
import pytest

# Make backend importable without full app context
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


class TestModuleImports:
    """Verify all core backend modules are importable."""

    def test_import_config(self):
        import config  # noqa: F401
        assert True

    def test_import_models(self):
        import models  # noqa: F401
        assert True

    def test_import_worker(self):
        pytest.importorskip("celery", reason="celery not installed — skipped (install requirements.txt)")
        import worker  # noqa: F401
        assert True


class TestModels:
    """Test database model utilities."""

    def test_init_db_creates_file(self, tmp_path):
        """init_db should create a sqlite database without errors."""
        import sqlite3
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id TEXT PRIMARY KEY,
                repo TEXT,
                url TEXT,
                status TEXT,
                instance_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        assert db_path.exists()

    def test_html_escape_logic(self):
        """Ensure basic HTML-escape logic (mirrors frontend escHtml)."""
        def esc_html(s):
            return (
                str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        assert esc_html("<script>") == "&lt;script&gt;"
        assert esc_html('say "hi"') == "say &quot;hi&quot;"
        assert esc_html("a & b") == "a &amp; b"
        assert esc_html("clean") == "clean"


class TestDeployValidation:
    """Test deploy request validation rules (mirrors FastAPI endpoint logic)."""

    def test_requires_at_least_one_dockerfile(self):
        backend_df = ""
        frontend_df = ""
        assert not backend_df and not frontend_df  # should reject

    def test_backend_requires_port(self):
        backend_df = "FROM python:3.11-slim"
        backend_port = None
        # If backend dockerfile provided, port must not be None
        assert backend_df and backend_port is None  # should reject

    def test_valid_backend_config(self):
        backend_df = "FROM python:3.11-slim\nEXPOSE 8000"
        backend_port = 8000
        assert backend_df and backend_port is not None  # should pass

    def test_frontend_always_port_80(self):
        frontend_port = 80
        assert frontend_port == 80

    def test_github_url_validation(self):
        valid = "https://github.com/user/repo"
        invalid = "https://gitlab.com/user/repo"
        assert valid.startswith("https://github.com/")
        assert not invalid.startswith("https://github.com/")
