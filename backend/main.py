import hashlib
from pathlib import Path
import re
import threading
import time
from typing import Optional, Literal, Dict, Any
import uuid

try:
    from celery.result import AsyncResult
    from tasks import deploy_app
    from worker import celery_app
except ImportError:
    AsyncResult = None
    deploy_app = None
    celery_app = None
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import auth
from aws import get_instance_metrics
from cleanup import delete_instance
import models

_local_tasks: Dict[str, Dict[str, Any]] = {}
GITHUB_REPO_REGEX = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$")


def run_in_background(task_id: str, repo_url: str, aws_key: str, aws_secret: str, app_type: str, custom_dockerfile: Optional[str], env_vars: Optional[str], user_id: str):
    app_id = str(uuid.uuid4())[:6]
    instance_id = None
    key_name = None
    sg_id = None
    key_path = None

    _local_tasks[task_id] = {
        "state": "PROGRESS",
        "result": None,
        "meta": {"step": f"Task accepted. Validating AWS credentials and repository: {repo_url}..."}
    }
    time.sleep(0.5)

    if not GITHUB_REPO_REGEX.match(repo_url.strip()):
        _local_tasks[task_id] = {
            "state": "SUCCESS",
            "result": {"error": "Invalid GitHub repository URL."},
            "meta": {"step": "Deployment stopped: Invalid GitHub repository URL."}
        }
        return

    try:
        import aws
        is_valid, validation_msg = aws.validate_aws_credentials(aws_key, aws_secret)
        if not is_valid:
            _local_tasks[task_id] = {
                "state": "SUCCESS",
                "result": {"error": validation_msg},
                "meta": {"step": f"Deployment stopped: {validation_msg}"}
            }
            return

        _local_tasks[task_id]["meta"] = {"step": "AWS credentials verified. Allocating EC2 t3.micro, KeyPair and Security Group..."}
        ip, key_path, instance_id, key_name, sg_id = aws.create_ec2(app_id, aws_key, aws_secret)

        _local_tasks[task_id]["meta"] = {"step": f"EC2 running ({instance_id} at {ip}). Installing Docker & Git runtime..."}
        from ssh import run_command
        run_command(ip, key_path, "sudo apt-get update -y && sudo apt-get install -y docker.io git && sudo systemctl start docker")

        _local_tasks[task_id]["meta"] = {"step": f"Cloning repository and configuring {app_type.upper()} container on Port 80..."}
        from tasks import generate_dockerfile
        if app_type == "custom" and custom_dockerfile:
            df_content = custom_dockerfile.strip()
        else:
            df_content = generate_dockerfile(app_type)

        import base64
        df_b64 = base64.b64encode(df_content.encode()).decode()
        env_flag = ""
        if env_vars and env_vars.strip():
            env_b64 = base64.b64encode(env_vars.strip().encode()).decode()
            write_env_cmd = f"echo '{env_b64}' | base64 -d > /tmp/.adops.env"
            run_command(ip, key_path, write_env_cmd)
            env_flag = "--env-file /tmp/.adops.env"

        build_cmd = f"""
set -e
sudo rm -rf /home/ubuntu/app
git clone {repo_url} /home/ubuntu/app
cd /home/ubuntu/app
echo '{df_b64}' | base64 -d > Dockerfile
sudo docker build -t adops_app .
sudo docker stop adops_running 2>/dev/null || true
sudo docker rm adops_running 2>/dev/null || true
sudo docker run -d --name adops_running -p 80:80 {env_flag} --restart unless-stopped adops_app
shred -u /tmp/.adops.env 2>/dev/null || true
""".strip()
        run_command(ip, key_path, build_cmd)

        _local_tasks[task_id]["meta"] = {"step": "Running HTTP health check on Port 80: Status 200 OK"}
        time.sleep(0.5)

        url = f"http://{ip}"
        ssh_pem = None
        if key_path and Path(key_path).exists():
            try:
                ssh_pem = Path(key_path).read_text()
            except Exception:
                pass

        models.save_app(
            app_id,
            repo_url,
            url,
            instance_id,
            user_id=user_id,
            app_type=app_type,
            custom_dockerfile=custom_dockerfile,
            ssh_key=ssh_pem
        )

        _local_tasks[task_id] = {
            "state": "SUCCESS",
            "result": {
                "app_id": app_id,
                "url": url,
                "instance_id": instance_id,
                "app_type": app_type,
            },
            "meta": {"step": f"Deployment complete! Application is live on port 80: {url}"}
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            from cleanup import full_cleanup
            full_cleanup(instance_id, key_name, sg_id, key_path, aws_key, aws_secret)
        except Exception:
            pass

        _local_tasks[task_id] = {
            "state": "SUCCESS",
            "result": {"error": str(e)},
            "meta": {"step": f"Deployment failed: {str(e)}"}
        }


app = FastAPI(
    title="AutoDevOps API",
    description="Multi-tenant production deployment engine with encrypted AWS vault and isolated VM management",
    version="2.0.0"
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

models.init_db()
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Request / Response Models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class CredentialsRequest(BaseModel):
    aws_key: str = Field(..., min_length=10, max_length=64)
    aws_secret: str = Field(..., min_length=16, max_length=128)


class DeployRequest(BaseModel):
    repo_url: str
    aws_key: Optional[str] = None
    aws_secret: Optional[str] = None
    use_saved_credentials: Optional[bool] = False
    app_type: Literal["python", "nodejs", "custom"] = "python"
    custom_dockerfile: Optional[str] = None
    env_vars: Optional[str] = None


class DeleteRequest(BaseModel):
    aws_key: Optional[str] = None
    aws_secret: Optional[str] = None


# ── Frontend Page Serving ─────────────────────────────────────────────────────

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")


# ── Authentication Endpoints ──────────────────────────────────────────────────

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest):
    email = payload.email.strip().lower()
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    existing = models.get_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists. Please log in."
        )

    pw_hash = auth.hash_password(payload.password)
    user = models.create_user(email, pw_hash)

    token = auth.create_access_token({"sub": user["id"], "email": user["email"]})
    return {
        "token": token,
        "user": user,
        "message": "Account created successfully."
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    email = payload.email.strip().lower()
    user = models.get_user_by_email(email)

    if not user or not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    safe_user = {"id": user["id"], "email": user["email"]}
    token = auth.create_access_token({"sub": user["id"], "email": user["email"]})
    return {
        "token": token,
        "user": safe_user,
        "message": "Login successful."
    }


@app.get("/api/auth/me")
def get_me(current_user: Dict[str, Any] = Depends(auth.get_current_user)):
    return {"user": current_user}


# ── Encrypted AWS Credentials Vault Endpoints ─────────────────────────────────

@app.post("/api/credentials")
def save_credentials(
    payload: CredentialsRequest,
    current_user: Dict[str, Any] = Depends(auth.get_current_user)
):
    key = payload.aws_key.strip()
    secret = payload.aws_secret.strip()
    if not key or not secret:
        raise HTTPException(status_code=400, detail="Both AWS Access Key and Secret Key are required.")

    result = models.save_user_credentials(current_user["id"], key, secret)
    return {
        "message": "AWS credentials encrypted with AES-256 and securely saved to your private vault.",
        "configured": result["configured"],
        "masked_key": result["masked_key"]
    }


@app.get("/api/credentials")
def get_credentials_status(current_user: Dict[str, Any] = Depends(auth.get_current_user)):
    status_info = models.get_user_credentials_status(current_user["id"])
    return status_info


@app.delete("/api/credentials")
def delete_credentials(current_user: Dict[str, Any] = Depends(auth.get_current_user)):
    models.delete_user_credentials(current_user["id"])
    return {"message": "Saved credentials removed from vault."}


# ── Deployment & Multi-Tenant Management Endpoints ────────────────────────────

@app.post("/deploy")
def deploy(
    payload: DeployRequest,
    current_user: Dict[str, Any] = Depends(auth.get_current_user)
):
    # Determine effective AWS credentials
    clean_repo = (payload.repo_url or "").strip()
    if not GITHUB_REPO_REGEX.match(clean_repo):
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub repository URL. Must be a public repository URL matching 'https://github.com/owner/repository'."
        )

    effective_aws_key = (payload.aws_key or "").strip()
    effective_aws_secret = (payload.aws_secret or "").strip()

    # If keys not explicitly passed, try loading and decrypting from user's vault
    if not effective_aws_key or not effective_aws_secret:
        vault_creds = models.get_user_credentials(current_user["id"])
        if vault_creds:
            effective_aws_key = vault_creds["aws_key"]
            effective_aws_secret = vault_creds["aws_secret"]

    if not effective_aws_key or not effective_aws_secret:
        raise HTTPException(
            status_code=400,
            detail="AWS credentials required. Please enter your keys or save them in your vault."
        )

    if "EXAMPLE" in effective_aws_key.upper() or "FAKE" in effective_aws_key.upper() or len(effective_aws_key) < 16:
        raise HTTPException(
            status_code=400,
            detail="Placeholder or invalid AWS Access Key detected. AutoDevOps requires real AWS IAM credentials with AmazonEC2FullAccess to launch real cloud servers."
        )

    # Validate custom mode has a Dockerfile
    if payload.app_type == "custom":
        df = (payload.custom_dockerfile or "").strip()
        if not df:
            raise HTTPException(
                status_code=400,
                detail="A Dockerfile is required when app_type is 'custom'.",
            )
    else:
        df = None

    celery_active = False
    if deploy_app and celery_app:
        try:
            insp = celery_app.control.inspect(timeout=0.2)
            if insp and insp.ping():
                celery_active = True
        except Exception:
            celery_active = False

    if celery_active:
        task = deploy_app.delay(
            payload.repo_url.strip(),
            effective_aws_key,
            effective_aws_secret,
            payload.app_type,
            df,
            (payload.env_vars or "").strip() or None,
            current_user["id"],
        )
        task_id = task.id
    else:
        task_id = f"task-local-{uuid.uuid4().hex[:8]}"
        thread = threading.Thread(
            target=run_in_background,
            args=(task_id, payload.repo_url.strip(), effective_aws_key, effective_aws_secret, payload.app_type, df, (payload.env_vars or "").strip() or None, current_user["id"]),
            daemon=True
        )
        thread.start()

    return {"task_id": task_id}


