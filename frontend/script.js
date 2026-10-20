/* ─────────────────────────────────────────────────────────────────
   AutoDevOps : script.js
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
  const saved = localStorage.getItem("adops-theme");
  const theme = saved || "dark";
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

// ── Vault & Session Credentials ────────────────────────────────────
let _usingSavedVault = false;
let _vaultMaskedKey  = "";

async function initVaultState() {
  const token = typeof getAuthToken === "function" ? getAuthToken() : "";
  if (!token) {
    _usingSavedVault = false;
    updateVaultUI(false, "");
    return;
  }

  const status = await getVaultStatus();
  if (status && status.configured && status.masked_key) {
    _usingSavedVault = true;
    _vaultMaskedKey = status.masked_key;
    updateVaultUI(true, status.masked_key);
  } else {
    _usingSavedVault = false;
    _vaultMaskedKey = "";
    updateVaultUI(false, "");
  }
}

function updateVaultUI(hasVault, maskedKey) {
  const banner = document.getElementById("vault_deploy_banner");
  const preview = document.getElementById("vault_active_key_preview");
  const manualWrap = document.getElementById("manual_creds_wrap");
  const toggleBtn = document.getElementById("toggle_custom_creds_btn");

  if (!banner || !manualWrap) return;

  if (hasVault && _usingSavedVault) {
    banner.style.display = "flex";
    if (preview) preview.textContent = maskedKey || "AKIA••••";
    manualWrap.style.display = "none";
    if (toggleBtn) toggleBtn.textContent = "Use Custom / Enter New";
  } else {
    banner.style.display = hasVault ? "flex" : "none";
    if (preview) preview.textContent = maskedKey || "AKIA••••";
    manualWrap.style.display = "block";
    if (toggleBtn) toggleBtn.textContent = "Use Vault Credentials";
  }
}

function toggleCustomCreds() {
  _usingSavedVault = !_usingSavedVault;
  updateVaultUI(Boolean(_vaultMaskedKey), _vaultMaskedKey);
}

// ── Deploy Submission ──────────────────────────────────────────────
async function deploy() {
  if (_deployInProgress) {
    showToast("Deployment already in progress.", "info");
    return;
  }

  // Auth Guard
  const token = typeof getAuthToken === "function" ? getAuthToken() : "";
  if (!token) {
    showToast("Please sign in to deploy infrastructure.", "error");
    setTimeout(() => {
      window.location.href = "/login?redirect=/";
    }, 600);
    return;
  }

  const repo      = (document.getElementById("repo")?.value || "").trim();
  const awsKey    = (document.getElementById("aws_key")?.value || "").trim();
  const awsSecret = (document.getElementById("aws_secret")?.value || "").trim();
  const customDf  = (document.getElementById("custom_dockerfile")?.value || "").trim();
  const envVars   = (document.getElementById("env_vars")?.value || "").trim();
  const saveVault = document.getElementById("save_to_vault_check")?.checked;

  // ── Validation ───────────────────────────────────────────────────
  if (!repo) {
    setStatus("Enter a GitHub repository URL.", "error");
    showToast("GitHub URL is required.", "error");
    document.getElementById("repo")?.focus();
    return;
  }

  const repoRegex = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/;
  if (!repoRegex.test(repo)) {
    setStatus("Invalid GitHub repository format (use https://github.com/owner/repo).", "error");
    showToast("Please enter a valid GitHub repository URL: https://github.com/owner/repo", "error");
    document.getElementById("repo")?.focus();
    return;
  }

  // If NOT using saved vault, user must supply valid keys
  if (!_usingSavedVault) {
    if (!awsKey || !awsSecret) {
      setStatus("AWS credentials are required.", "error");
      showToast("Enter your AWS Access Key and Secret Key.", "error");
      document.getElementById("aws_key")?.focus();
      return;
    }
  }

  if (_currentAppType === "custom" && !customDf) {
    setStatus("Custom Dockerfile content is required.", "error");
    showToast("Paste your custom Dockerfile.", "error");
    document.getElementById("custom_dockerfile")?.focus();
    return;
  }

  // Optionally encrypt and save newly entered keys to vault
  if (!_usingSavedVault && awsKey && awsSecret && saveVault) {
    try {
      await saveVaultCredentials(awsKey, awsSecret);
      _vaultMaskedKey = maskKeyPreview(awsKey);
      _usingSavedVault = true;
      updateVaultUI(true, _vaultMaskedKey);
      showToast("Credentials encrypted & saved to vault.", "success");
    } catch (vErr) {
      console.warn("Could not auto-save to vault:", vErr);
    }
  }

  // ── Start UI state ───────────────────────────────────────────────
  _deployInProgress = true;
  setDeployButtonState(true);
  hideResultCard();
  clearLog();
  showTerminal();
  setStatus("Queuing deployment…", "active");

  appendLog("Validating request & permissions…", "info");
  appendLog(`Repository: ${repo}`);
  appendLog(`Runtime: ${_currentAppType.toUpperCase()} (Port 80)`);
  if (_usingSavedVault) {
    appendLog(`Credentials: Encrypted Vault Key (${_vaultMaskedKey || "Active"})`, "info");
  } else {
    appendLog("Credentials: Custom session keys attached", "info");
  }

  if (envVars) {
    const lineCount = envVars.split("\n").filter(l => l.trim() && !l.startsWith("#")).length;
    appendLog(`ENV Variables: ${lineCount} variable(s) attached (will be shredded on boot)`, "info");
  }
  appendLog("Submitting task to worker…", "info");
  appendLogCursor();

  try {
    const payload = {
      repo_url:          repo,
      app_type:          _currentAppType,
      custom_dockerfile: _currentAppType === "custom" ? customDf : null,
      env_vars:          envVars || null,
      use_saved_credentials: _usingSavedVault,
    };

    if (!_usingSavedVault) {
      payload.aws_key = awsKey;
      payload.aws_secret = awsSecret;
    }

    const res = await fetchWithAuth("/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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

function maskKeyPreview(key) {
  if (!key) return "";
  if (key.length <= 8) return "••••••••";
  return key.slice(0, 4) + "••••••••" + key.slice(-4);
}

// ── Real-time Status Polling ───────────────────────────────────────
function startPolling(taskId) {
  if (_pollInterval) clearInterval(_pollInterval);

  let attempts = 0;
  let lastLoggedStep = "";
  const MAX_ATTEMPTS = 180;

  const pollStep = async () => {
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

      if (meta.step && meta.step !== lastLoggedStep) {
        lastLoggedStep = meta.step;
        removeLogCursor();
        appendLog(meta.step, "info");
        appendLogCursor();
        setStatus(meta.step, "active");
      }

      if (state === "PENDING" && !meta.step) {
        setStatus("Allocating worker environment…", "active");
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

          const errHtml = `
            <div class="result-error-card" style="border: 1px solid rgba(239, 68, 68, 0.35); background: rgba(239, 68, 68, 0.08); border-radius: 12px; padding: 18px; margin-top: 6px;">
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
                <span style="font-size:22px;">🛑</span>
                <div>
                  <div style="font-weight:700; color:#f87171; font-size:15px;">Deployment Stopped: Real AWS Credentials Required</div>
                  <div style="font-size:12px; color:var(--ink-2); margin-top:2px;">No virtual machine or fake IP was created.</div>
                </div>
              </div>
              <p style="color:var(--ink-1); font-size:13px; line-height:1.6; margin: 10px 0 14px 0; background:rgba(0,0,0,0.25); padding:10px 12px; border-radius:8px; border-left:3px solid #ef4444;">
                ${escHtml(result.error)}
              </p>
              <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px 14px; font-size:12.5px; color:var(--ink-2); line-height:1.65; margin-bottom:14px;">
                <div style="font-weight:600; color:var(--ink-1); margin-bottom:6px;">How to deploy successfully:</div>
                <div style="margin-bottom:4px;">1. AutoDevOps provisions real Amazon EC2 instances directly on your AWS account.</div>
                <div style="margin-bottom:4px;">2. Go to the <strong>AWS Management Console &gt; IAM &gt; Users &gt; Security credentials</strong>.</div>
                <div style="margin-bottom:4px;">3. Generate an <strong>Access Key</strong> and ensure the policy <code>AmazonEC2FullAccess</code> is attached.</div>
                <div>4. Enter your real Access Key and Secret Key above, or store them in your private encrypted vault.</div>
              </div>
              <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <button type="button" class="btn btn-primary btn-sm" onclick="openVaultModal()">🔐 Open Credential Vault</button>
                <a href="https://console.aws.amazon.com/iam/home#/users" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="text-decoration:none;">↗ AWS IAM Console</a>
              </div>
            </div>`;
          showResultCard(errHtml);
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

        if (result.app_id) {
          const rawIp = liveUrl ? liveUrl.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : "YOUR_EC2_IP";
          cardHtml += `
            <div style="margin-top:16px;padding:14px;background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.25);border-radius:10px;">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
                <div style="display:flex;align-items:center;gap:6px;">
                  <span style="font-size:1.1rem;">🔑</span>
                  <span style="font-weight:700;font-size:0.85rem;color:var(--ink);">SSH Key &amp; Direct Server Access</span>
                </div>
                <button type="button" class="btn btn-secondary btn-sm" onclick="downloadSSHKey('${escHtml(result.app_id)}')">⬇ Download key-${escHtml(result.app_id)}.pem</button>
              </div>
              <div style="font-size:0.75rem;color:var(--ink-2);margin-bottom:6px;">To SSH into this EC2 instance from your laptop terminal:</div>
              <code style="display:block;background:rgba(0,0,0,0.35);padding:8px 12px;border-radius:6px;font-family:monospace;font-size:0.78rem;color:var(--purple);word-break:break-all;">chmod 400 key-${escHtml(result.app_id)}.pem &amp;&amp; ssh -i key-${escHtml(result.app_id)}.pem ubuntu@${escHtml(rawIp)}</code>
            </div>`;
        }

        showResultCard(cardHtml);
      }

      if (state === "FAILURE") {
        clearInterval(_pollInterval);
        _deployInProgress = false;
        setDeployButtonState(false);
        removeLogCursor();
        appendLog("Worker process terminated with failure.", "error");
        setStatus("Deployment failed: worker error.", "error");
        showToast("Deployment failed on worker.", "error");
      }

    } catch (_) {
      // transient network hiccup
    }
  };

  pollStep();
  _pollInterval = setInterval(pollStep, 1200);
}

// ── Load Example Helper ────────────────────────────────────────────
function fillExample() {
  const repoEl   = document.getElementById("repo");
  const envEl    = document.getElementById("env_vars");

  if (repoEl && !repoEl.value) repoEl.value = "https://github.com/tiangolo/fastapi";

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

  showToast("Example repository loaded. Enter your AWS IAM credentials to launch.", "info");
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

// ── Interactive Startup Presets & Tutorial Stepper ────────────────
function applyPreset(presetType, event) {
  if (event) event.stopPropagation();

  const repoEl = document.getElementById("repo");
  const envEl  = document.getElementById("env_vars");

  if (presetType === "fastapi") {
    if (repoEl) repoEl.value = "https://github.com/tiangolo/fastapi";
    selectAppType("python");
    if (envEl) {
      envEl.value = "ENVIRONMENT=production\nDEBUG=False\nPORT=80";
    }
    showToast("FastAPI preset loaded.", "info");
  } else if (presetType === "express") {
    if (repoEl) repoEl.value = "https://github.com/expressjs/express";
    selectAppType("nodejs");
    if (envEl) {
      envEl.value = "NODE_ENV=production\nPORT=80";
    }
    showToast("Express.js preset loaded.", "info");
  } else if (presetType === "flask") {
    if (repoEl) repoEl.value = "https://github.com/pallets/flask";
    selectAppType("python");
    if (envEl) {
      envEl.value = "FLASK_ENV=production\nPORT=80";
    }
    showToast("Flask preset loaded.", "info");
  }

  // Pulse animation on the repo input
  if (repoEl) {
    repoEl.classList.remove("highlight-pulse");
    void repoEl.offsetWidth; // trigger reflow
    repoEl.classList.add("highlight-pulse");
    repoEl.scrollIntoView({ behavior: "smooth", block: "center" });
    repoEl.focus();
  }

  focusTutorialStep(1);
}

function focusTutorialStep(stepNum) {
  [1, 2, 3].forEach(n => {
    const el = document.getElementById("step_card_" + n);
    if (el) {
      if (n === stepNum) el.classList.add("active");
      else el.classList.remove("active");
    }
  });

  if (stepNum === 1) {
    const repoEl = document.getElementById("repo");
    if (repoEl) repoEl.focus();
  } else if (stepNum === 2) {
    if (_usingSavedVault) {
      openVaultModal();
    } else {
      const keyEl = document.getElementById("aws_key");
      if (keyEl) {
        keyEl.scrollIntoView({ behavior: "smooth", block: "center" });
        keyEl.focus();
      }
    }
  } else if (stepNum === 3) {
    const deployBtn = document.getElementById("deploy_btn");
    if (deployBtn) {
      deployBtn.scrollIntoView({ behavior: "smooth", block: "center" });
      deployBtn.classList.remove("highlight-pulse");
      void deployBtn.offsetWidth;
      deployBtn.classList.add("highlight-pulse");
    }
  }
}

function openIamGuideModal(event) {
  if (event) event.stopPropagation();

  if (!document.getElementById("adops_iam_modal")) {
    const modalHtml = `
    <div id="adops_iam_modal" class="modal-backdrop" style="display:none;">
      <div class="modal-box" style="max-width:520px;">
        <div class="modal-header">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:1.3rem;">📖</span>
            <div>
              <div style="font-size:1.05rem;font-weight:700;color:var(--ink);">AWS IAM Setup Guide</div>
              <div style="font-size:0.78rem;color:var(--ink-3);">Minimum policies required for AutoDevOps orchestration</div>
            </div>
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="closeIamGuideModal()" style="padding:4px 8px;">✕</button>
        </div>
        <div style="font-size:0.83rem;color:var(--ink-2);line-height:1.6;margin-bottom:16px;">
          <p style="margin-bottom:10px;">To allow AutoDevOps to provision EC2 instances, key pairs, and security groups in your AWS account, your IAM user requires:</p>
          <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;margin-bottom:12px;">
            <div style="font-weight:700;color:var(--ink);margin-bottom:4px;">Required Policy:</div>
            <code style="color:var(--purple);font-family:var(--font-mono);font-size:0.82rem;">AmazonEC2FullAccess</code>
            <div style="font-size:0.74rem;color:var(--ink-3);margin-top:4px;">Covers: RunInstances, TerminateInstances, CreateKeyPair, CreateSecurityGroup.</div>
          </div>
          <ol style="padding-left:18px;margin-bottom:12px;font-size:0.8rem;color:var(--ink-2);display:flex;flex-direction:column;gap:6px;">
            <li>Go to <strong>AWS Console &rarr; IAM &rarr; Users &rarr; Create User</strong>.</li>
            <li>Attach the <code>AmazonEC2FullAccess</code> managed policy.</li>
            <li>Select <strong>Security Credentials &rarr; Create Access Key</strong> (Application running outside AWS).</li>
            <li>Copy the <strong>Access Key ID</strong> &amp; <strong>Secret Access Key</strong> into your AutoDevOps Vault.</li>
          </ol>
          <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:var(--radius-sm);padding:10px 12px;font-size:0.77rem;color:#86efac;">
            🛡️ <strong>Encryption Guarantee:</strong> All credentials are encrypted at rest with AES-256 Fernet. They are never logged or exposed in cleartext.
          </div>
        </div>
        <div style="display:flex;justify-content:flex-end;">
          <button type="button" class="btn btn-primary" onclick="closeIamGuideModal()">Got it!</button>
        </div>
      </div>
    </div>
    `;
    document.body.insertAdjacentHTML("beforeend", modalHtml);
    document.getElementById("adops_iam_modal").addEventListener("click", function(e) {
      if (e.target === this) closeIamGuideModal();
    });
  }

  document.getElementById("adops_iam_modal").style.display = "flex";
}

function closeIamGuideModal() {
  const modal = document.getElementById("adops_iam_modal");
  if (modal) modal.style.display = "none";
}

function downloadCredentials() {
  const card = document.getElementById("result_card");
  const codeEl = card ? card.querySelector("code") : null;
  const appId = codeEl ? codeEl.textContent.trim() : "";
  if (appId && typeof downloadSSHKey === "function") {
    downloadSSHKey(appId);
  } else {
    showToast("SSH keys are available on deployment completion or in Dashboard.", "info");
  }
}

// ── Initial Setup on Page Load ─────────────────────────────────────
async function bootApp() {
  initTheme();
  selectAppType("python");

  if (typeof renderNavbarAuth === "function") {
    renderNavbarAuth();
  }
  if (typeof initVaultState === "function") {
    await initVaultState();
  }

  window.addEventListener("adops-vault-updated", (e) => {
    if (e.detail && e.detail.configured && e.detail.masked_key) {
      _vaultMaskedKey = e.detail.masked_key;
      _usingSavedVault = true;
      updateVaultUI(true, _vaultMaskedKey);
    } else {
      _vaultMaskedKey = "";
      _usingSavedVault = false;
      updateVaultUI(false, "");
    }
  });

  const pendingPreset = localStorage.getItem("preset_deploy");
  if (pendingPreset) {
    localStorage.removeItem("preset_deploy");
    setTimeout(() => applyPreset(pendingPreset), 150);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootApp);
} else {
  bootApp();
}
