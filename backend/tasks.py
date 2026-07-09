from worker import celery_app
from aws import create_ec2
from ssh import run_command
from models import save_app
from cleanup import full_cleanup
import traceback
import uuid
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY

@celery_app.task(bind=True)
def deploy_app(self, repo_url, aws_key, aws_secret, b_port, f_port, b_df, f_df):
    instance_id = None
    key_name = None
    sg_id = None
    key_path = None
    effective_aws_key = aws_key or AWS_ACCESS_KEY
    effective_aws_secret = aws_secret or AWS_SECRET_KEY

    try:
        if not effective_aws_key or not effective_aws_secret:
            return {"error": "AWS credentials are required"}

        app_id = str(uuid.uuid4())[:6]
        print(f"[DEPLOY {app_id}] Deployment started")
        print(f"[DEPLOY {app_id}] Repo: {repo_url}")

        b_df = (b_df or "").strip()
        f_df = (f_df or "").strip()
        print(f"[DEPLOY {app_id}] Backend requested: {bool(b_df)} | Frontend requested: {bool(f_df)}")

        if not b_df and not f_df:
            print(f"[DEPLOY {app_id}] Error: no Dockerfile provided")
            return {"error": "Please provide at least one Dockerfile"}

        backend_port_for_sg = int(b_port) if b_df and b_port else None
        print(f"[DEPLOY {app_id}] Backend port for SG: {backend_port_for_sg}")

        # create ec2
        self.update_state(state="PROGRESS", meta={"step": "Creating EC2"})
        print(f"[DEPLOY {app_id}] Creating EC2 instance")
        ip, key_path, instance_id, key_name, sg_id = create_ec2(
            app_id,
            effective_aws_key,
            effective_aws_secret,
            backend_port=backend_port_for_sg,
        )
        print(f"[DEPLOY {app_id}] EC2 ready | instance_id={instance_id} | ip={ip} | sg_id={sg_id}")
        
        # Setup EC2 
        print(f"[DEPLOY {app_id}] Installing Docker and Git on EC2")
        run_command(ip, key_path, "sudo apt update -y && sudo apt install -y docker.io git && sudo systemctl start docker && sudo systemctl enable docker && sudo usermod -aG docker ubuntu")
        print(f"[DEPLOY {app_id}] EC2 setup complete")
        
        # Deploy app
        self.update_state(state="PROGRESS", meta={"step": "Cloning repo and setting up"})
        cmd = f"set -e\ngit clone {repo_url} app\ncd app\n"
        
        if b_df:
            print(f"[DEPLOY {app_id}] Building backend on port {b_port}")
            cmd += f"cat > Dockerfile.backend << 'ENDFILE'\n{b_df}\nENDFILE\n"
            cmd += f"if [ -d Backend ]; then sudo docker build -t backend Backend -f Dockerfile.backend && sudo docker run -d -p {b_port}:{b_port} backend; else sudo docker build -t backend . -f Dockerfile.backend && sudo docker run -d -p {b_port}:{b_port} backend; fi\n"
        
        if f_df:
            print(f"[DEPLOY {app_id}] Building frontend on port 80")
            cmd += f"cat > Dockerfile.frontend << 'ENDFILE'\n{f_df}\nENDFILE\n"
            cmd += f"if [ -d Frontend ]; then sudo docker build -t frontend Frontend -f Dockerfile.frontend && sudo docker run -d -p 80:80 frontend; else sudo docker build -t frontend . -f Dockerfile.frontend && sudo docker run -d -p 80:80 frontend; fi\n"

        self.update_state(state="PROGRESS", meta={"step": "Deploying app"})
        print(f"[DEPLOY {app_id}] Running remote deployment commands")
        run_command(ip, key_path, cmd)
        print(f"[DEPLOY {app_id}] Remote deployment completed")

        backend_url = f"http://{ip}:{b_port}" if b_df and b_port else None
        frontend_url = f"http://{ip}:80" if f_df else None
        url = frontend_url or backend_url or f"http://{ip}"
        print(f"[DEPLOY {app_id}] URLs | backend={backend_url} | frontend={frontend_url}")
        
        # Save to DB
        save_app(app_id, repo_url, url, instance_id)
        print(f"[DEPLOY {app_id}] Saved in DB and finished successfully")
        return {
            "app_id": app_id,
            "url": url,
            "backend_url": backend_url,
            "frontend_url": frontend_url,
            "instance_id": instance_id,
        }
    
    except Exception as e:
        print(f"[DEPLOY ERROR] {e}")
        traceback.print_exc()
        full_cleanup(instance_id, key_name, sg_id, key_path, effective_aws_key, effective_aws_secret)
        return {"error": str(e)}
        
        