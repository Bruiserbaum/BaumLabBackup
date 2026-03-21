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
function renderApp() {
  const app = el('app');
  if (!state.token) {
    // Fetch OIDC config once, then render login page
    fetch('/api/auth/config')
      .then(r => r.json())
      .then(d => { state.oidcEnabled = !!d.oidc_enabled; })
      .catch(() => {})
      .finally(() => {
        app.innerHTML = renderLoginPage();
        bindLoginPage();
      });
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
        <button class="btn btn-danger btn-sm" onclick="deleteDestination(${d.id}, '${esc(d.name)}')">Delete</button>
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
      <div class="form-group"><label>Share Name</label><input class="form-control" id="dm-smb-share" placeholder="Backups" /></div>
      <div class="form-group"><label>Username</label><input class="form-control" id="dm-smb-user" /></div>
      <div class="form-group"><label>Password</label><input class="form-control" id="dm-smb-pass" type="password" /></div>
      <div class="form-group"><label>Domain (optional)</label><input class="form-control" id="dm-smb-domain" placeholder="WORKGROUP" /></div>
      <div class="form-group"><label>Path (inside share)</label><input class="form-control" id="dm-smb-path" placeholder="baumlabbackup/" /></div>
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
        share: el('dm-smb-share').value.trim(),
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

function closeModal(overlayId) {
  const overlay = el(overlayId);
  if (overlay) overlay.remove();
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
