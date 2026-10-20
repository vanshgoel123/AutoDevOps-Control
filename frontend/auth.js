/* ─────────────────────────────────────────────────────────────────
   AutoDevOps : auth.js
   Client-side Authentication & Session Management
   - Bearer token handling (localStorage with auto-expiry check)
   - Route guard (requireAuth, redirectIfAuth)
   - Authenticated fetch helper (fetchWithAuth)
   - Global navbar user widget (email badge + vault status + logout)
───────────────────────────────────────────────────────────────── */

"use strict";

const AUTH_TOKEN_KEY = "adops_token";
const AUTH_USER_KEY  = "adops_user";

// ── Token & User Storage Helpers ─────────────────────────────────

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function setAuthToken(token) {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    // Also set as cookie for standard requests
    document.cookie = `adops_token=${encodeURIComponent(token)}; path=/; max-age=${60 * 60 * 24 * 7}; SameSite=Lax`;
  }
}

function getStoredUser() {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function setStoredUser(user) {
  if (user) {
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  }
}

function clearAuth() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  // Clear any legacy plain credentials that might be lingering
  localStorage.removeItem("aws_key");
  localStorage.removeItem("aws_secret");
  sessionStorage.removeItem("_adops_key");
  sessionStorage.removeItem("_adops_secret");
  document.cookie = "adops_token=; path=/; max-age=0";
}

function logout() {
  clearAuth();
  window.location.href = "/login";
}

// ── Authenticated Fetch Helper ───────────────────────────────────

async function fetchWithAuth(url, options = {}) {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // Session expired or invalid
    clearAuth();
    if (window.location.pathname !== "/login") {
      window.location.href = "/login?expired=1";
    }
  }

  return response;
}

// ── Route Guards ─────────────────────────────────────────────────

async function requireAuth(redirectPath = "/login") {
  const token = getAuthToken();
  if (!token) {
    window.location.href = redirectPath;
    return null;
  }

  try {
    const res = await fetchWithAuth("/api/auth/me");
    if (!res.ok) {
      clearAuth();
      window.location.href = redirectPath;
      return null;
    }
    const data = await res.json();
    setStoredUser(data.user);
    return data.user;
  } catch (err) {
    clearAuth();
    window.location.href = redirectPath;
    return null;
  }
}

function redirectIfAuth(destination = "/dashboard") {
  const token = getAuthToken();
  if (token) {
    window.location.href = destination;
  }
}

// ── Vault Helpers ────────────────────────────────────────────────

async function getVaultStatus() {
  try {
    const res = await fetchWithAuth("/api/credentials");
    if (!res.ok) return { configured: false, masked_key: null };
    return await res.json();
  } catch (_) {
    return { configured: false, masked_key: null };
  }
}

async function saveVaultCredentials(awsKey, awsSecret) {
  const res = await fetchWithAuth("/api/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ aws_key: awsKey, aws_secret: awsSecret }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to save credentials.");
  return data;
}

// ── Global Navbar Auth Widget Injection ─────────────────────────

function renderNavbarAuth() {
  const navActions = document.querySelector(".nav-actions");
  if (!navActions) return;

  const user = getStoredUser();
  const token = getAuthToken();

  // If already rendered, skip
  if (document.getElementById("nav_user_menu")) return;

  if (token && user) {
    const userWrap = document.createElement("div");
    userWrap.id = "nav_user_menu";
    userWrap.className = "nav-user-wrap";
    userWrap.style.cssText = "display:flex;align-items:center;gap:10px;";

    const emailPrefix = user.email ? user.email.split("@")[0] : "User";
    const isAdmin = Boolean(user.is_admin) || (user.email && user.email.toLowerCase() === "vanshg247776@gmail.com");
    const adminLinkHtml = isAdmin ? `
      <a href="/admin" class="btn btn-sm nav-admin-btn" id="nav_admin_btn" style="background:linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(139, 92, 246, 0.35));border:1px solid rgba(239, 68, 68, 0.5);color:#fca5a5;font-weight:600;display:inline-flex;align-items:center;gap:6px;text-decoration:none;padding:5px 11px;border-radius:8px;" title="Super-Admin Console & Database Inspector">
        <span>👑</span>
        <span>Admin Panel</span>
      </a>
    ` : "";

    userWrap.innerHTML = `
      ${adminLinkHtml}
      <button type="button" class="btn btn-ghost btn-sm nav-vault-btn" id="nav_vault_btn" onclick="openVaultModal()" title="Manage encrypted AWS credentials">
        <span class="vault-icon">🔑</span>
        <span class="vault-label">AWS Vault</span>
      </button>
      <div class="user-pill" title="${escHtml(user.email || "")}">
        <span class="user-avatar-dot"></span>
        <span class="user-pill-email">${escHtml(emailPrefix)}</span>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" onclick="logout()" title="Sign out" style="color:var(--ink-3);">
        Sign Out
      </button>
    `;

    // Insert before the action buttons (or at end)
    navActions.appendChild(userWrap);
  } else {
    // Anonymous user
    const loginLink = document.createElement("a");
    loginLink.id = "nav_login_btn";
    loginLink.className = "btn btn-primary btn-sm";
    loginLink.href = "/login";
    loginLink.textContent = "Sign In →";
    navActions.appendChild(loginLink);
  }
}

// ── Shared Vault Modal Injection ─────────────────────────────────