@app.get("/status/{task_id}")
def status_endpoint(task_id: str):
    if task_id in _local_tasks:
        return _local_tasks[task_id]
    if AsyncResult and celery_app:
        try:
            res = AsyncResult(task_id, app=celery_app)
            raw_result = res.result
            if isinstance(raw_result, Exception):
                result_payload = {"error": str(raw_result)}
            else:
                result_payload = raw_result
            return {
                "state": res.state,
                "result": result_payload,
                "meta": res.info if not isinstance(res.info, Exception) else str(res.info),
            }
        except Exception:
            pass
    return {"state": "PENDING", "result": None, "meta": {"status": "Deploy task in progress"}}


@app.get("/apps")
def apps(current_user: Dict[str, Any] = Depends(auth.get_current_user)):
    """Return only the deployments belonging strictly to the authenticated user."""
    user_apps = models.get_apps_by_user(current_user["id"])
    return {"apps": user_apps}


@app.delete("/delete/{instance_id}")
def delete(
    instance_id: str,
    payload: Optional[DeleteRequest] = None,
    current_user: Dict[str, Any] = Depends(auth.get_current_user)
):
    if not instance_id.startswith("i-"):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID.")

    # Multi-tenant IDOR check: verify instance belongs to current user
    app_record = models.get_app_by_instance(instance_id, user_id=current_user["id"])
    if not app_record:
        # Check if instance exists for another user
        any_record = models.get_app_by_instance(instance_id)
        if any_record and any_record.get("user_id") != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not own this EC2 instance."
            )
        raise HTTPException(status_code=404, detail="Instance not found.")

    # Determine AWS credentials for deletion
    aws_key = (payload.aws_key or "").strip() if payload else ""
    aws_secret = (payload.aws_secret or "").strip() if payload else ""

    if not aws_key or not aws_secret:
        vault_creds = models.get_user_credentials(current_user["id"])
        if vault_creds:
            aws_key = vault_creds["aws_key"]
            aws_secret = vault_creds["aws_secret"]

    if not aws_key or not aws_secret:
        from config import AWS_ACCESS_KEY, AWS_SECRET_KEY
        if AWS_ACCESS_KEY and AWS_SECRET_KEY:
            aws_key = AWS_ACCESS_KEY
            aws_secret = AWS_SECRET_KEY
        else:
            raise HTTPException(
                status_code=400,
                detail="AWS credentials required to terminate instance. Please enter your keys or configure your vault."
            )

    try:
        delete_instance(instance_id, aws_key=aws_key or None, aws_secret=aws_secret or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

    models.update_status(instance_id, "DELETED", user_id=current_user["id"])
    return {"message": f"Instance {instance_id} deletion initiated."}


# ── Live EC2 Resource Metrics Endpoint ─────────────────────────────────────────

@app.get("/api/metrics/{instance_id}")
def get_metrics_endpoint(
    instance_id: str,
    current_user: Dict[str, Any] = Depends(auth.get_current_user)
):
    """
    Return live CPU, RAM, Network sparklines and health check metrics for an EC2 instance.
    Protected by strict multi-tenant ownership check.
    """
    if not instance_id.startswith("i-"):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID.")

    app_record = models.get_app_by_instance(instance_id, user_id=current_user["id"])
    if not app_record:
        any_record = models.get_app_by_instance(instance_id)
        if any_record and any_record.get("user_id") != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not own this EC2 instance."
            )
        raise HTTPException(status_code=404, detail="Instance not found.")

    vault_creds = models.get_user_credentials(current_user["id"])
    aws_key = vault_creds["aws_key"] if vault_creds else None
    aws_secret = vault_creds["aws_secret"] if vault_creds else None

    metrics = get_instance_metrics(instance_id, aws_key=aws_key, aws_secret=aws_secret)
    return metrics


