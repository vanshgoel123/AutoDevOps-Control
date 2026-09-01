/* ─────────────────────────────────────────────────────────────────
   AutoDevOps — script.js
   Full Overhaul Implementation:
   - Single-service, Port-80 deployment model
   - Runtime selector: Python | Node.js | Custom
   - Live Dockerfile template preview & custom Dockerfile support
   - Secure Environment Variables (.env) injection
   - Real-time deployment polling & log terminal
   - Transient credentials handling & download helper
   - Theme toggle (Dark / Light) with persistence
───────────────────────────────────────────────────────────────── */

"use strict";

// ── Dockerfile Templates ───────────────────────────────────────────
const TEMPLATES = {
  python:
`FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 80 2>/dev/null || gunicorn -b 0.0.0.0:80 app:app 2>/dev/null || python app.py"]`,

  nodejs:
`FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
EXPOSE 80
ENV PORT=80
CMD ["sh", "-c", "npm start 2>/dev/null || node index.js 2>/dev/null || node server.js"]`,
};

// ── State ──────────────────────────────────────────────────────────
let _currentAppType   = "python";
let _deployInProgress = false;
let _pollInterval     = null;
let _lastTaskId       = null;

// ── Runtime Selection ──────────────────────────────────────────────
function selectAppType(type) {
  _currentAppType = type;

  // Update pills active state
  ["python", "nodejs", "custom"].forEach(t => {
    const pill = document.getElementById("pill_" + t);
    if (pill) {
      if (t === type) pill.classList.add("active");
      else pill.classList.remove("active");
    }
  });

  const autoWrap   = document.getElementById("auto_dockerfile_wrap");
  const customWrap = document.getElementById("custom_dockerfile_wrap");
  const codeEl     = document.getElementById("df_preview_code");

  if (type === "custom") {
    if (autoWrap)   autoWrap.style.display   = "none";
    if (customWrap) customWrap.style.display = "block";
  } else {
    if (autoWrap)   autoWrap.style.display   = "block";
    if (customWrap) customWrap.style.display = "none";
    if (codeEl)     codeEl.textContent       = TEMPLATES[type] || "";
  }
}