function ensureVaultModal() {
  if (document.getElementById("adops_vault_modal")) return;

  const modalHtml = `
  <div id="adops_vault_modal" class="modal-backdrop" style="display:none;">
    <div class="modal-box">
      <div class="modal-header">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:1.3rem;">🛡️</span>
          <div>
            <div style="font-size:1.05rem;font-weight:700;color:var(--ink);">Encrypted AWS Vault</div>
            <div style="font-size:0.78rem;color:var(--ink-3);margin-top:2px;">AES-256 encrypted at rest &middot; Scoped only to your account</div>
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" onclick="closeVaultModal()" style="padding:4px 8px;">✕</button>
      </div>

      <div id="vault_current_status" style="margin-bottom:16px;padding:12px 14px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;font-size:0.83rem;">
        <span style="color:var(--ink-2);">Checking vault status…</span>
      </div>

      <form id="vault_form" onsubmit="handleSaveVault(event)">
        <div class="field" style="margin-bottom:14px;">
          <label for="vault_aws_key">AWS Access Key ID</label>
          <input id="vault_aws_key" type="text" placeholder="AKIA…" autocomplete="off" spellcheck="false" required>
        </div>
        <div class="field" style="margin-bottom:20px;">
          <label for="vault_aws_secret">AWS Secret Access Key</label>
          <input id="vault_aws_secret" type="password" placeholder="••••••••••••••••••••••••••••••••" autocomplete="new-password" required>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button type="button" class="btn btn-ghost" onclick="closeVaultModal()">Cancel</button>
          <button type="submit" class="btn btn-primary" id="vault_save_btn">Encrypt &amp; Save</button>
        </div>
      </form>
    </div>
  </div>
  `;

  document.body.insertAdjacentHTML("beforeend", modalHtml);

  // Close on backdrop click
  document.getElementById("adops_vault_modal").addEventListener("click", function(e) {
    if (e.target === this) closeVaultModal();
  });
}

async function openVaultModal() {
  ensureVaultModal();
  const modal = document.getElementById("adops_vault_modal");
  const statusEl = document.getElementById("vault_current_status");

  modal.style.display = "flex";
  statusEl.innerHTML = `<span style="color:var(--ink-3);">Checking vault status…</span>`;

  const info = await getVaultStatus();
  if (info.configured && info.masked_key) {
    statusEl.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div>
          <span style="color:var(--green);font-weight:600;">✓ Active Vault Key:</span>
          <code style="margin-left:6px;background:rgba(34,197,94,0.12);color:var(--green);padding:2px 6px;border-radius:4px;font-family:monospace;">${escHtml(info.masked_key)}</code>
        </div>
        <button type="button" class="btn btn-danger btn-sm" onclick="handleDeleteVault()" style="font-size:0.72rem;padding:3px 8px;">Remove</button>
      </div>
      <div style="font-size:0.75rem;color:var(--ink-3);margin-top:6px;">Enter new credentials below only if you wish to rotate or replace them.</div>
    `;
    document.getElementById("vault_aws_key").required = false;
    document.getElementById("vault_aws_secret").required = false;
  } else {
    statusEl.innerHTML = `
      <span style="color:var(--amber);">⚠️ No credentials stored. Enter your AWS IAM keys below to deploy VMs with one click.</span>
    `;
    document.getElementById("vault_aws_key").required = true;
    document.getElementById("vault_aws_secret").required = true;
  }
}

function closeVaultModal() {
  const modal = document.getElementById("adops_vault_modal");
  if (modal) modal.style.display = "none";
}

async function handleSaveVault(e) {
  e.preventDefault();
  const key = document.getElementById("vault_aws_key").value.trim();
  const secret = document.getElementById("vault_aws_secret").value.trim();
  const btn = document.getElementById("vault_save_btn");

  if (!key || !secret) {
    if (typeof showToast === "function") showToast("Both AWS key and secret are required.", "error");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Encrypting…";

  try {
    const res = await saveVaultCredentials(key, secret);
    if (typeof showToast === "function") showToast(res.message || "Credentials securely saved!", "success");
    closeVaultModal();
    // Dispatch event so forms can refresh vault indicators
    window.dispatchEvent(new CustomEvent("adops-vault-updated", { detail: res }));
  } catch (err) {
    if (typeof showToast === "function") showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Encrypt & Save";
  }
}

async function handleDeleteVault() {
  if (!confirm("Are you sure you want to remove your saved AWS credentials?")) return;
  try {
    const res = await fetchWithAuth("/api/credentials", { method: "DELETE" });
    if (res.ok) {
      if (typeof showToast === "function") showToast("Vault credentials removed.", "info");
      openVaultModal();
      window.dispatchEvent(new CustomEvent("adops-vault-updated", { detail: { configured: false } }));
    }
  } catch (err) {
    if (typeof showToast === "function") showToast("Failed to remove credentials.", "error");
  }
}

// ── HTML Escaper ─────────────────────────────────────────────────
function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── SSH Private Key Downloader ───────────────────────────────────
async function downloadSSHKey(appId) {
  if (!appId) return;
  try {
    const res = await fetchWithAuth(`/api/apps/${encodeURIComponent(appId)}/ssh-key`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (typeof showToast === "function") {
        showToast(err.detail || "Could not download SSH key.", "error");
      }
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `key-${appId}.pem`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    if (typeof showToast === "function") {
      showToast(`key-${appId}.pem downloaded! (chmod 400 key-${appId}.pem)`, "success");
    }
  } catch (err) {
    if (typeof showToast === "function") {
      showToast("Download failed: " + err.message, "error");
    }
  }
}

