/* ─────────────────────────────────────────────────────────────────
   AutoDevOps — script.js
   Handles: theme toggle, deploy form, real-time status polling,
            log terminal, credential storage (session only),
            credential download, section toggles, form helpers,
            toast notifications.
───────────────────────────────────────────────────────────────── */

"use strict";

// ── State ──────────────────────────────────────────────────────────
let _deployInProgress = false;
let _pollInterval = null;
let _lastTaskId = null;

// ── Theme ──────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("adops-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  const theme = saved || preferred;
  document.documentElement.setAttribute("data-theme", theme);
  _updateThemeIcon(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("adops-theme", next);
  _updateThemeIcon(next);
}

function _updateThemeIcon(theme) {
  const btn = document.getElementById("theme_toggle_btn");
  if (btn) btn.textContent = theme === "light" ? "🌙" : "☀️";
  // Also update meta theme-color for mobile browsers
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f5f6fa" : "#0b0d0f");
}

// Run immediately on load
initTheme();

// ── Section toggles ────────────────────────────────────────────────
function toggleSection(name) {
  const content = document.getElementById("section-" + name);
  const toggle = document.getElementById("toggle-" + name);
  if (!content || !toggle) return;

  const isOpen = content.classList.contains("open");
  content.classList.toggle("open", !isOpen);
  toggle.classList.toggle("open", !isOpen);
}

// ── Toast ──────────────────────────────────────────────────────────
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

// ── Status bar helpers ─────────────────────────────────────────────
function setStatus(text, state = "") {
  const bar = document.getElementById("status_bar");
  const span = document.getElementById("status_text");
  if (!bar || !span) return;

  bar.className = "status-bar" + (state ? " " + state : "");
  span.textContent = text;
}

// ── Log terminal ───────────────────────────────────────────────────
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

// ── HTML escape ────────────────────────────────────────────────────
function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Deploy button state ────────────────────────────────────────────
function setDeployButtonState(loading) {
  const btn = document.getElementById("deploy_btn");
  if (!btn) return;
  if (loading) {
    btn.classList.add("btn-loading");
    btn.disabled = true;
  } else {
    btn.classList.remove("btn-loading");
    btn.disabled = false;
  }
  const textEl = btn.querySelector(".btn-text");
  if (textEl) textEl.textContent = loading ? "Deploying…" : "⚡ Deploy App";
}

// ── Result card ────────────────────────────────────────────────────
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

// ── Credential storage ─────────────────────────────────────────────
// Credentials are stored in sessionStorage (cleared on tab close) and
// also in localStorage so the dashboard can fall back to them.
// They are NEVER sent anywhere except as the AWS auth payload to /deploy
// and /delete. The backend does NOT persist them in the database.
function storeCredentials(key, secret) {
  try {
    sessionStorage.setItem("_adops_key", key);
    sessionStorage.setItem("_adops_secret", secret);
    // Also store in localStorage so dashboard can find them
    // after page navigation within the same browser session.
    localStorage.setItem("aws_key", key);
    localStorage.setItem("aws_secret", secret);
  } catch (_) { }
}

function getStoredCredentials() {
  return {
    key: sessionStorage.getItem("_adops_key") || localStorage.getItem("aws_key") || "",
    secret: sessionStorage.getItem("_adops_secret") || localStorage.getItem("aws_secret") || "",
  };
}

