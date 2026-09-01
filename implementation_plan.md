# AutoDevOps — Full Overhaul Plan

## What We're Building

Complete redesign to support a much simpler, cleaner deploy model:

1. **Single-repo, single-service** — one GitHub URL → one deployment on port 80
2. **No Dockerfile needed** — user picks Python or Node.js; we auto-generate the Dockerfile
3. **Custom Dockerfile mode** — advanced users can still paste their own
4. **ENV variables** — user pastes `KEY=VALUE` lines; we SCP a `.env` to the server, use it, then securely delete it
5. **Port 80 always** — no more "port required" badge, no service split

---

## Scope: What This System Can Do

| Feature | Supported |
|---|---|
| Single GitHub public repo | ✅ |
| Python apps (FastAPI, Flask, Django…) | ✅ |
| Node.js apps (Express, Next.js…) | ✅ |
| User-provided custom Dockerfile | ✅ |
| ENV variables — copied then deleted | ✅ |
| Everything on port 80 | ✅ |
| Frontend + Backend split | ❌ Removed |
| Multiple services per deploy | ❌ Not in scope |
| HTTPS / SSL | ❌ Not in scope |

---

## Key Design Decisions

> [!IMPORTANT]
> **Single-service model**: One repo = one Docker container on port 80. No more backend/frontend split. Simpler UX, fewer bugs.

> [!IMPORTANT]
> **ENV security flow**: Vars written to local temp file → SCP'd to EC2 `/tmp/.env` → used by `docker run --env-file` → `shred -u` deleted. Never stored in DB.

> [!IMPORTANT]
> **Auto Dockerfile**: Python and Node.js templates auto-generated. CMD tries multiple entry points (uvicorn → gunicorn → python app.py for Python; npm start → node index.js for Node).

---

## Proposed Changes

### Backend

#### [MODIFY] [main.py](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/backend/main.py)
- New `DeployRequest`: `repo_url`, `aws_key`, `aws_secret`, `app_type` (python/nodejs/custom), `custom_dockerfile` (optional), `env_vars` (optional)
- Remove all port fields, frontend/backend split
- Validation: custom type requires `custom_dockerfile`

#### [MODIFY] [tasks.py](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/backend/tasks.py)
- `generate_dockerfile(app_type)` → returns Dockerfile string
- SCP `.env` to EC2, use `--env-file /tmp/.env`, then `shred -u /tmp/.env`
- All containers: `-p 80:80`
- Remove backend/frontend split logic

#### [MODIFY] [ssh.py](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/backend/ssh.py)
- Add `scp_file(ip, key_path, local_path, remote_path)` via paramiko SFTP

---

### Frontend

#### [MODIFY] [index.html](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/frontend/index.html)
- Remove backend/frontend split + all port inputs
- New **App Type** selector: Python pill | Node.js pill | Custom pill
- Live Dockerfile preview (read-only) for Python/Node.js
- **ENV Variables** section with collapsible textarea (`KEY=VALUE` format)
- Updated "How it works" steps

#### [MODIFY] [script.js](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/frontend/script.js)
- New `deploy()` for single-service model
- Live preview generation per language selection
- ENV vars sent as `env_vars` field
- Remove all port logic

#### [MODIFY] [style.css](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/frontend/style.css)
- Language selector pill buttons with animated active state
- Glassmorphism card polish
- ENV vars section styling
- Overall premium visual upgrade

#### [MODIFY] [dashboard.html](file:///home/vansh/Desktop/Project_Railway/project/phase7-everythingfromuser/frontend/dashboard.html)
- Better empty states, glow card effects

---

## Auto-Generated Dockerfiles

**Python:**
```
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 80 2>/dev/null || gunicorn -b 0.0.0.0:80 app:app 2>/dev/null || python app.py"]
```

**Node.js:**
```
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "npm start 2>/dev/null || node index.js 2>/dev/null || node server.js"]
```

---

## ENV Variable Security Flow

1. User pastes `KEY=VALUE` lines in UI
2. Sent as `env_vars` string in POST body
3. Backend writes to temp local file
4. SCP'd to EC2 `/tmp/.env`
5. `docker run -d -p 80:80 --env-file /tmp/.env app`
6. `shred -u /tmp/.env || rm -f /tmp/.env` on EC2
7. Temp file on orchestrator deleted
8. `env_vars` never written to DB

---

## Verification Plan

- Deploy Python FastAPI repo → verify port 80 response
- Deploy Node.js Express repo → verify port 80
- Test ENV vars available inside container
- Verify `.env` deleted after deploy
- Dashboard shows app, terminate works
