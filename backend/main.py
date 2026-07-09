from pathlib import Path
from typing import Optional

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cleanup import delete_instance
from models import get_apps, init_db, update_status
from tasks import deploy_app
from worker import celery_app


app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

init_db()
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class DeployRequest(BaseModel):
    repo_url: str
    aws_key: str
    aws_secret: str
    backend_port: Optional[int] = None
    frontend_port: Optional[int] = None
    backend_dockerfile: Optional[str] = None
    frontend_dockerfile: Optional[str] = None


class DeleteRequest(BaseModel):
    aws_key: Optional[str] = None
    aws_secret: Optional[str] = None

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/dashboard")
def dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")

@app.post("/deploy")
def deploy(payload: DeployRequest):
    backend_df = (payload.backend_dockerfile or "").strip()
    frontend_df = (payload.frontend_dockerfile or "").strip()

    if not backend_df and not frontend_df:
        raise HTTPException(status_code=400, detail="Provide at least one Dockerfile")

    if backend_df and payload.backend_port is None:
        raise HTTPException(status_code=400, detail="Backend port is required when backend Dockerfile is provided")

    if frontend_df:
        if payload.frontend_port is not None and payload.frontend_port != 80:
            raise HTTPException(status_code=400, detail="Frontend port must be 80")
        frontend_port = 80
    else:
        frontend_port = None

    task = deploy_app.delay(
        payload.repo_url,
        payload.aws_key,
        payload.aws_secret,
        payload.backend_port,
        frontend_port,
        backend_df,
        frontend_df
    )
    return {"task_id": task.id}

@app.get("/status/{task_id}")
def status(task_id: str):
    res = AsyncResult(task_id, app=celery_app)
    return {
        "state": res.state,
        "result": res.result,
        "meta": res.info
    }


@app.get("/apps")
def apps():
    return {"apps": get_apps()}

@app.delete("/delete/{instance_id}")
def delete(instance_id: str, payload: Optional[DeleteRequest] = None):
    if not instance_id.startswith("i-"):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID")

    aws_key = payload.aws_key if payload else None
    aws_secret = payload.aws_secret if payload else None

    try:
        delete_instance(instance_id, aws_key=aws_key, aws_secret=aws_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")
    update_status(instance_id, "DELETED")
    return {"message": f"Instance {instance_id} deletion initiated."}