// ── Theme Helpers ──────────────────────────────────────────────────
function initTheme() {
  const saved     = localStorage.getItem("adops-theme");
  const preferred = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  const theme     = saved || preferred;
  document.documentElement.setAttribute("data-theme", theme);
  _updateThemeIcon(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next    = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("adops-theme", next);
  _updateThemeIcon(next);
}

function _updateThemeIcon(theme) {
  const btn = document.getElementById("theme_toggle_btn");
  if (btn) btn.textContent = theme === "light" ? "🌙" : "☀️";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f5f6fa" : "#0b0d0f");
}

// ── Collapsible Section Toggle ─────────────────────────────────────
function toggleSection(name) {
  const content = document.getElementById("section-" + name);
  const toggle  = document.getElementById("toggle-" + name);
  if (!content) return;

  const isOpen = content.classList.contains("open");
  content.classList.toggle("open", !isOpen);
  if (toggle) toggle.classList.toggle("open", !isOpen);
}

// ── Toast Notifications ────────────────────────────────────────────
function showToast(msg, type = "info") {
  const container = document.getElementById("toast_container");
  if (!container) return;
  const icons = { success: "✅", error: "❌", info: "💬" };
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = `<span>${icons[type] || "💬"}</span><span>${msg}</span>`;
  container.appendChild(t);
  setTimeout(() => {
    t.classList.add("fadeout");
    setTimeout(() => t.remove(), 300);
  }, 3500);
}

// ── Status Bar ─────────────────────────────────────────────────────
function setStatus(text, state = "") {
  const bar  = document.getElementById("status_bar");
  const span = document.getElementById("status_text");
  if (!bar || !span) return;

  bar.className = "status-bar" + (state ? " " + state : "");
  span.textContent = text;
}

// ── Log Terminal ───────────────────────────────────────────────────
function showTerminal() {
  const t = document.getElementById("log_terminal");
  if (t) t.classList.add("visible");
}

function hideTerminal() {
  const t = document.getElementById("log_terminal");
  if (t) t.classList.remove("visible");
}

function clearLog() {
  const b = document.getElementById("log_body");
  if (b) b.innerHTML = "";
}

function appendLog(text, type = "") {
  const body = document.getElementById("log_body");
  if (!body) return;

  const line = document.createElement("div");
  line.className = "log-line";
  line.innerHTML = `<span class="log-line-prefix">$</span><span class="log-line-text ${type}">${escHtml(text)}</span>`;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

function appendLogCursor() {
  const body = document.getElementById("log_body");
  if (!body) return;
  const line = document.createElement("div");
  line.className = "log-line";
  line.id = "log_cursor_line";
  line.innerHTML = `<span class="log-line-prefix">$</span><span class="log-line-text log-line-cursor"></span>`;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

function removeLogCursor() {
  const el = document.getElementById("log_cursor_line");
  if (el) el.remove();
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Deploy Button State ────────────────────────────────────────────
function setDeployButtonState(loading) {
  const btn = document.getElementById("deploy_btn");
  if (!btn) return;
  btn.disabled = loading;
  if (loading) btn.classList.add("btn-loading");
  else btn.classList.remove("btn-loading");

  const textEl = btn.querySelector(".btn-text");
  if (textEl) textEl.textContent = loading ? "Deploying on EC2…" : "⚡ Deploy App (Port 80)";
}

// ── Result Card ────────────────────────────────────────────────────
function showResultCard(html) {
  const card = document.getElementById("result_card");
  const body = document.getElementById("result_body");
  if (!card || !body) return;
  body.innerHTML = html;
  card.classList.add("visible");
}

function hideResultCard() {
  const card = document.getElementById("result_card");
  if (card) card.classList.remove("visible");
}

// ── Session Credentials ────────────────────────────────────────────
function storeCredentials(key, secret) {
  try {
    sessionStorage.setItem("_adops_key",    key);
    sessionStorage.setItem("_adops_secret", secret);
    localStorage.setItem("aws_key",         key);
    localStorage.setItem("aws_secret",      secret);
  } catch (_) {}
}

function getStoredCredentials() {
  return {
    key:    sessionStorage.getItem("_adops_key")    || localStorage.getItem("aws_key")    || "",
    secret: sessionStorage.getItem("_adops_secret") || localStorage.getItem("aws_secret") || "",
  };
}

function downloadCredentials() {
  const keyInput    = document.getElementById("aws_key");
  const secretInput = document.getElementById("aws_secret");

  const key    = (keyInput    ? keyInput.value.trim()    : "") || getStoredCredentials().key;
  const secret = (secretInput ? secretInput.value.trim() : "") || getStoredCredentials().secret;

  if (!key || !secret) {
    showToast("No credentials to save.", "error");
    return;
  }

  const content = [
    "# AutoDevOps AWS credentials",
    "# Keep this file private — never commit it to git.",
    `AWS_ACCESS_KEY_ID=${key}`,
    `AWS_SECRET_ACCESS_KEY=${secret}`,
    "",
  ].join("\n");

  const blob = new Blob([content], { type: "text/plain" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "aws_credentials.env";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  showToast("Saved aws_credentials.env", "success");
}

// ── Deploy Submission ──────────────────────────────────────────────
async function deploy() {
  if (_deployInProgress) {
    showToast("Deployment already in progress.", "info");
    return;
  }

  const repo        = (document.getElementById("repo")?.value || "").trim();
  const awsKey      = (document.getElementById("aws_key")?.value || "").trim();
  const awsSecret   = (document.getElementById("aws_secret")?.value || "").trim();
  const customDf    = (document.getElementById("custom_dockerfile")?.value || "").trim();
  const envVars     = (document.getElementById("env_vars")?.value || "").trim();

  // ── Validation ───────────────────────────────────────────────────
  if (!repo) {
    setStatus("Enter a GitHub repository URL.", "error");
    showToast("GitHub URL is required.", "error");
    document.getElementById("repo")?.focus();
    return;
  }

  if (!repo.startsWith("https://github.com/")) {
    setStatus("Only public GitHub repositories are supported.", "error");
    showToast("URL must start with https://github.com/", "error");
    document.getElementById("repo")?.focus();
    return;
  }

  if (!awsKey || !awsSecret) {
    setStatus("AWS credentials are required.", "error");
    showToast("Enter your AWS Access Key and Secret Key.", "error");
    document.getElementById("aws_key")?.focus();
    return;
  }

  if (_currentAppType === "custom" && !customDf) {
    setStatus("Custom Dockerfile content is required.", "error");
    showToast("Paste your custom Dockerfile.", "error");
    document.getElementById("custom_dockerfile")?.focus();
    return;
  }

  // ── Save credentials for current session ─────────────────────────
  storeCredentials(awsKey, awsSecret);

  // ── Start UI state ───────────────────────────────────────────────
  _deployInProgress = true;
  setDeployButtonState(true);
  hideResultCard();
  clearLog();
  showTerminal();
  setStatus("Queuing deployment…", "active");

  appendLog("Validating request…", "info");
  appendLog(`Repository: ${repo}`);
  appendLog(`Runtime: ${_currentAppType.toUpperCase()} (Port 80)`);
  if (envVars) {
    const lineCount = envVars.split("\n").filter(l => l.trim() && !l.startsWith("#")).length;
    appendLog(`ENV Variables: ${lineCount} variable(s) attached (will be shredded on boot)`, "info");
  }
  appendLog("Submitting task to worker…", "info");
  appendLogCursor();

  try {
    const res = await fetch("/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_url:          repo,
        aws_key:           awsKey,
        aws_secret:        awsSecret,
        app_type:          _currentAppType,
        custom_dockerfile: _currentAppType === "custom" ? customDf : null,
        env_vars:          envVars || null,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "Server rejected the deploy request.");
    }

    if (!data.task_id) {
      throw new Error("No task ID returned from server.");
    }

    _lastTaskId = data.task_id;
    removeLogCursor();
    appendLog(`Task queued successfully (ID: ${data.task_id})`, "success");
    appendLog("Waiting for worker…", "info");
    appendLogCursor();
    setStatus("Worker provisioning EC2…", "active");

    startPolling(data.task_id);

  } catch (err) {
    removeLogCursor();
    appendLog("Error: " + (err.message || "Unknown error"), "error");
    setStatus(err.message || "Deployment failed.", "error");
    showToast(err.message || "Deployment failed.", "error");
    _deployInProgress = false;
    setDeployButtonState(false);
  }
}

// ── Real-time Status Polling ───────────────────────────────────────
function startPolling(taskId) {
  if (_pollInterval) clearInterval(_pollInterval);

  let attempts = 0;
  const MAX_ATTEMPTS = 180; // ~6 minutes at 2s interval

  _pollInterval = setInterval(async () => {
    attempts++;

    if (attempts > MAX_ATTEMPTS) {
      clearInterval(_pollInterval);
      removeLogCursor();
      appendLog("Timeout: Deployment is taking longer than expected. Check the dashboard.", "error");
      setStatus("Timed out. Check dashboard for live status.", "error");
      showToast("Deployment timed out after 6 minutes.", "error");
      _deployInProgress = false;
      setDeployButtonState(false);
      return;
    }

    try {
      const res = await fetch("/status/" + taskId);
      if (!res.ok) return;

      const data  = await res.json();
      const state = data.state || "";
      const meta  = data.meta  || {};

      if (meta.step) {
        removeLogCursor();
        appendLog(meta.step, "info");
        appendLogCursor();
        setStatus(meta.step, "active");
      }

      if (state === "PENDING") {
        setStatus("Waiting for worker to pick up task…", "active");
      }

      if (state === "PROGRESS" || state === "STARTED") {
        setStatus(meta.step || "Deploying on AWS infrastructure…", "active");
      }

      if (state === "SUCCESS") {
        clearInterval(_pollInterval);
        _deployInProgress = false;
        setDeployButtonState(false);
        removeLogCursor();

        const result = data.result || {};

        if (result.error) {
          appendLog("Deployment failed: " + result.error, "error");
          setStatus("Failed: " + result.error, "error");
          showToast("Deployment failed: " + result.error, "error");
          return;
        }

        appendLog("Deployment complete! Container is live on port 80 🎉", "success");
        setStatus("Deployment successful!", "success");
        showToast("App deployed successfully!", "success");

        const liveUrl = result.url || (result.app_id ? `http://${result.url}` : "");

        let cardHtml = "";
        if (result.app_id) {
          cardHtml += `<div class="result-meta"><span style="color:var(--ink-2);">App ID</span> <code>${escHtml(result.app_id)}</code></div>`;
        }
        if (result.instance_id) {
          cardHtml += `<div class="result-meta"><span style="color:var(--ink-2);">EC2 Instance</span> <code>${escHtml(result.instance_id)}</code></div>`;
        }
        if (result.app_type) {
          cardHtml += `<div class="result-meta"><span style="color:var(--ink-2);">Runtime</span> <span class="badge badge-purple">${escHtml(result.app_type.toUpperCase())}</span></div>`;
        }

        if (liveUrl) {
          appendLog("Live App URL: " + liveUrl, "success");
          cardHtml += `
            <div class="result-link-row" style="margin-top:14px;">
              <span class="result-link-label">Live App (Port 80)</span>
              <a class="result-link-url" href="${liveUrl}" target="_blank" rel="noopener noreferrer">${escHtml(liveUrl)}</a>
            </div>`;
        } else {
          cardHtml += `<div class="result-meta" style="color:var(--ink-3);margin-top:10px;">Check the Dashboard to see your live instance.</div>`;
        }

        showResultCard(cardHtml);
      }

      if (state === "FAILURE") {
        clearInterval(_pollInterval);
        _deployInProgress = false;
        setDeployButtonState(false);
        removeLogCursor();
        appendLog("Worker process terminated with failure.", "error");
        setStatus("Deployment failed — worker error.", "error");
        showToast("Deployment failed on worker.", "error");
      }

    } catch (_) {
      // transient network hiccup
    }
  }, 2000);
}

// ── Load Example Helper ────────────────────────────────────────────
function fillExample() {
  const repoEl   = document.getElementById("repo");
  const keyEl    = document.getElementById("aws_key");
  const secretEl = document.getElementById("aws_secret");
  const envEl    = document.getElementById("env_vars");

  if (repoEl   && !repoEl.value)   repoEl.value   = "https://github.com/tiangolo/fastapi";
  if (keyEl    && !keyEl.value)    keyEl.value    = "AKIAIOSFODNN7EXAMPLE";
  if (secretEl && !secretEl.value) secretEl.value = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";

  selectAppType("python");

  if (envEl && !envEl.value) {
    envEl.value = "PORT=80\nDEBUG=False\nENVIRONMENT=production";
    const sec = document.getElementById("section-env");
    const tog = document.getElementById("toggle-env");
    if (sec && !sec.classList.contains("open")) {
      sec.classList.add("open");
      if (tog) tog.classList.add("open");
    }
  }

  showToast("Example Python app loaded.", "info");
}

// ── Clear Form ─────────────────────────────────────────────────────
function clearForm() {
  ["repo", "aws_key", "aws_secret", "custom_dockerfile", "env_vars"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  selectAppType("python");
  setStatus("Ready when you are", "");
  hideResultCard();
  hideTerminal();
  clearLog();

  if (_pollInterval) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
  _deployInProgress = false;
  setDeployButtonState(false);

  showToast("Form cleared.", "info");
}

// ── Initial Setup on Page Load ─────────────────────────────────────
function bootApp() {
  initTheme();
  selectAppType("python");

  // Restore stored session credentials if available
  const { key, secret } = getStoredCredentials();
  const keyEl    = document.getElementById("aws_key");
  const secretEl = document.getElementById("aws_secret");
  if (keyEl    && key    && !keyEl.value)    keyEl.value    = key;
  if (secretEl && secret && !secretEl.value) secretEl.value = secret;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootApp);
} else {
  bootApp();
}
