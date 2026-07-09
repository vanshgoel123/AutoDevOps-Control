# AutoDevOps Control

This phase lets you deploy a Dockerized GitHub repository to EC2 from a FastAPI dashboard.

## What it does

- Accepts a public GitHub repo URL
- Accepts backend and/or frontend Dockerfiles pasted into the form
- Creates EC2, security group, and key pair automatically
- Clones the repo, builds the Docker image(s), and starts the container(s)
- Shows deployment progress and active apps in the dashboard

## Local run

1. Copy the environment template:

   `cp .env.example .env`

2. Fill in your AWS credentials and region values.

3. Start the stack:

   `docker compose up --build`

4. Open the app:

   - Home: `https://deploy.13-207-132-171.sslip.io:8000`
   - Dashboard: `https://deploy.13-207-132-171.sslip.io:8000/dashboard`

## Frontend usage

- Paste a public GitHub repository URL.
- Paste at least one Dockerfile.
- If you provide a backend Dockerfile, set the backend port.
- Frontend deployments always use port `80`.

## Environment variables

- `REDIS_URL`
- `AWS_ACCESS_KEY`
- `AWS_SECRET_KEY`
- `AWS_REGION`
- `AMI_ID`
- `INSTANCE_TYPE`
- `ROOT_VOLUME_SIZE_GB`
- `DOCKER_USERNAME`

## Notes

- The app stores deployment records in `database/db.sqlite3`.
- Use the dashboard to terminate old EC2 instances after testing.
- Rotate any credentials that were previously hardcoded before using this in production.