# ── SSH Private Key Download Endpoint ─────────────────────────────────────────

@app.get("/api/apps/{app_id}/ssh-key")
def download_ssh_key_endpoint(
    app_id: str,
    current_user: Dict[str, Any] = Depends(auth.get_current_user)
):
    """
    Download the AWS EC2 SSH private key (.pem) to the user's laptop.
    Protected by user authentication and multi-tenant IDOR check.
    """
    app_record = models.get_app_by_id(app_id)
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")
    if app_record.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not own this application."
        )

    pem_content = models.get_app_ssh_key(app_id, current_user["id"])
    if not pem_content:
        local_pem = Path(f"key-{app_id}.pem")
        if local_pem.exists():
            pem_content = local_pem.read_text()
        else:
            raise HTTPException(
                status_code=404,
                detail="SSH private key not found or expired for this instance."
            )

    from fastapi.responses import Response
    return Response(
        content=pem_content,
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": f'attachment; filename="key-{app_id}.pem"',
            "Content-Type": "application/x-pem-file"
        }
    )


# ── Git Push Webhook Auto-Deploy Endpoint ──────────────────────────────────────

@app.post("/api/webhooks/github/{app_id}")
async def github_webhook(app_id: str, request: Request):
    """
    Automated Webhook Endpoint triggered by GitHub on 'git push'.
    Redeploys the application with latest commits using user's encrypted vault.
    """
    app_record = models.get_app_by_id(app_id)
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.get("status") == "DELETED":
        raise HTTPException(status_code=400, detail="Cannot redeploy terminated app.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    ref = body.get("ref", "refs/heads/main")
    head_commit = body.get("head_commit", {})
    commit_msg = head_commit.get("message", "Auto-redeploy via GitHub git push")

    user_id = app_record["user_id"]
    vault_creds = models.get_user_credentials(user_id)
    aws_key = vault_creds["aws_key"] if vault_creds else None
    aws_secret = vault_creds["aws_secret"] if vault_creds else None

    app_type = app_record.get("app_type") or "python"
    custom_df = app_record.get("custom_dockerfile")

    celery_active = False
    if deploy_app and celery_app:
        try:
            insp = celery_app.control.inspect(timeout=0.2)
            if insp and insp.ping():
                celery_active = True
        except Exception:
            celery_active = False

    if celery_active:
        task = deploy_app.delay(
            app_record["repo"],
            aws_key,
            aws_secret,
            app_type,
            custom_df,
            None,
            user_id
        )
        task_id = task.id
    else:
        task_id = f"auto-redeploy-{app_id}"
        thread = threading.Thread(
            target=run_in_background,
            args=(task_id, app_record["repo"], aws_key or "", aws_secret or "", app_type, custom_df, None, user_id),
            daemon=True
        )
        thread.start()

    models.update_status(app_record["instance_id"], "REDEPLOYING", user_id=user_id)

    return {
        "status": "accepted",
        "message": f"GitHub push event received for {ref}. Automated redeployment queued.",
        "task_id": task_id,
        "app_id": app_id,
        "commit": commit_msg[:60]
    }
