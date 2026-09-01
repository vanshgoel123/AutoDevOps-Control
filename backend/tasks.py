import os
import tempfile
import traceback
import uuid

from worker import celery_app
from aws import create_ec2
from ssh import run_command, scp_file
from models import save_app
from cleanup import full_cleanup
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY

# ── Dockerfile templates ──────────────────────────────────────────────────────

PYTHON_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 80 2>/dev/null || gunicorn -b 0.0.0.0:80 app:app 2>/dev/null || python app.py"]
"""

NODEJS_DOCKERFILE = """\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "npm start 2>/dev/null || node index.js 2>/dev/null || node server.js"]
"""


def generate_dockerfile(app_type: str) -> str:
    """Return an auto-generated Dockerfile string for the given app_type."""
    if app_type == "nodejs":
        return NODEJS_DOCKERFILE
    return PYTHON_DOCKERFILE  # default for "python" and any unknown type


# ── Main deploy task ──────────────────────────────────────────────────────────

@celery_app.task(bind=True)
def deploy_app(self, repo_url, aws_key, aws_secret, app_type, custom_dockerfile, env_vars):
    """
    Deploy a single GitHub repo to a fresh EC2 instance on port 80.

    Parameters
    ----------
    repo_url          : Public GitHub URL to clone
    aws_key           : AWS access key (may be None → falls back to env)
    aws_secret        : AWS secret key (may be None → falls back to env)
    app_type          : "python" | "nodejs" | "custom"
    custom_dockerfile : Dockerfile content when app_type=="custom", else None
    env_vars          : Raw .env file contents (KEY=VALUE lines), or None
    """
    instance_id = None
    key_name = None
    sg_id = None
    key_path = None
    local_env_file = None   # temp file on the orchestrator

    effective_aws_key = aws_key or AWS_ACCESS_KEY
    effective_aws_secret = aws_secret or AWS_SECRET_KEY

    try:
        if not effective_aws_key or not effective_aws_secret:
            return {"error": "AWS credentials are required"}

        app_id = str(uuid.uuid4())[:6]
        print(f"[DEPLOY {app_id}] Starting — repo={repo_url} app_type={app_type}")

        # ── Choose Dockerfile ──────────────────────────────────────────────
        if app_type == "custom":
            dockerfile_content = (custom_dockerfile or "").strip()
            if not dockerfile_content:
                return {"error": "Custom Dockerfile is required for app_type='custom'"}
        else:
            dockerfile_content = generate_dockerfile(app_type)

        print(f"[DEPLOY {app_id}] Dockerfile ready ({len(dockerfile_content)} bytes)")

        # ── Write .env to local temp file (if provided) ────────────────────
        has_env = bool(env_vars and env_vars.strip())
        if has_env:
            fd, local_env_file = tempfile.mkstemp(prefix="adops_env_", suffix=".env")
            with os.fdopen(fd, "w") as f:
                f.write(env_vars.strip() + "\n")
            print(f"[DEPLOY {app_id}] .env file written locally ({local_env_file})")

        # ── Create EC2 instance ────────────────────────────────────────────
        self.update_state(state="PROGRESS", meta={"step": "Creating EC2 instance…"})
        print(f"[DEPLOY {app_id}] Launching EC2")
        ip, key_path, instance_id, key_name, sg_id = create_ec2(
            app_id,
            effective_aws_key,
            effective_aws_secret,
            backend_port=None,  # port 80 is always open
        )
        print(f"[DEPLOY {app_id}] EC2 ready | id={instance_id} ip={ip}")

        # ── Bootstrap EC2 (Docker + Git) ───────────────────────────────────
        self.update_state(state="PROGRESS", meta={"step": "Installing Docker & Git…"})
        print(f"[DEPLOY {app_id}] Installing Docker + Git")
        run_command(
            ip, key_path,
            "sudo apt-get update -y && "
            "sudo apt-get install -y docker.io git && "
            "sudo systemctl start docker && "
            "sudo systemctl enable docker && "
            "sudo usermod -aG docker ubuntu"
        )
        print(f"[DEPLOY {app_id}] Bootstrap complete")

        # ── SCP .env file to EC2 (if provided) ────────────────────────────
        if has_env and local_env_file:
            print(f"[DEPLOY {app_id}] Uploading .env to EC2")
            scp_file(ip, key_path, local_env_file, "/tmp/.adops.env")
            # Delete local temp immediately after SCP
            try:
                os.unlink(local_env_file)
            except OSError:
                pass
            local_env_file = None
            print(f"[DEPLOY {app_id}] .env uploaded; local copy deleted")

        # ── Clone + build + run ────────────────────────────────────────────
        self.update_state(state="PROGRESS", meta={"step": "Cloning repo & building image…"})
        print(f"[DEPLOY {app_id}] Building & running container")

        env_file_flag = "--env-file /tmp/.adops.env" if has_env else ""
        # Write Dockerfile to the remote, build, run, then securely delete .env
        # We use a heredoc to transfer the Dockerfile content without needing SCP.
        # The Dockerfile content is base64-encoded to survive the shell safely.
        import base64
        df_b64 = base64.b64encode(dockerfile_content.encode()).decode()

        remote_cmd = f"""
set -e
git clone {repo_url} /home/ubuntu/app
cd /home/ubuntu/app
echo "{df_b64}" | base64 -d > Dockerfile
sudo docker build -t adops_app .
sudo docker run -d -p 80:80 {env_file_flag} --restart unless-stopped adops_app
""".strip()

        if has_env:
            # Securely delete the .env from EC2 after docker run
            remote_cmd += "\nshred -u /tmp/.adops.env 2>/dev/null || rm -f /tmp/.adops.env"

        run_command(ip, key_path, remote_cmd)
        print(f"[DEPLOY {app_id}] Container started on port 80")

        # ── Save + return result ───────────────────────────────────────────
        url = f"http://{ip}"
        save_app(app_id, repo_url, url, instance_id)
        print(f"[DEPLOY {app_id}] Done — url={url}")

        return {
            "app_id": app_id,
            "url": url,
            "instance_id": instance_id,
            "app_type": app_type,
        }

    except Exception as e:
        print(f"[DEPLOY ERROR] {e}")
        traceback.print_exc()
        # Clean up local .env if something went wrong before deletion
        if local_env_file:
            try:
                os.unlink(local_env_file)
            except OSError:
                pass
        full_cleanup(instance_id, key_name, sg_id, key_path, effective_aws_key, effective_aws_secret)
        return {"error": str(e)}
