# AutoDevOps ⚡

> Deploy any GitHub repository directly to your own AWS EC2 infrastructure on Port 80 in under 3 minutes — with zero PaaS markup, zero vendor lock-in, and full cloud ownership.

🚀 **Live Production Platform:** [https://www.autodevops.vanshgoel.tech](https://www.autodevops.vanshgoel.tech)

<img width="2367" height="1128" alt="AutoDevOps Platform Interface" src="https://github.com/user-attachments/assets/6fee7151-8c4c-484d-ac4b-26317b50e71c" />

---

## 💡 What is AutoDevOps?

Modern developers love PaaS platforms like **Render** and **Railway** for their developer experience (DX). But as projects scale, developers face:
- **Hefty compute markups** (paying 3x–5x for RAM and CPU over baseline cloud rates)
- **Vendor lock-in** (black-box container runtimes with zero access to underlying VMs)
- **Inability to use cloud credits** (inability to utilize AWS Activate credits or existing enterprise AWS accounts)
- **Complex DevOps overhead** (writing 500+ lines of Terraform, Kubernetes manifests, and IAM configurations just to deploy a side-project or startup MVP)

**AutoDevOps bridges this gap:** It gives you the **instant, 1-click developer experience of Railway/Render**, but deploys **directly into your own AWS account** on isolated EC2 virtual machines.

---

## ⚡ Core Features

- **Port 80 Direct Routing:** Every deployed application is served directly on Port 80 with automatic Security Group ingress rules. No port mapping confusion or reverse-proxy headaches.
- **Zero-Config Auto Dockerfiles:** Built-in optimized Dockerfiles for **Python** (FastAPI, Flask, Django) and **Node.js** (Express, Next.js, Nest) with automatic dependency caching, or bring your own **Custom Dockerfile**.
- **Encrypted AWS Credential Vault:** Your AWS IAM credentials are encrypted at rest using **AES-256 Fernet** symmetric encryption. Credentials are never stored in plaintext and never logged.
- **Ephemeral Secrets Injection:** Environment variables are transferred to EC2 over secure SSH/SFTP, injected directly into `docker run --env-file`, and immediately shredded from disk (`shred -u`). Never stored in any database.
- **Strict Multi-Tenant Isolation:** Powered by Bcrypt password hashing and signed JWT authentication. Users can only monitor, manage, and terminate their own virtual machines (IDOR protected).
- **GitHub Git-Push Auto-Deploy Webhooks:** Attach an auto-generated webhook URL to your GitHub repository to trigger zero-downtime redeployments automatically on every `git push`.
- **Live Resource Telemetry:** Real-time CPU, RAM, and Network I/O metrics with live SVG sparklines and EC2 status checks directly in your private dashboard.

---

## 🏗️ Architecture Overview

```
                      ┌───────────────────────────────────────┐
                      │            AutoDevOps Web             │
                      │       (FastAPI + Static UI)           │
                      └──────────────────┬────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
          [Task Delegation]                           [Multi-Tenant Auth]
                   │                                           │
                   ▼                                           ▼
      ┌─────────────────────────┐                 ┌─────────────────────────┐
      │  Celery / Local Worker  │                 │    SQLite3 (WAL Mode)   │
      │  + Redis Message Broker │                 │   AES-256 Fernet Vault  │
      └────────────┬────────────┘                 └─────────────────────────┘
                   │
                   ▼ (Boto3 API)
      ┌─────────────────────────────────────────────────────────┐
      │                   User's AWS Account                    │
      │                                                         │
      │  1. Allocate EC2 (t3.micro, Ubuntu, gp3 EBS)            │
      │  2. Generate KeyPair & Security Group (Port 22 + 80)    │
      │  3. Bootstrap Docker & Git runtime via SSH/Paramiko     │
      │  4. Clone Repository & Build Dockerfile (Auto / Custom) │
      │  5. Inject & Shred ENV variables                        │
      │  6. Launch Container: Live on http://<Public-IP>:80    │
      └─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart & Local Setup

### 1. Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Redis (for Celery background worker)

### 2. Environment Configuration
```bash
cp .env.example .env
```
Fill in the configuration variables:
```env
REDIS_URL=redis://localhost:6379/0
AWS_REGION=us-east-1
JWT_SECRET_KEY=your-secure-jwt-secret-key-here
CREDENTIAL_ENCRYPTION_KEY=your-fernet-key-or-leave-blank-to-derive
```

### 3. Run with Docker Compose
```bash
docker compose up --build
```
Access the application at `http://localhost:5000`.

### 4. Or Run Locally with Python & Uvicorn
```bash
# Install dependencies
pip install -r requirements.txt

# Start backend server
cd backend
uvicorn main:app --reload --port 8000
```
Open `http://localhost:8000` in your browser.

---

## 🧪 Testing & Code Quality

Run the comprehensive security, encryption, and API integration test suite:

```bash
# Run pytest test suite
pytest

# Run flake8 linter
flake8 .
```

---

## 🛡️ Security Highlights

1. **Defense-in-Depth Input Validation:** Strict regex enforcement on GitHub repository URLs prevents remote command injection vectors.
2. **Encrypted Vault at Rest:** AWS IAM keys are protected by AES-256 Fernet encryption with deterministic key derivation fallbacks.
3. **No Persistent Secrets:** App runtime secrets (`.env`) are transmitted ephemerally to the target VM and wiped with `shred -u`.
4. **Anti-IDOR Authorization:** Every instance deletion and metric query rigorously validates user ownership before taking action.

---

## 📜 License

MIT License &copy; 2026 Vansh Goel. Ship without friction.
