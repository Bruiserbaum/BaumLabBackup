/* ============================================================
   BaumLabBackup – Single Page Application
   ============================================================ */

'use strict';

// ---- State ----
const state = {
  token: localStorage.getItem('blb_token') || null,
  user: null,
  page: 'dashboard',
  dashboardTimer: null,
  oidcEnabled: false,
  oidcError: null,
};

// ---- OIDC callback handling ----
// Handle ?token= or ?oidc_error= redirected from /api/auth/oidc/callback
(function () {
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get('token');
  const urlError = params.get('oidc_error');
  if (urlToken) {
    state.token = urlToken;
    localStorage.setItem('blb_token', urlToken);
    window.history.replaceState({}, '', '/');
  }
  if (urlError) {
    state.oidcError = 'SSO login failed: ' + urlError.replace(/_/g, ' ');
    window.history.replaceState({}, '', '/');
  }
}());

// ---- API helper ----
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (state.token) opts.headers['Authorization'] = `Bearer ${state.token}`;
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch('/api' + path, opts);
  if (res.status === 401) {
    logout();
    return null;
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && (data.detail || JSON.stringify(data))) || res.statusText);
  return data;
}

// ---- Utilities ----
function formatBytes(bytes) {
  if (bytes == null || bytes === 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + ' ' + units[i];
}

function formatDuration(start, end) {
  if (!start || !end) return '—';
  const ms = new Date(end) - new Date(start);
  if (ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60), rem = s % 60;
  return m + 'm ' + rem + 's';
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function statusBadge(status) {
  const map = { success: 'badge-success', failed: 'badge-failed', running: 'badge-running' };
  const cls = map[status] || 'badge-warning';
  return `<span class="badge ${cls}">${status || 'unknown'}</span>`;
}

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function el(id) { return document.getElementById(id); }

function showError(containerId, msg) {
  const c = el(containerId);
  if (c) c.innerHTML = `<div class="form-error">${esc(msg)}</div>`;
}

// ---- Auth ----
function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem('blb_token');
  stopDashboardTimer();
  renderApp();
}

// ---- Navigation ----
function navigate(page) {
  stopDashboardTimer();
  state.page = page;
  renderMain();
  document.querySelectorAll('.nav-link').forEach(l => {
    l.classList.toggle('active', l.dataset.page === page);
  });
}

// ---- Routing ----
function _showLoginPage(app) {
  fetch('/api/auth/config')
    .then(r => r.json())
    .then(d => { state.oidcEnabled = !!d.oidc_enabled; })
    .catch(() => {})
    .finally(() => {
      app.innerHTML = renderLoginPage();
      bindLoginPage();
    });
}

function renderApp() {
  const app = el('app');
  if (!state.token) {
    // Try Authentik header auth first (silent — 404/401 means not configured or no header present)
    fetch('/api/auth/header-login')
      .then(async r => {
        if (r.ok) {
          const data = await r.json().catch(() => null);
          if (data && data.access_token) {
            state.token = data.access_token;
            localStorage.setItem('blb_token', data.access_token);
            renderApp();
            return;
          }
        }
        _showLoginPage(app);
      })
      .catch(() => _showLoginPage(app));
    return;
  }
  app.innerHTML = renderShell();
  renderMain();
  document.querySelectorAll('.nav-link').forEach(l => {
    l.addEventListener('click', () => navigate(l.dataset.page));
  });
  el('btn-logout').addEventListener('click', logout);

  // Load user info
  api('GET', '/auth/me').then(user => {
    if (user) {
      state.user = user;
      const userEl = el('navbar-username');
      if (userEl) userEl.textContent = user.username;
    }
  });
}

function renderShell() {
  return `
    <nav class="navbar">
      <span class="navbar-logo">◈ BaumLabBackup</span>
      <div class="navbar-links">
        <button class="nav-link ${state.page === 'dashboard' ? 'active' : ''}" data-page="dashboard">Dashboard</button>
        <button class="nav-link ${state.page === 'jobs' ? 'active' : ''}" data-page="jobs">Jobs</button>
        <button class="nav-link ${state.page === 'stacks' ? 'active' : ''}" data-page="stacks">Stacks</button>
        <button class="nav-link ${state.page === 'destinations' ? 'active' : ''}" data-page="destinations">Destinations</button>
        <button class="nav-link ${state.page === 'history' ? 'active' : ''}" data-page="history">History</button>
        <button class="nav-link ${state.page === 'settings' ? 'active' : ''}" data-page="settings">Settings</button>
      </div>
      <div class="navbar-user">
        <span id="navbar-username">...</span>
        <button class="btn btn-secondary btn-sm" id="btn-logout">Logout</button>
      </div>
    </nav>
    <div class="main-content" id="main-content"></div>
  `;
}

function renderMain() {
  const mc = el('main-content');
  if (!mc) return;
  switch (state.page) {
    case 'dashboard':    loadDashboard(mc); break;
    case 'jobs':         loadJobs(mc); break;
    case 'stacks':       loadStacks(mc); break;
    case 'destinations': loadDestinations(mc); break;
    case 'history':      loadHistory(mc, 1); break;
    case 'settings':     loadSettings(mc); break;
    default:             loadDashboard(mc);
  }
}

// ============================================================
// LOGIN PAGE
// ============================================================

function renderLoginPage() {
  const oidcBtn = state.oidcEnabled ? `
    <div style="display:flex;align-items:center;gap:8px;margin:8px 0">
      <div style="flex:1;height:1px;background:var(--border,#333)"></div>
      <span style="font-size:11px;color:var(--text-muted,#888)">or</span>
      <div style="flex:1;height:1px;background:var(--border,#333)"></div>
    </div>
    <a href="/api/auth/oidc/login" style="text-decoration:none">
      <button class="btn btn-secondary w-full" type="button">Login with Authentik</button>
    </a>` : '';
  return `
    <div class="login-wrapper">
      <div class="login-card">
        <h1>◈ BaumLabBackup</h1>
        <div class="form-group">
          <label>Username</label>
          <input class="form-control" id="login-username" type="text" autocomplete="username" placeholder="admin" />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input class="form-control" id="login-password" type="password" autocomplete="current-password" placeholder="••••••••" />
        </div>
        <div id="totp-section" style="display:none" class="form-group">
          <label>Authenticator Code</label>
          <input class="form-control" id="login-totp" type="text" inputmode="numeric" maxlength="6" placeholder="6-digit code" />
        </div>
        <div id="login-error" style="margin-bottom:8px"></div>
        <button class="btn btn-primary w-full" id="btn-login">Sign In</button>
        ${oidcBtn}
      </div>
    </div>
  `;
}

function bindLoginPage() {
  // Show OIDC error if redirected back after a failed SSO attempt
  if (state.oidcError) {
    el('login-error').innerHTML = `<div class="form-error">${esc(state.oidcError)}</div>`;
    state.oidcError = null;
  }

  const btn = el('btn-login');
  const doLogin = async () => {
    btn.disabled = true;
    el('login-error').innerHTML = '';
    try {
      const body = {
        username: el('login-username').value.trim(),
        password: el('login-password').value,
      };
      const totpVal = el('login-totp') ? el('login-totp').value.trim() : '';
      if (totpVal) body.totp_code = totpVal;

      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Login failed');

      if (data.totp_required) {
        el('totp-section').style.display = 'block';
        el('login-totp').focus();
        btn.disabled = false;
        return;
      }

      state.token = data.access_token;
      localStorage.setItem('blb_token', state.token);
      renderApp();
    } catch (e) {
      el('login-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
      btn.disabled = false;
    }
  };

  btn.addEventListener('click', doLogin);
  document.querySelectorAll('#login-username, #login-password, #login-totp').forEach(inp => {
    inp && inp.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  });
}

// ============================================================
// DASHBOARD
// ============================================================

function stopDashboardTimer() {
  if (state.dashboardTimer) {
    clearInterval(state.dashboardTimer);
    state.dashboardTimer = null;
  }
}

async function loadDashboard(container) {
  container.innerHTML = `<div class="page-title">Dashboard</div><p class="text-secondary">Loading...</p>`;
  try {
    const data = await api('GET', '/status');
    if (!data) return;
    renderDashboard(container, data);

    // Auto-refresh every 30 seconds
    stopDashboardTimer();
    state.dashboardTimer = setInterval(async () => {
      if (state.page !== 'dashboard') { stopDashboardTimer(); return; }
      const fresh = await api('GET', '/status');
      if (fresh) renderDashboard(container, fresh);
    }, 30000);
  } catch (e) {
    container.innerHTML = `<div class="page-title">Dashboard</div><div class="form-error">${esc(e.message)}</div>`;
  }
}

function renderDashboard(container, data) {
  const successRate = data.total_runs > 0
    ? Math.round((data.successful_runs / data.total_runs) * 100) : 0;

  const runningHtml = data.running_runs > 0
    ? `<div class="running-indicator"><span class="pulse"></span> ${data.running_runs} backup(s) currently running...</div>` : '';

  const recentRows = (data.recent_runs || []).map(run => `
    <tr>
      <td>${esc(run.job_name)}</td>
      <td>${statusBadge(run.status)}</td>
      <td>${formatDate(run.started_at)}</td>
      <td>${formatDuration(run.started_at, run.completed_at)}</td>
      <td>${formatBytes(run.size_bytes)}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="page-title">Dashboard</div>
    ${runningHtml}
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Jobs</div>
        <div class="stat-value">${data.total_jobs}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Active Jobs</div>
        <div class="stat-value">${data.enabled_jobs}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Runs</div>
        <div class="stat-value">${data.total_runs}</div>
      </div>
      <div class="stat-card${data.running_runs > 0 ? ' running' : ''}">
        <div class="stat-label">Success Rate</div>
        <div class="stat-value">${successRate}%</div>
      </div>
    </div>
    <div class="page-title" style="font-size:16px;margin-bottom:12px">Recent Runs</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Job</th><th>Status</th><th>Started</th><th>Duration</th><th>Size</th>
        </tr></thead>
        <tbody>
          ${recentRows || '<tr><td colspan="5" class="text-secondary" style="text-align:center;padding:24px">No runs yet</td></tr>'}
        </tbody>
      </table>
    </div>
  `;
}

// ============================================================
// JOBS PAGE
// ============================================================

async function loadJobs(container) {
  container.innerHTML = `<div class="page-title">Backup Jobs</div><p class="text-secondary">Loading...</p>`;
  try {
    const [jobs, destinations] = await Promise.all([
      api('GET', '/jobs'),
      api('GET', '/destinations'),
    ]);
    if (!jobs || !destinations) return;
    renderJobs(container, jobs, destinations);
  } catch (e) {
    container.innerHTML = `<div class="page-title">Backup Jobs</div><div class="form-error">${esc(e.message)}</div>`;
  }
}

function renderJobs(container, jobs, destinations) {
  const rows = jobs.map(job => {
    const dest = destinations.find(d => d.id === job.destination_id);
    return `
      <tr>
        <td><strong>${esc(job.name)}</strong></td>
        <td class="text-mono text-sm">${esc(job.schedule_cron)}</td>
        <td>
          ${job.last_run_status ? statusBadge(job.last_run_status) : '<span class="text-secondary">—</span>'}
          <br/><span class="text-secondary text-sm">${formatDate(job.last_run_at)}</span>
        </td>
        <td class="text-sm">${formatDate(job.next_run)}</td>
        <td>${dest ? esc(dest.name) : '<span class="text-secondary">—</span>'}</td>
        <td>
          <label class="toggle">
            <input type="checkbox" ${job.enabled ? 'checked' : ''} onchange="toggleJob(${job.id}, this)" />
            <span class="toggle-slider"></span>
          </label>
        </td>
        <td>
          <div class="row-actions">
            <button class="btn btn-secondary btn-sm" onclick="runJobNow(${job.id}, '${esc(job.name)}')">Run Now</button>
            <button class="btn btn-danger btn-sm" onclick="deleteJob(${job.id}, '${esc(job.name)}')">Delete</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  container.innerHTML = `
    <div class="flex justify-between items-center mb-4">
      <div class="page-title" style="margin-bottom:0">Backup Jobs</div>
      <button class="btn btn-primary" onclick="showAddJobModal()">+ Add Job</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Name</th><th>Schedule</th><th>Last Run</th><th>Next Run</th><th>Destination</th><th>Enabled</th><th>Actions</th>
        </tr></thead>
        <tbody>
          ${rows || '<tr><td colspan="7" class="text-secondary" style="text-align:center;padding:24px">No jobs yet. Click "+ Add Job" to create one.</td></tr>'}
        </tbody>
      </table>
    </div>
    <div id="job-modal-container"></div>
  `;
}

async function toggleJob(jobId, checkbox) {
  try {
    await api('PATCH', `/jobs/${jobId}/toggle`);
  } catch (e) {
    alert('Failed to toggle job: ' + e.message);
    checkbox.checked = !checkbox.checked;
  }
}

async function runJobNow(jobId, name) {
  if (!confirm(`Trigger backup job "${name}" now?`)) return;
  try {
    await api('POST', `/jobs/${jobId}/run`);
    alert('Job triggered! Check History for progress.');
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

async function deleteJob(jobId, name) {
  if (!confirm(`Delete job "${name}"? This cannot be undone.`)) return;
  try {
    await api('DELETE', `/jobs/${jobId}`);
    navigate('jobs');
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

async function showAddJobModal() {
  const [containers, volumes, destinations] = await Promise.all([
    api('GET', '/jobs/containers'),
    api('GET', '/jobs/volumes'),
    api('GET', '/destinations'),
  ]);

  const containerChecks = (containers || []).map(c => `
    <label class="form-check">
      <input type="checkbox" name="job_containers" value="${esc(c.name)}" />
      ${esc(c.name)} <span class="text-secondary text-sm">(${esc(c.status)})</span>
    </label>
  `).join('');

  const destOptions = (destinations || []).map(d =>
    `<option value="${d.id}">${esc(d.name)} (${d.type})</option>`
  ).join('');

  const modalHtml = `
    <div class="modal-overlay" id="job-modal-overlay">
      <div class="modal">
        <button class="modal-close" onclick="closeModal('job-modal-overlay')">✕</button>
        <div class="modal-title">Add Backup Job</div>
        <div id="job-modal-error"></div>

        <div class="form-group">
          <label>Job Name</label>
          <input class="form-control" id="jm-name" placeholder="my-backup" />
        </div>

        <div class="form-section">
          <div class="form-section-title">Containers</div>
          <div class="container-list">
            ${containerChecks || '<span class="text-secondary text-sm">No containers found</span>'}
          </div>
          <div class="form-check mt-2">
            <input type="checkbox" id="jm-prestop" />
            <label for="jm-prestop">Stop containers before backup (pre-stop)</label>
          </div>
        </div>

        <div class="form-section">
          <div class="form-section-title">Volumes / Paths</div>
          <div class="volume-rows" id="jm-vol-rows">
            <div class="volume-row">
              <input class="form-control" placeholder="Source path (e.g. /var/lib/docker/volumes/myapp/_data)" data-vol-src />
              <input class="form-control" placeholder="Archive name" data-vol-name style="max-width:160px" />
              <button class="btn btn-danger btn-sm" onclick="removeVolumeRow(this)">✕</button>
            </div>
          </div>
          <button class="btn btn-secondary btn-sm mt-2" onclick="addVolumeRow()">+ Add Path</button>
        </div>

        <div class="form-section">
          <div class="form-section-title">Database Dump (optional)</div>
          <div class="form-group">
            <label>DB Type</label>
            <select class="form-control" id="jm-dbtype" onchange="updateDbFields()">
              <option value="">None</option>
              <option value="mysql">MySQL / MariaDB</option>
              <option value="postgres">PostgreSQL</option>
            </select>
          </div>
          <div id="jm-db-fields" style="display:none">
            <div class="form-group">
              <label>DB Container Name</label>
              <input class="form-control" id="jm-db-container" placeholder="mysql-container" />
            </div>
            <div class="form-group">
              <label>Database Name</label>
              <input class="form-control" id="jm-db-name" placeholder="mydb" />
            </div>
            <div class="form-group">
              <label>DB User</label>
              <input class="form-control" id="jm-db-user" placeholder="root" />
            </div>
            <div class="form-group">
              <label>DB Password</label>
              <input class="form-control" id="jm-db-pass" type="password" />
            </div>
          </div>
        </div>

        <div class="form-group">
          <label>Destination</label>
          <select class="form-control" id="jm-dest">
            <option value="">— Select destination —</option>
            ${destOptions}
          </select>
        </div>

        <div class="form-group">
          <label>Schedule (cron)</label>
          <input class="form-control" id="jm-cron" placeholder="0 2 * * *" value="0 2 * * *" />
          <div class="form-hint">5-field cron. Examples: <code>0 2 * * *</code> = daily at 2am &nbsp;|&nbsp; <code>0 */6 * * *</code> = every 6h</div>
        </div>

        <div class="form-group">
          <label>Retention (days, 0 = keep forever)</label>
          <input class="form-control" id="jm-retention" type="number" value="30" min="0" />
        </div>

        <div class="form-check">
          <input type="checkbox" id="jm-enabled" checked />
          <label for="jm-enabled">Enabled</label>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="closeModal('job-modal-overlay')">Cancel</button>
          <button class="btn btn-primary" onclick="submitAddJob()">Create Job</button>
        </div>
      </div>
    </div>
  `;

  el('job-modal-container').innerHTML = modalHtml;
}

function updateDbFields() {
  const val = el('jm-dbtype').value;
  el('jm-db-fields').style.display = val ? 'block' : 'none';
}

function addVolumeRow() {
  const row = document.createElement('div');
  row.className = 'volume-row';
  row.innerHTML = `
    <input class="form-control" placeholder="Source path" data-vol-src />
    <input class="form-control" placeholder="Archive name" data-vol-name style="max-width:160px" />
    <button class="btn btn-danger btn-sm" onclick="removeVolumeRow(this)">✕</button>
  `;
  el('jm-vol-rows').appendChild(row);
}

function removeVolumeRow(btn) {
  const rows = el('jm-vol-rows');
  if (rows.children.length > 1) btn.closest('.volume-row').remove();
}

async function submitAddJob() {
  el('job-modal-error').innerHTML = '';
  try {
    const name = el('jm-name').value.trim();
    if (!name) throw new Error('Job name is required');

    const containers = Array.from(document.querySelectorAll('input[name=job_containers]:checked'))
      .map(c => c.value);

    const volumes = Array.from(el('jm-vol-rows').querySelectorAll('.volume-row'))
      .map(row => ({
        source: row.querySelector('[data-vol-src]').value.trim(),
        name: row.querySelector('[data-vol-name]').value.trim(),
      }))
      .filter(v => v.source);

    const dbType = el('jm-dbtype').value;
    const destId = parseInt(el('jm-dest').value);
    if (!destId) throw new Error('Please select a destination');

    const body = {
      name,
      containers,
      volumes,
      db_type: dbType || null,
      db_container: dbType ? el('jm-db-container').value.trim() : null,
      db_name: dbType ? el('jm-db-name').value.trim() : null,
      db_user: dbType ? el('jm-db-user').value.trim() : null,
      db_password: dbType ? el('jm-db-pass').value : null,
      destination_id: destId,
      schedule_cron: el('jm-cron').value.trim(),
      pre_stop: el('jm-prestop').checked,
      retention_days: parseInt(el('jm-retention').value) || 30,
      enabled: el('jm-enabled').checked,
    };

    await api('POST', '/jobs', body);
    closeModal('job-modal-overlay');
    navigate('jobs');
  } catch (e) {
    el('job-modal-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

// ============================================================
// STACKS PAGE
// ============================================================

async function loadStacks(container) {
  container.innerHTML = `
    <div class="page-header">
      <h2>Stacks</h2>
      <div style="display:flex;gap:8px">
        <button class="btn btn-secondary" id="btn-detect-stacks">Detect from Docker</button>
        <button class="btn btn-primary" id="btn-add-stack">+ Add Stack</button>
      </div>
    </div>
    <div id="stacks-table-wrap"><p style="color:var(--text-muted)">Loading...</p></div>
    <div id="stack-run-log-wrap" style="margin-top:24px"></div>
  `;

  el('btn-add-stack').addEventListener('click', () => openAddStackModal());
  el('btn-detect-stacks').addEventListener('click', detectAndFillStacks);

  await refreshStacksTable();
}

async function refreshStacksTable() {
  const wrap = el('stacks-table-wrap');
  if (!wrap) return;
  try {
    const [stacks, dests] = await Promise.all([
      api('GET', '/stacks'),
      api('GET', '/destinations'),
    ]);
    if (!stacks || stacks.length === 0) {
      wrap.innerHTML = `<p style="color:var(--text-muted)">No stacks configured. Use <strong>Detect from Docker</strong> or <strong>+ Add Stack</strong>.</p>`;
      return;
    }
    const destMap = Object.fromEntries((dests || []).map(d => [d.id, d.name]));
    wrap.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>Name</th><th>Repo</th><th>Project</th><th>Destination</th>
          <th>Last Backup</th><th>Next Backup</th><th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody>
          ${stacks.map(s => `
            <tr>
              <td><strong>${esc(s.name)}</strong></td>
              <td style="font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                <a href="${esc(s.repo_url)}" target="_blank" title="${esc(s.repo_url)}" style="color:var(--accent)">${esc(s.repo_url)}</a>
              </td>
              <td><code>${esc(s.compose_project)}</code></td>
              <td>${esc(destMap[s.destination_id] || s.destination_id)}</td>
              <td>${formatDate(s.last_backup_at)}</td>
              <td>${s.schedule_cron ? (formatDate(s.next_run) || s.schedule_cron) : '<span style="color:var(--text-muted)">Manual</span>'}</td>
              <td>${s.last_backup_status ? statusBadge(s.last_backup_status) : '<span style="color:var(--text-muted)">—</span>'}</td>
              <td>
                <div style="display:flex;gap:4px;flex-wrap:wrap">
                  <button class="btn btn-secondary btn-sm" onclick="triggerStackBackup(${s.id}, '${esc(s.name)}')">Backup</button>
                  <button class="btn btn-secondary btn-sm" onclick="openBrowseBackups(${s.id}, '${esc(s.name)}')">Restore</button>
                  <button class="btn btn-secondary btn-sm" onclick="openStackRunLog(${s.id})">Logs</button>
                  <button class="btn btn-secondary btn-sm" onclick="openEditStackModal(${s.id})">Edit</button>
                  <button class="btn btn-danger btn-sm" onclick="deleteStack(${s.id}, '${esc(s.name)}')">Delete</button>
                </div>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    wrap.innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

// ── Detect stacks ─────────────────────────────────────────────────────────────

async function detectAndFillStacks() {
  const btn = el('btn-detect-stacks');
  btn.textContent = 'Detecting...';
  btn.disabled = true;
  try {
    const detected = await api('GET', '/stacks/detect');
    if (!detected || detected.length === 0) {
      alert('No Docker Compose stacks detected. Make sure containers are running and were started with docker compose.');
      return;
    }
    openDetectModal(detected);
  } catch (e) {
    alert('Detection failed: ' + e.message);
  } finally {
    btn.textContent = 'Detect from Docker';
    btn.disabled = false;
  }
}

function openDetectModal(detected) {
  const rows = detected.map((s, i) => `
    <tr>
      <td><input type="checkbox" id="det-chk-${i}" checked></td>
      <td><strong>${esc(s.compose_project)}</strong></td>
      <td style="font-size:12px">${s.containers.slice(0, 3).map(esc).join(', ')}${s.containers.length > 3 ? ` +${s.containers.length - 3} more` : ''}</td>
      <td style="font-size:12px">${s.volumes.map(esc).join(', ') || '<em>none</em>'}</td>
      <td style="font-size:12px;max-width:160px;word-break:break-all">${esc(s.env_file)}</td>
    </tr>`).join('');

  showModal('Detected Compose Stacks', `
    <p style="color:var(--text-muted);margin-bottom:12px">Select stacks to import. You can edit repo URL and destination after adding.</p>
    <table class="data-table" style="margin-bottom:12px">
      <thead><tr><th></th><th>Project</th><th>Containers</th><th>Volumes</th><th>.env path</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div id="detect-error"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="btn-import-detected">Import Selected</button>
    </div>
  `);

  el('btn-import-detected').addEventListener('click', async () => {
    const selected = detected.filter((_, i) => el(`det-chk-${i}`)?.checked);
    if (!selected.length) { showError('detect-error', 'Select at least one stack.'); return; }

    // For each selected, open the add-stack modal pre-filled
    closeModal();
    // Open first one; user can add others manually
    if (selected.length === 1) {
      openAddStackModal(selected[0]);
    } else {
      // Queue: open modals one after another
      for (const s of selected) {
        await new Promise(resolve => openAddStackModal(s, resolve));
      }
    }
  });
}

// ── Add / Edit Stack modal ────────────────────────────────────────────────────

async function openAddStackModal(prefill = null, onDone = null) {
  const [dests, vols] = await Promise.all([
    api('GET', '/destinations'),
    api('GET', '/stacks/volumes'),
  ]);

  const destOptions = (dests || []).map(d =>
    `<option value="${d.id}">${esc(d.name)} (${esc(d.type)})</option>`).join('');

  const volChecks = (vols || []).map(v => {
    const checked = prefill && prefill.volumes && prefill.volumes.includes(v.name) ? 'checked' : '';
    return `<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
      <input type="checkbox" name="vol" value="${esc(v.name)}" ${checked}> ${esc(v.name)}
    </label>`;
  }).join('');

  showModal('Add Stack', `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="form-group" style="grid-column:1/-1">
        <label>Stack Name *</label>
        <input class="form-control" id="s-name" value="${esc(prefill?.compose_project || '')}" placeholder="e.g. BaumLab">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Repository URL *</label>
        <input class="form-control" id="s-repo" value="${esc(prefill?.repo_url || '')}" placeholder="https://github.com/Bruiserbaum/BaumLab">
      </div>
      <div class="form-group">
        <label>Branch</label>
        <input class="form-control" id="s-branch" value="${esc(prefill?.repo_branch || 'main')}">
      </div>
      <div class="form-group">
        <label>Compose Project Name *</label>
        <input class="form-control" id="s-project" value="${esc(prefill?.compose_project || '')}" placeholder="baumlab">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>.env File Path (on host) *</label>
        <input class="form-control" id="s-env" value="${esc(prefill?.env_file || prefill?.env_path || '')}" placeholder="/opt/baumlab/.env">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Volumes to Back Up</label>
        <div style="max-height:160px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px">
          ${volChecks || '<p style="color:var(--text-muted);margin:0">No volumes found</p>'}
        </div>
      </div>
      <div class="form-group">
        <label>Destination *</label>
        <select class="form-control" id="s-dest">${destOptions}</select>
      </div>
      <div class="form-group">
        <label>Retention (days)</label>
        <input class="form-control" id="s-retention" type="number" value="30" min="1">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Schedule (cron) <span style="color:var(--text-muted);font-size:11px">— leave blank for manual only</span></label>
        <input class="form-control" id="s-cron" value="" placeholder="0 3 * * *  (daily at 3am)">
      </div>
    </div>
    <div id="add-stack-error"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="btn-save-stack">Save Stack</button>
    </div>
  `);

  el('btn-save-stack').addEventListener('click', async () => {
    const name = el('s-name').value.trim();
    const repo_url = el('s-repo').value.trim();
    const repo_branch = el('s-branch').value.trim() || 'main';
    const compose_project = el('s-project').value.trim();
    const env_path = el('s-env').value.trim();
    const destination_id = parseInt(el('s-dest').value);
    const retention_days = parseInt(el('s-retention').value) || 30;
    const schedule_cron = el('s-cron').value.trim() || null;
    const volumes = [...document.querySelectorAll('input[name="vol"]:checked')].map(c => c.value);

    if (!name || !repo_url || !compose_project) {
      showError('add-stack-error', 'Name, Repo URL, and Compose Project are required.');
      return;
    }

    try {
      el('btn-save-stack').disabled = true;
      await api('POST', '/stacks', { name, repo_url, repo_branch, env_path, compose_project, volumes, destination_id, schedule_cron, retention_days });
      closeModal();
      await refreshStacksTable();
      if (onDone) onDone();
    } catch (e) {
      showError('add-stack-error', e.message);
      el('btn-save-stack').disabled = false;
    }
  });
}

async function openEditStackModal(stackId) {
  const [stack, dests, vols] = await Promise.all([
    api('GET', `/stacks`).then(all => (all || []).find(s => s.id === stackId)),
    api('GET', '/destinations'),
    api('GET', '/stacks/volumes'),
  ]);
  if (!stack) return alert('Stack not found');

  const destOptions = (dests || []).map(d =>
    `<option value="${d.id}" ${d.id === stack.destination_id ? 'selected' : ''}>${esc(d.name)} (${esc(d.type)})</option>`).join('');

  const volChecks = (vols || []).map(v => {
    const checked = stack.volumes.includes(v.name) ? 'checked' : '';
    return `<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
      <input type="checkbox" name="vol" value="${esc(v.name)}" ${checked}> ${esc(v.name)}
    </label>`;
  }).join('');

  showModal('Edit Stack', `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="form-group" style="grid-column:1/-1">
        <label>Stack Name *</label>
        <input class="form-control" id="s-name" value="${esc(stack.name)}">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Repository URL *</label>
        <input class="form-control" id="s-repo" value="${esc(stack.repo_url)}">
      </div>
      <div class="form-group">
        <label>Branch</label>
        <input class="form-control" id="s-branch" value="${esc(stack.repo_branch)}">
      </div>
      <div class="form-group">
        <label>Compose Project Name *</label>
        <input class="form-control" id="s-project" value="${esc(stack.compose_project)}">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>.env File Path (on host)</label>
        <input class="form-control" id="s-env" value="${esc(stack.env_path)}">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Volumes to Back Up</label>
        <div style="max-height:160px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px">
          ${volChecks || '<p style="color:var(--text-muted);margin:0">No volumes found</p>'}
        </div>
      </div>
      <div class="form-group">
        <label>Destination *</label>
        <select class="form-control" id="s-dest">${destOptions}</select>
      </div>
      <div class="form-group">
        <label>Retention (days)</label>
        <input class="form-control" id="s-retention" type="number" value="${stack.retention_days}" min="1">
      </div>
      <div class="form-group" style="grid-column:1/-1">
        <label>Schedule (cron) <span style="color:var(--text-muted);font-size:11px">— leave blank for manual only</span></label>
        <input class="form-control" id="s-cron" value="${esc(stack.schedule_cron || '')}">
      </div>
    </div>
    <div id="edit-stack-error"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="btn-update-stack">Save Changes</button>
    </div>
  `);

  el('btn-update-stack').addEventListener('click', async () => {
    const name = el('s-name').value.trim();
    const repo_url = el('s-repo').value.trim();
    const repo_branch = el('s-branch').value.trim() || 'main';
    const compose_project = el('s-project').value.trim();
    const env_path = el('s-env').value.trim();
    const destination_id = parseInt(el('s-dest').value);
    const retention_days = parseInt(el('s-retention').value) || 30;
    const schedule_cron = el('s-cron').value.trim() || null;
    const volumes = [...document.querySelectorAll('input[name="vol"]:checked')].map(c => c.value);

    if (!name || !repo_url || !compose_project) {
      showError('edit-stack-error', 'Name, Repo URL, and Compose Project are required.');
      return;
    }

    try {
      el('btn-update-stack').disabled = true;
      await api('PUT', `/stacks/${stackId}`, { name, repo_url, repo_branch, env_path, compose_project, volumes, destination_id, schedule_cron, retention_days });
      closeModal();
      await refreshStacksTable();
    } catch (e) {
      showError('edit-stack-error', e.message);
      el('btn-update-stack').disabled = false;
    }
  });
}

// ── Backup / delete ───────────────────────────────────────────────────────────

async function triggerStackBackup(stackId, stackName) {
  try {
    await api('POST', `/stacks/${stackId}/backup`);
    alert(`Backup started for "${stackName}". Check Logs for progress.`);
    await refreshStacksTable();
  } catch (e) {
    alert('Failed to trigger backup: ' + e.message);
  }
}

async function deleteStack(stackId, stackName) {
  if (!confirm(`Delete stack "${stackName}"? Existing backups on the destination are NOT deleted.`)) return;
  try {
    await api('DELETE', `/stacks/${stackId}`);
    await refreshStacksTable();
  } catch (e) {
    alert('Delete failed: ' + e.message);
  }
}

// ── Browse backups / restore ──────────────────────────────────────────────────

async function openBrowseBackups(stackId, stackName) {
  showModal(`Restore: ${stackName}`, `<p style="color:var(--text-muted)">Loading available backups...</p>`);
  try {
    const data = await api('GET', `/stacks/${stackId}/backups`);
    const backups = data?.backups || [];
    if (!backups.length) {
      setModalBody(`<p style="color:var(--text-muted)">No backups found at <code>${esc(data?.remote_path || '')}</code>.</p>
        <button class="btn btn-secondary" onclick="closeModal()">Close</button>`);
      return;
    }
    const rows = backups.map(b => `
      <tr>
        <td style="font-size:12px">${esc(b.name)}</td>
        <td>${formatBytes(b.size)}</td>
        <td>${b.modified ? new Date(b.modified).toLocaleString() : '—'}</td>
        <td><button class="btn btn-primary btn-sm" onclick="openRestoreModal(${stackId}, '${esc(stackName)}', '${esc(b.name)}')">Restore</button></td>
      </tr>`).join('');

    setModalBody(`
      <p style="color:var(--text-muted);margin-bottom:8px">Remote: <code>${esc(data?.remote_path || '')}</code></p>
      <table class="data-table" style="margin-bottom:12px">
        <thead><tr><th>Archive</th><th>Size</th><th>Date</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <button class="btn btn-secondary" onclick="closeModal()">Close</button>
    `);
  } catch (e) {
    setModalBody(`<div class="form-error">${esc(e.message)}</div><button class="btn btn-secondary" onclick="closeModal()">Close</button>`);
  }
}

function openRestoreModal(stackId, stackName, backupFilename) {
  const defaultTarget = `/opt/${stackName.toLowerCase().replace(/\s+/g, '-')}`;
  setModalBody(`
    <h3 style="margin-bottom:12px">Restore from: <code style="font-size:13px">${esc(backupFilename)}</code></h3>
    <div class="form-group">
      <label>Clone target directory *</label>
      <input class="form-control" id="restore-target" value="${esc(defaultTarget)}" placeholder="/opt/baumlab">
      <small style="color:var(--text-muted)">The repo will be cloned here and .env placed inside.</small>
    </div>
    <div class="form-group">
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="restore-autostart" checked>
        Auto-start stack after restore (<code>docker compose up -d</code>)
      </label>
    </div>
    <div id="restore-error"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="openBrowseBackups(${stackId}, '${esc(stackName)}')">← Back</button>
      <button class="btn btn-primary" id="btn-start-restore">Start Restore</button>
    </div>
  `);

  el('btn-start-restore').addEventListener('click', async () => {
    const restore_target_dir = el('restore-target').value.trim();
    const auto_start = el('restore-autostart').checked;
    if (!restore_target_dir) { showError('restore-error', 'Target directory is required.'); return; }

    try {
      el('btn-start-restore').disabled = true;
      const resp = await api('POST', `/stacks/${stackId}/restore`, {
        backup_filename: backupFilename,
        restore_target_dir,
        auto_start,
      });
      closeModal();
      alert(`Restore started. Click "Logs" on the stack row to monitor progress.`);
      await refreshStacksTable();
    } catch (e) {
      showError('restore-error', e.message);
      el('btn-start-restore').disabled = false;
    }
  });
}

// ── Stack run log viewer ──────────────────────────────────────────────────────

async function openStackRunLog(stackId) {
  const wrap = el('stack-run-log-wrap');
  if (!wrap) return;

  wrap.innerHTML = `<p style="color:var(--text-muted)">Loading run history...</p>`;
  try {
    const data = await api('GET', `/stacks/runs?stack_id=${stackId}&page=1`);
    const runs = data?.runs || [];
    if (!runs.length) {
      wrap.innerHTML = `<p style="color:var(--text-muted)">No runs yet for this stack.</p>`;
      return;
    }
    const rows = runs.map(r => `
      <tr style="cursor:pointer" onclick="showStackRunDetail(${r.id})">
        <td>${statusBadge(r.status)}</td>
        <td><span class="badge" style="background:var(--border);color:var(--text)">${esc(r.run_type)}</span></td>
        <td>${formatDate(r.started_at)}</td>
        <td>${formatDuration(r.started_at, r.completed_at)}</td>
        <td>${formatBytes(r.size_bytes)}</td>
      </tr>`).join('');

    wrap.innerHTML = `
      <h3 style="margin-bottom:8px">Run History</h3>
      <table class="data-table">
        <thead><tr><th>Status</th><th>Type</th><th>Started</th><th>Duration</th><th>Size</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (e) {
    wrap.innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

async function showStackRunDetail(runId) {
  showModal('Run Log', `<p style="color:var(--text-muted)">Loading...</p>`);
  try {
    const run = await api('GET', `/stacks/runs/${runId}`);
    renderStackRunModal(run);

    // Poll while running
    if (run.status === 'running') {
      _stackLogPollTimer = setInterval(async () => {
        const updated = await api('GET', `/stacks/runs/${runId}`);
        if (!updated) { clearInterval(_stackLogPollTimer); return; }
        renderStackRunModal(updated);
        if (updated.status !== 'running') {
          clearInterval(_stackLogPollTimer);
          await refreshStacksTable();
        }
      }, 2000);
    }
  } catch (e) {
    setModalBody(`<div class="form-error">${esc(e.message)}</div><button class="btn btn-secondary" onclick="closeModal()">Close</button>`);
  }
}

function renderStackRunModal(run) {
  const logHtml = (run.log_lines || []).map(line => {
    const cls = /error/i.test(line) ? 'color:#e06c75' : /warning|warn/i.test(line) ? 'color:#e5c07b' : /ok|success|complete/i.test(line) ? 'color:#98c379' : 'color:var(--text)';
    return `<div style="${cls};font-size:12px;line-height:1.5">${esc(line)}</div>`;
  }).join('');

  const typeLabel = run.run_type === 'restore' ? '🔄 Restore' : '💾 Backup';
  setModalBody(`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;font-size:13px">
      <div><strong>Stack:</strong> ${esc(run.stack_name)}</div>
      <div><strong>Type:</strong> ${typeLabel}</div>
      <div><strong>Status:</strong> ${statusBadge(run.status)}</div>
      <div><strong>Started:</strong> ${formatDate(run.started_at)}</div>
      <div><strong>Duration:</strong> ${formatDuration(run.started_at, run.completed_at)}</div>
      <div><strong>Size:</strong> ${formatBytes(run.size_bytes)}</div>
      ${run.restore_target ? `<div style="grid-column:1/-1"><strong>Target:</strong> <code>${esc(run.restore_target)}</code></div>` : ''}
    </div>
    ${run.error ? `<div class="form-error" style="margin-bottom:8px">${esc(run.error)}</div>` : ''}
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:12px;max-height:320px;overflow-y:auto;font-family:monospace">
      ${logHtml || '<span style="color:var(--text-muted)">No log lines yet...</span>'}
    </div>
    ${run.status === 'running' ? '<p style="color:var(--text-muted);font-size:12px;margin-top:8px">Auto-refreshing every 2s...</p>' : ''}
    <div style="display:flex;justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">Close</button>
    </div>
  `);
}

// ============================================================
// DESTINATIONS PAGE
// ============================================================

async function loadDestinations(container) {
  container.innerHTML = `<div class="page-title">Destinations</div><p class="text-secondary">Loading...</p>`;
  try {
    const dests = await api('GET', '/destinations');
    if (!dests) return;
    renderDestinations(container, dests);
  } catch (e) {
    container.innerHTML = `<div class="page-title">Destinations</div><div class="form-error">${esc(e.message)}</div>`;
  }
}

function renderDestinations(container, dests) {
  const rows = dests.map(d => `
    <tr>
      <td><strong>${esc(d.name)}</strong></td>
      <td><span class="badge badge-warning">${esc(d.type.toUpperCase())}</span></td>
      <td class="text-sm text-secondary">${formatDate(d.created_at)}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="testDestConnection(${d.id})">Test</button>
        <button class="btn btn-secondary btn-sm" onclick='showEditDestModal(${d.id}, ${JSON.stringify(d.name)}, ${JSON.stringify(d.type)}, ${JSON.stringify(d.config)})'>Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteDestination(${d.id}, '${esc(d.name)}')">Delete</button>
        <span id="dest-test-${d.id}" class="text-sm" style="margin-left:6px"></span>
      </td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="flex justify-between items-center mb-4">
      <div class="page-title" style="margin-bottom:0">Destinations</div>
      <button class="btn btn-primary" onclick="showAddDestModal()">+ Add Destination</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Created</th><th>Actions</th></tr></thead>
        <tbody>
          ${rows || '<tr><td colspan="4" class="text-secondary" style="text-align:center;padding:24px">No destinations yet.</td></tr>'}
        </tbody>
      </table>
    </div>
    <div id="dest-modal-container"></div>
  `;
}

async function deleteDestination(id, name) {
  if (!confirm(`Delete destination "${name}"? Jobs using this destination will lose their target.`)) return;
  try {
    await api('DELETE', `/destinations/${id}`);
    navigate('destinations');
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

function showAddDestModal() {
  const modalHtml = `
    <div class="modal-overlay" id="dest-modal-overlay">
      <div class="modal">
        <button class="modal-close" onclick="closeModal('dest-modal-overlay')">✕</button>
        <div class="modal-title">Add Destination</div>
        <div id="dest-modal-error"></div>

        <div class="form-group">
          <label>Name</label>
          <input class="form-control" id="dm-name" placeholder="My NAS Backup" />
        </div>

        <div class="form-group">
          <label>Type</label>
          <select class="form-control" id="dm-type" onchange="renderDestFields()">
            <option value="b2">Backblaze B2</option>
            <option value="smb">SMB / NAS</option>
            <option value="sftp">SFTP</option>
            <option value="local">Local Path</option>
          </select>
        </div>

        <div id="dm-fields"></div>

        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="closeModal('dest-modal-overlay')">Cancel</button>
          <button class="btn btn-primary" onclick="submitAddDest()">Add Destination</button>
        </div>
      </div>
    </div>
  `;
  el('dest-modal-container').innerHTML = modalHtml;
  renderDestFields();
}

function renderDestFields() {
  const type = el('dm-type').value;
  const container = el('dm-fields');

  const fields = {
    b2: `
      <div class="form-group"><label>Account ID</label><input class="form-control" id="dm-b2-account" placeholder="0023abc..." /></div>
      <div class="form-group"><label>Application Key</label><input class="form-control" id="dm-b2-key" type="password" /></div>
      <div class="form-group"><label>Bucket Name</label><input class="form-control" id="dm-b2-bucket" placeholder="my-backups" /></div>
      <div class="form-group"><label>Path (inside bucket)</label><input class="form-control" id="dm-b2-path" placeholder="baumlabbackup/" /></div>
    `,
    smb: `
      <div class="form-group"><label>Host</label><input class="form-control" id="dm-smb-host" placeholder="192.168.1.10" /></div>
      <div class="form-group"><label>Username</label><input class="form-control" id="dm-smb-user" /></div>
      <div class="form-group"><label>Password</label><input class="form-control" id="dm-smb-pass" type="password" /></div>
      <div class="form-group"><label>Domain (optional)</label><input class="form-control" id="dm-smb-domain" placeholder="WORKGROUP" /></div>
      <div class="form-group">
        <label>Path — start with the share name: <code>ShareName/subfolder</code></label>
        <input class="form-control" id="dm-smb-path" placeholder="Backups/LabBackup" />
        <div class="text-sm text-secondary" style="margin-top:4px">e.g. \\\\192.168.1.10\Backups\LabBackup → enter <strong>Backups/LabBackup</strong></div>
      </div>
    `,
    sftp: `
      <div class="form-group"><label>Host</label><input class="form-control" id="dm-sftp-host" /></div>
      <div class="form-group"><label>Port</label><input class="form-control" id="dm-sftp-port" type="number" value="22" /></div>
      <div class="form-group"><label>Username</label><input class="form-control" id="dm-sftp-user" /></div>
      <div class="form-group"><label>Password</label><input class="form-control" id="dm-sftp-pass" type="password" /></div>
      <div class="form-group"><label>Path</label><input class="form-control" id="dm-sftp-path" placeholder="/backups/" /></div>
    `,
    local: `
      <div class="form-group"><label>Local Path (absolute path inside container)</label><input class="form-control" id="dm-local-path" placeholder="/mnt/nas/backups" /></div>
    `,
  };

  container.innerHTML = fields[type] || '';
}

async function submitAddDest() {
  el('dest-modal-error').innerHTML = '';
  try {
    const name = el('dm-name').value.trim();
    if (!name) throw new Error('Name is required');
    const type = el('dm-type').value;

    let config = {};
    if (type === 'b2') {
      config = {
        account_id: el('dm-b2-account').value.trim(),
        application_key: el('dm-b2-key').value,
        bucket: el('dm-b2-bucket').value.trim(),
        path: el('dm-b2-path').value.trim(),
      };
    } else if (type === 'smb') {
      config = {
        host: el('dm-smb-host').value.trim(),
        user: el('dm-smb-user').value.trim(),
        password: el('dm-smb-pass').value,
        domain: el('dm-smb-domain').value.trim(),
        path: el('dm-smb-path').value.trim(),
      };
    } else if (type === 'sftp') {
      config = {
        host: el('dm-sftp-host').value.trim(),
        port: parseInt(el('dm-sftp-port').value) || 22,
        user: el('dm-sftp-user').value.trim(),
        password: el('dm-sftp-pass').value,
        path: el('dm-sftp-path').value.trim(),
      };
    } else if (type === 'local') {
      config = { path: el('dm-local-path').value.trim() };
    }

    await api('POST', '/destinations', { name, type, config });
    closeModal('dest-modal-overlay');
    navigate('destinations');
  } catch (e) {
    el('dest-modal-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

function showEditDestModal(id, name, type, config) {
  const modalHtml = `
    <div class="modal-overlay" id="dest-modal-overlay">
      <div class="modal">
        <button class="modal-close" onclick="closeModal('dest-modal-overlay')">✕</button>
        <div class="modal-title">Edit Destination</div>
        <div id="dest-modal-error"></div>

        <div class="form-group">
          <label>Name</label>
          <input class="form-control" id="em-name" value="${esc(name)}" placeholder="My NAS Backup" />
        </div>

        <div class="form-group">
          <label>Type</label>
          <select class="form-control" id="em-type" onchange="renderEditDestFields(el('em-type').value, {})">
            <option value="b2"  ${type==='b2'   ? 'selected':''}>Backblaze B2</option>
            <option value="smb" ${type==='smb'  ? 'selected':''}>SMB / NAS</option>
            <option value="sftp"${type==='sftp' ? 'selected':''}>SFTP</option>
            <option value="local"${type==='local'? 'selected':''}>Local Path</option>
          </select>
        </div>

        <div id="em-fields"></div>

        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="closeModal('dest-modal-overlay')">Cancel</button>
          <button class="btn btn-primary" id="btn-save-dest" onclick="submitEditDest(${id})">Save Changes</button>
        </div>
      </div>
    </div>
  `;
  el('dest-modal-container').innerHTML = modalHtml;
  renderEditDestFields(type, config);
}

function renderEditDestFields(type, config) {
  const v = (key, fallback = '') => esc(config[key] != null ? config[key] : fallback);
  const sensitive = '*** (unchanged)';
  const isSensitive = val => val === '***';

  const fields = {
    b2: `
      <div class="form-group"><label>Account ID</label><input class="form-control" id="em-b2-account" value="${v('account_id')}" /></div>
      <div class="form-group"><label>Application Key</label><input class="form-control" id="em-b2-key" type="password" placeholder="${isSensitive(config.application_key) ? sensitive : ''}" /></div>
      <div class="form-group"><label>Bucket Name</label><input class="form-control" id="em-b2-bucket" value="${v('bucket')}" /></div>
      <div class="form-group"><label>Path (inside bucket)</label><input class="form-control" id="em-b2-path" value="${v('path')}" /></div>
    `,
    smb: `
      <div class="form-group"><label>Host</label><input class="form-control" id="em-smb-host" value="${v('host')}" /></div>
      <div class="form-group"><label>Username</label><input class="form-control" id="em-smb-user" value="${v('user')}" /></div>
      <div class="form-group"><label>Password</label><input class="form-control" id="em-smb-pass" type="password" placeholder="${isSensitive(config.password) ? sensitive : ''}" /></div>
      <div class="form-group"><label>Domain (optional)</label><input class="form-control" id="em-smb-domain" value="${v('domain')}" /></div>
      <div class="form-group">
        <label>Path — start with the share name: <code>ShareName/subfolder</code></label>
        <input class="form-control" id="em-smb-path" value="${v('path')}" placeholder="Backups/LabBackup" />
        <div class="text-sm text-secondary" style="margin-top:4px">e.g. \\\\${v('host') || '192.168.1.10'}\\Backups\\LabBackup → enter <strong>Backups/LabBackup</strong></div>
      </div>
    `,
    sftp: `
      <div class="form-group"><label>Host</label><input class="form-control" id="em-sftp-host" value="${v('host')}" /></div>
      <div class="form-group"><label>Port</label><input class="form-control" id="em-sftp-port" type="number" value="${v('port', '22')}" /></div>
      <div class="form-group"><label>Username</label><input class="form-control" id="em-sftp-user" value="${v('user')}" /></div>
      <div class="form-group"><label>Password</label><input class="form-control" id="em-sftp-pass" type="password" placeholder="${isSensitive(config.password) ? sensitive : ''}" /></div>
      <div class="form-group"><label>Path</label><input class="form-control" id="em-sftp-path" value="${v('path')}" /></div>
    `,
    local: `
      <div class="form-group"><label>Local Path</label><input class="form-control" id="em-local-path" value="${v('path')}" /></div>
    `,
  };

  el('em-fields').innerHTML = fields[type] || '';
}

async function submitEditDest(id) {
  el('dest-modal-error').innerHTML = '';
  try {
    const name = el('em-name').value.trim();
    if (!name) throw new Error('Name is required');
    const type = el('em-type').value;

    // Empty password fields mean "keep existing" — the backend handles "" as unchanged
    let config = {};
    if (type === 'b2') {
      config = {
        account_id: el('em-b2-account').value.trim(),
        application_key: el('em-b2-key').value,
        bucket: el('em-b2-bucket').value.trim(),
        path: el('em-b2-path').value.trim(),
      };
    } else if (type === 'smb') {
      config = {
        host: el('em-smb-host').value.trim(),
        user: el('em-smb-user').value.trim(),
        password: el('em-smb-pass').value,
        domain: el('em-smb-domain').value.trim(),
        path: el('em-smb-path').value.trim(),
      };
    } else if (type === 'sftp') {
      config = {
        host: el('em-sftp-host').value.trim(),
        port: parseInt(el('em-sftp-port').value) || 22,
        user: el('em-sftp-user').value.trim(),
        password: el('em-sftp-pass').value,
        path: el('em-sftp-path').value.trim(),
      };
    } else if (type === 'local') {
      config = { path: el('em-local-path').value.trim() };
    }

    el('btn-save-dest').disabled = true;
    await api('PUT', `/destinations/${id}`, { name, type, config });
    closeModal('dest-modal-overlay');
    navigate('destinations');
  } catch (e) {
    el('btn-save-dest').disabled = false;
    el('dest-modal-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

async function testDestConnection(id) {
  const span = el(`dest-test-${id}`);
  if (span) span.innerHTML = '<span style="color:var(--text-muted)">Testing…</span>';
  try {
    const res = await api('POST', `/destinations/${id}/test`);
    if (!res) return;
    if (span) {
      span.innerHTML = res.ok
        ? '<span style="color:#4ade80">✓ Connected</span>'
        : `<span style="color:var(--danger)" title="${esc(res.message)}">✗ Failed</span>`;
    }
  } catch (e) {
    if (span) span.innerHTML = `<span style="color:var(--danger)" title="${esc(e.message)}">✗ Error</span>`;
  }
}

// ============================================================
// HISTORY PAGE
// ============================================================

async function loadHistory(container, page = 1) {
  container.innerHTML = `<div class="page-title">Run History</div><p class="text-secondary">Loading...</p>`;
  try {
    const data = await api('GET', `/status/runs?page=${page}&page_size=20`);
    if (!data) return;
    renderHistory(container, data, page);
  } catch (e) {
    container.innerHTML = `<div class="page-title">Run History</div><div class="form-error">${esc(e.message)}</div>`;
  }
}

function renderHistory(container, data, currentPage) {
  const rows = (data.items || []).map(run => `
    <tr>
      <td>${esc(run.job_name)}</td>
      <td>${statusBadge(run.status)}</td>
      <td>${formatDate(run.started_at)}</td>
      <td>${formatDuration(run.started_at, run.completed_at)}</td>
      <td>${formatBytes(run.size_bytes)}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="viewRunLog(${run.id})">View Log</button>
      </td>
    </tr>
  `).join('');

  const totalPages = Math.ceil(data.total / data.page_size);
  const paginationHtml = totalPages > 1 ? `
    <div class="pagination">
      <span>Page ${currentPage} of ${totalPages} (${data.total} total)</span>
      ${currentPage > 1 ? `<button class="btn btn-secondary btn-sm" onclick="loadHistory(el('main-content'), ${currentPage - 1})">← Prev</button>` : ''}
      ${currentPage < totalPages ? `<button class="btn btn-secondary btn-sm" onclick="loadHistory(el('main-content'), ${currentPage + 1})">Next →</button>` : ''}
    </div>
  ` : '';

  container.innerHTML = `
    <div class="page-title">Run History</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Job</th><th>Status</th><th>Started</th><th>Duration</th><th>Size</th><th>Log</th>
        </tr></thead>
        <tbody>
          ${rows || '<tr><td colspan="6" class="text-secondary" style="text-align:center;padding:24px">No runs yet</td></tr>'}
        </tbody>
      </table>
    </div>
    ${paginationHtml}
    <div id="log-modal-container"></div>
  `;
}

async function viewRunLog(runId) {
  try {
    const run = await api('GET', `/status/runs/${runId}`);
    if (!run) return;

    const logHtml = run.log_lines.map(line => {
      const cls = line.includes('ERROR') ? 'log-line-error'
        : line.includes('Warning') ? 'log-line-warn'
        : line.includes('success') || line.includes('complete') ? 'log-line-ok' : '';
      return `<div class="${cls}">${esc(line)}</div>`;
    }).join('');

    const mc = el('main-content');
    const logContainer = mc.querySelector('#log-modal-container') || mc;

    const modalHtml = `
      <div class="modal-overlay" id="log-modal-overlay">
        <div class="modal" style="max-width:800px">
          <button class="modal-close" onclick="closeModal('log-modal-overlay')">✕</button>
          <div class="modal-title">Run Log: ${esc(run.job_name)}</div>
          <div class="flex gap-3 mb-4 text-sm text-secondary">
            <span>${statusBadge(run.status)}</span>
            <span>Started: ${formatDate(run.started_at)}</span>
            <span>Duration: ${formatDuration(run.started_at, run.completed_at)}</span>
            <span>Size: ${formatBytes(run.size_bytes)}</span>
          </div>
          ${run.error ? `<div class="form-error mb-4">${esc(run.error)}</div>` : ''}
          <div class="log-viewer">${logHtml || '<span class="text-secondary">No log lines</span>'}</div>
          <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal('log-modal-overlay')">Close</button>
          </div>
        </div>
      </div>
    `;

    const existingContainer = mc.querySelector('#log-modal-container');
    if (existingContainer) {
      existingContainer.innerHTML = modalHtml;
    } else {
      const div = document.createElement('div');
      div.id = 'log-modal-container';
      div.innerHTML = modalHtml;
      mc.appendChild(div);
    }
  } catch (e) {
    alert('Failed to load log: ' + e.message);
  }
}

// ============================================================
// SETTINGS PAGE
// ============================================================

async function loadSettings(container) {
  container.innerHTML = `<div class="page-title">Settings</div><p class="text-secondary">Loading...</p>`;
  try {
    const user = await api('GET', '/auth/me');
    if (!user) return;
    state.user = user;
    renderSettings(container, user);
  } catch (e) {
    container.innerHTML = `<div class="page-title">Settings</div><div class="form-error">${esc(e.message)}</div>`;
  }
}

function renderSettings(container, user) {
  container.innerHTML = `
    <div class="page-title">Settings</div>

    <div class="settings-section">
      <h2>Change Password</h2>
      <div id="pw-error"></div>
      <div id="pw-success" style="display:none" class="form-hint" style="color:var(--success)">Password changed successfully!</div>
      <div class="form-group">
        <label>Current Password</label>
        <input class="form-control" id="pw-current" type="password" />
      </div>
      <div class="form-group">
        <label>New Password</label>
        <input class="form-control" id="pw-new" type="password" />
      </div>
      <div class="form-group">
        <label>Confirm New Password</label>
        <input class="form-control" id="pw-confirm" type="password" />
      </div>
      <button class="btn btn-primary" onclick="submitChangePassword()">Change Password</button>
    </div>

    <div class="settings-section">
      <h2>Two-Factor Authentication (TOTP)</h2>
      <div id="totp-status-area">
        ${renderTotpStatus(user)}
      </div>
    </div>
  `;
}

function renderTotpStatus(user) {
  if (user.totp_enabled) {
    return `
      <p class="mb-4"><span class="badge badge-success">TOTP Enabled</span> Your account is protected with an authenticator app.</p>
      <div id="totp-disable-area">
        <p class="text-secondary text-sm mb-4">To disable, enter your current authenticator code:</p>
        <div class="form-group"><input class="form-control" id="totp-disable-code" placeholder="6-digit code" inputmode="numeric" maxlength="6" style="max-width:200px" /></div>
        <div id="totp-disable-error"></div>
        <button class="btn btn-danger" onclick="submitDisableTotp()">Disable TOTP</button>
      </div>
    `;
  } else {
    return `
      <p class="text-secondary mb-4">TOTP is not enabled. Add an extra layer of security with an authenticator app.</p>
      <button class="btn btn-primary" onclick="startTotpSetup()">Enable TOTP</button>
      <div id="totp-setup-area" style="display:none"></div>
    `;
  }
}

async function submitChangePassword() {
  el('pw-error').innerHTML = '';
  const current = el('pw-current').value;
  const newPw = el('pw-new').value;
  const confirm = el('pw-confirm').value;
  if (newPw !== confirm) {
    el('pw-error').innerHTML = '<div class="form-error">Passwords do not match</div>';
    return;
  }
  try {
    await api('POST', '/auth/change-password', { current_password: current, new_password: newPw });
    el('pw-current').value = '';
    el('pw-new').value = '';
    el('pw-confirm').value = '';
    const successEl = el('pw-success');
    if (successEl) { successEl.style.display = 'block'; successEl.style.color = 'var(--success)'; }
  } catch (e) {
    el('pw-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

async function startTotpSetup() {
  try {
    const data = await api('POST', '/auth/totp/setup');
    const area = el('totp-setup-area');
    area.style.display = 'block';
    area.innerHTML = `
      <div class="qr-wrapper mt-4">
        <img src="data:image/png;base64,${data.qr_code}" alt="TOTP QR Code" />
        <div class="text-secondary text-sm">Scan with your authenticator app</div>
        <div class="secret-text">${esc(data.secret)}</div>
      </div>
      <p class="text-secondary text-sm mb-4">Enter the 6-digit code from your app to confirm:</p>
      <div class="form-group"><input class="form-control" id="totp-confirm-code" placeholder="6-digit code" inputmode="numeric" maxlength="6" style="max-width:200px" /></div>
      <div id="totp-confirm-error"></div>
      <button class="btn btn-primary" onclick="submitConfirmTotp()">Confirm & Enable</button>
    `;
  } catch (e) {
    alert('Failed to start TOTP setup: ' + e.message);
  }
}

async function submitConfirmTotp() {
  const code = el('totp-confirm-code').value.trim();
  try {
    await api('POST', '/auth/totp/confirm', { code });
    if (state.user) state.user.totp_enabled = true;
    el('totp-status-area').innerHTML = renderTotpStatus({ totp_enabled: true });
  } catch (e) {
    el('totp-confirm-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

async function submitDisableTotp() {
  const code = el('totp-disable-code').value.trim();
  try {
    await api('POST', '/auth/totp/disable', { code });
    if (state.user) state.user.totp_enabled = false;
    el('totp-status-area').innerHTML = renderTotpStatus({ totp_enabled: false });
  } catch (e) {
    el('totp-disable-error').innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

// ============================================================
// MODAL UTILITY
// ============================================================

let _stackLogPollTimer = null;

/**
 * showModal — creates a dynamic full-screen overlay modal used by the Stacks page.
 * The existing Jobs/Destinations pages use inline CSS-class modals (closeModal(id)).
 */
function showModal(title, bodyHtml) {
  let overlay = el('modal-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;display:flex;align-items:center;justify-content:center';
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = `
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:24px;width:min(720px,95vw);max-height:90vh;overflow-y:auto">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h2 style="margin:0">${esc(title)}</h2>
        <button class="btn btn-secondary btn-sm" onclick="closeModal()">✕</button>
      </div>
      <div id="modal-body">${bodyHtml}</div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
}

function setModalBody(html) {
  const b = el('modal-body');
  if (b) b.innerHTML = html;
}

function closeModal(overlayId) {
  if (overlayId) {
    const overlay = el(overlayId);
    if (overlay) overlay.remove();
  } else {
    // Dynamic stack modal
    if (_stackLogPollTimer) { clearInterval(_stackLogPollTimer); _stackLogPollTimer = null; }
    const o = el('modal-overlay');
    if (o) o.remove();
  }
}

// Close modal on overlay click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.remove();
  }
});

// ============================================================
// INIT
// ============================================================

renderApp();