// ── Credential download ────────────────────────────────────────────
// Gives the user a .env file with their credentials so they don't
// have to re-enter them every time they come back.
function downloadCredentials() {
  const awsKeyInput = document.getElementById("aws_key");
  const awsSecretInput = document.getElementById("aws_secret");

  const key = (awsKeyInput ? awsKeyInput.value.trim() : "") || getStoredCredentials().key;
  const secret = (awsSecretInput ? awsSecretInput.value.trim() : "") || getStoredCredentials().secret;

  if (!key || !secret) {
    showToast("No credentials to save. Deploy first.", "error");
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
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "aws_credentials.env";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  showToast("Credentials saved as aws_credentials.env", "success");
}

// ── Main deploy function ───────────────────────────────────────────
async function deploy() {
  if (_deployInProgress) {
    showToast("Deployment already in progress.", "info");
    return;
  }

  // Collect inputs
  const repo = (document.getElementById("repo")?.value || "").trim();
  const awsKey = (document.getElementById("aws_key")?.value || "").trim();
  const awsSecret = (document.getElementById("aws_secret")?.value || "").trim();
  const backendPort = (document.getElementById("backend_port")?.value || "").trim();
  const backendDf = (document.getElementById("backend_dockerfile")?.value || "").trim();
  const frontendDf = (document.getElementById("frontend_dockerfile")?.value || "").trim();

  // ── Validation ────────────────────────────────────────────────
  if (!repo) {
    setStatus("Enter a GitHub repository URL first.", "error");
    showToast("Repository URL is required.", "error");
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

  if (!backendDf && !frontendDf) {
    setStatus("Provide at least one Dockerfile.", "error");
    showToast("Paste at least one Dockerfile (backend or frontend).", "error");
    return;
  }

  if (backendDf && !backendPort) {
    setStatus("Backend port is required when using a backend Dockerfile.", "error");
    showToast("Enter the backend port number.", "error");
    // Auto-expand the backend section so user can see the port field
    const sec = document.getElementById("section-backend");
    const tog = document.getElementById("toggle-backend");
    if (sec && !sec.classList.contains("open")) {
      sec.classList.add("open");
      tog && tog.classList.add("open");
    }
    document.getElementById("backend_port")?.focus();
    return;
  }

  const backendPortNum = backendPort ? Number(backendPort) : null;
  const frontendPort = frontendDf ? 80 : null;

  // ── Persist credentials ───────────────────────────────────────
  storeCredentials(awsKey, awsSecret);

  // ── UI: start state ───────────────────────────────────────────
  _deployInProgress = true;
  setDeployButtonState(true);
  hideResultCard();
  clearLog();
  showTerminal();
  setStatus("Queuing deployment…", "active");
  appendLog("Validating inputs…", "info");
  appendLog(`Repo: ${repo}`, "");
  if (backendDf) appendLog(`Backend port: ${backendPortNum}`, "");
  if (frontendDf) appendLog("Frontend port: 80", "");
  appendLog("Sending to worker…", "info");
  appendLogCursor();

  try {
    const res = await fetch("/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_url: repo,
        aws_key: awsKey,
        aws_secret: awsSecret,
        backend_port: backendPortNum,
        frontend_port: frontendPort,
        backend_dockerfile: backendDf || null,
        frontend_dockerfile: frontendDf || null,
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
    appendLog(`Task queued — ID: ${data.task_id}`, "success");
    appendLog("Polling for status…", "info");
    appendLogCursor();
    setStatus("Worker picked up the task…", "active");

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

// ── Status polling ─────────────────────────────────────────────────
function startPolling(taskId) {
  if (_pollInterval) clearInterval(_pollInterval);

  let attempts = 0;
  const MAX_ATTEMPTS = 180; // 6 minutes at 2s intervals

  _pollInterval = setInterval(async () => {
    attempts++;

    if (attempts > MAX_ATTEMPTS) {
      clearInterval(_pollInterval);
      removeLogCursor();
      appendLog("Timeout — deploy is taking too long. Check dashboard later.", "error");
      setStatus("Timed out. Check dashboard for status.", "error");
      showToast("Deploy timed out after 6 minutes.", "error");
      _deployInProgress = false;
      setDeployButtonState(false);
      return;
    }

    try {
      const res = await fetch("/status/" + taskId);
      if (!res.ok) return; // transient error, keep polling

      const data = await res.json();
      const state = data.state || "";
      const meta = data.meta || {};

      // Update log with step info from worker metadata
      if (meta.step) {
        removeLogCursor();
        appendLog(meta.step, "info");
        appendLogCursor();
        setStatus(meta.step, "active");
      }

      if (state === "PENDING") {
        setStatus("Waiting for worker to pick up task…", "active");
      }

      if (state === "STARTED") {
        setStatus(meta.step || "Deploying on AWS infrastructure…", "active");
      }

      if (state === "SUCCESS") {
        clearInterval(_pollInterval);
        _deployInProgress = false;
        setDeployButtonState(false);
        removeLogCursor();

        const result = data.result || {};

        if (result.error) {
          // Task completed but reported an application-level error
          appendLog("Deploy error: " + result.error, "error");
          setStatus("Deployment failed — " + result.error, "error");
          showToast("Deployment failed.", "error");
          return;
        }

        appendLog("Deployment complete! 🎉", "success");
        setStatus("Deployment successful!", "success");
        showToast("App deployed successfully!", "success");

        // Build result card HTML
        let cardHtml = "";

        if (result.app_id) {
          cardHtml += `<div class="result-meta"><span style="color:var(--ink-2);">App ID</span> ${escHtml(result.app_id)}</div>`;
        }
        if (result.instance_id) {
          cardHtml += `<div class="result-meta"><span style="color:var(--ink-2);">Instance</span> ${escHtml(result.instance_id)}</div>`;
        }

        const links = [];
        if (result.frontend_url) {
          appendLog("Frontend: " + result.frontend_url, "success");
          links.push({ label: "Frontend", url: result.frontend_url });
        }
        if (result.backend_url) {
          appendLog("Backend:  " + result.backend_url, "success");
          links.push({ label: "Backend", url: result.backend_url });
        }
        if (links.length === 0 && result.url) {
          appendLog("URL: " + result.url, "success");
          links.push({ label: "App", url: result.url });
        }

        links.forEach(({ label, url }) => {
          cardHtml += `
            <div class="result-link-row">
              <span class="result-link-label">${label}</span>
              <a class="result-link-url" href="${url}" target="_blank" rel="noopener noreferrer">${escHtml(url)}</a>
            </div>`;
        });

        if (links.length === 0) {
          cardHtml += `<div class="result-meta" style="color:var(--ink-3);">No public URL returned. Check the dashboard.</div>`;
        }

        showResultCard(cardHtml);
      }

      if (state === "FAILURE") {
        clearInterval(_pollInterval);
        _deployInProgress = false;
        setDeployButtonState(false);
        removeLogCursor();
        appendLog("Worker task failed.", "error");
        setStatus("Deployment failed — worker error.", "error");
        showToast("Deployment failed on worker.", "error");
      }

    } catch (_) {
      // Network hiccup during polling — just skip this tick
    }
  }, 2000);
}

// ── Fill example ───────────────────────────────────────────────────
function fillExample() {
  const repoEl = document.getElementById("repo");
  const keyEl = document.getElementById("aws_key");
  const secretEl = document.getElementById("aws_secret");
  const portEl = document.getElementById("backend_port");
  const backendEl = document.getElementById("backend_dockerfile");
  const frontEl = document.getElementById("frontend_dockerfile");

  if (repoEl && !repoEl.value) repoEl.value = "https://github.com/user/my-app";
  if (keyEl && !keyEl.value) keyEl.value = "AKIAIOSFODNN7EXAMPLE";
  if (secretEl && !secretEl.value) secretEl.value = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";
  if (portEl && !portEl.value) portEl.value = "8000";

  if (backendEl && !backendEl.value) {
    backendEl.value =
      `FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`;
  }

  if (frontEl && !frontEl.value) {
    frontEl.value =
      `FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80`;
  }

  // Expand both sections so example data is visible
  ["backend", "frontend"].forEach(name => {
    const sec = document.getElementById("section-" + name);
    const tog = document.getElementById("toggle-" + name);
    if (sec && !sec.classList.contains("open")) {
      sec.classList.add("open");
      tog && tog.classList.add("open");
    }
  });

  showToast("Example data loaded.", "info");
}

// ── Clear form ─────────────────────────────────────────────────────
function clearForm() {
  ["repo", "aws_key", "aws_secret", "backend_port", "backend_dockerfile", "frontend_dockerfile"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

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

// ── Restore credentials on page load ──────────────────────────────
// If the user reloads the page mid-session, pre-fill credentials
// from sessionStorage so they don't have to type them again.
(function restoreCredentials() {
  const { key, secret } = getStoredCredentials();
  const keyEl = document.getElementById("aws_key");
  const secretEl = document.getElementById("aws_secret");
  if (keyEl && key && !keyEl.value) keyEl.value = key;
  if (secretEl && secret && !secretEl.value) secretEl.value = secret;
})();
