// ═══════════════════════════════════════════════════════════════════
//  State
// ═══════════════════════════════════════════════════════════════════
let _token = localStorage.getItem('tga_token');
let _phoneCodeHash = '';
let _activeTab = 'userbot';

// ═══════════════════════════════════════════════════════════════════
//  API helpers
// ═══════════════════════════════════════════════════════════════════
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (_token) opts.headers['Authorization'] = `Bearer ${_token}`;
  if (body !== undefined) opts.body = JSON.stringify(body);

  const r = await fetch('/api' + path, opts);
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

// ═══════════════════════════════════════════════════════════════════
//  Bootstrap
// ═══════════════════════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', () => {
  if (_token) {
    showApp();
  } else {
    showAuth();
  }
});

function showAuth() {
  document.getElementById('auth-screen').style.display = '';
  document.getElementById('app-screen').style.display = 'none';
  document.getElementById('user-info').style.display = 'none';
  injectTelegramWidget();
}

function showApp() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-screen').style.display = '';
  document.getElementById('user-info').style.display = 'flex';
  loadTab(_activeTab);
  loadStatus();
}

function logout() {
  stopQrPolling();
  localStorage.removeItem('tga_token');
  localStorage.removeItem('tga_user');
  _token = null;
  showAuth();
}

// ═══════════════════════════════════════════════════════════════════
//  Telegram Login Widget
// ═══════════════════════════════════════════════════════════════════
function injectTelegramWidget() {
  const container = document.getElementById('tg-widget-container');
  container.innerHTML = '';
  const s = document.createElement('script');
  s.async = true;
  s.src = 'https://telegram.org/js/telegram-widget.js?22';
  s.setAttribute('data-telegram-login', _getBotUsername());
  s.setAttribute('data-size', 'large');
  s.setAttribute('data-onauth', 'onTelegramAuth(user)');
  s.setAttribute('data-request-access', 'write');
  container.appendChild(s);
}

function _getBotUsername() {
  // Bot username is set via meta tag or window variable during server-side rendering.
  // Fallback: read from <meta name="tg-bot"> or window.TG_BOT_USERNAME
  return window.TG_BOT_USERNAME || document.querySelector('meta[name="tg-bot"]')?.content || 'YOUR_BOT_USERNAME';
}

window.onTelegramAuth = async function(user) {
  try {
    const data = await api('POST', '/auth/telegram', user);
    _token = data.token;
    localStorage.setItem('tga_token', _token);
    localStorage.setItem('tga_user', data.first_name);
    document.getElementById('user-name').textContent = data.first_name;
    showApp();
  } catch(e) {
    alert('Помилка авторизації: ' + e.message);
  }
};

// ═══════════════════════════════════════════════════════════════════
//  Tabs
// ═══════════════════════════════════════════════════════════════════
function switchTab(name) {
  _activeTab = name;
  document.querySelectorAll('.tab-btn').forEach((b) => {
    b.classList.toggle('active', b.getAttribute('onclick').includes(`'${name}'`));
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  loadTab(name);
}

function loadTab(name) {
  if (name === 'userbot') loadStatus();
  if (name === 'sources') loadSources();
  if (name === 'destination') loadDestination();
  if (name === 'filters') loadKeywords();
}

// ═══════════════════════════════════════════════════════════════════
//  Status
// ═══════════════════════════════════════════════════════════════════
async function loadStatus() {
  try {
    const data = await api('GET', '/status');
    const dot = document.getElementById('status-dot');
    const notice = document.getElementById('userbot-status-notice');
    const userName = localStorage.getItem('tga_user') || '';
    document.getElementById('user-name').textContent = userName;

    if (data.userbot_connected) {
      dot.classList.add('connected');
      notice.className = 'notice ok';
      notice.textContent = '✅ Userbot активний і підключений';
      document.getElementById('phone-form').style.display = 'none';
    } else if (data.has_session) {
      dot.classList.remove('connected');
      notice.className = 'notice warn';
      notice.textContent = '⚠️ Сесія є в БД, але клієнт не підключений. Спробуйте переавторизуватись.';
    } else {
      dot.classList.remove('connected');
      notice.className = 'notice warn';
      notice.textContent = '🔐 Userbot не авторизований. Введіть номер телефону нижче.';
    }
  } catch(e) {
    if (e.message.includes('401')) { logout(); return; }
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Auth method toggle (Phone vs QR)
// ═══════════════════════════════════════════════════════════════════
function showAuthMethod(method) {
  const isPhone = method === 'phone';
  document.getElementById('auth-phone-section').style.display = isPhone ? '' : 'none';
  document.getElementById('auth-qr-section').style.display = isPhone ? 'none' : '';
  document.getElementById('toggle-phone').className = isPhone ? 'btn btn-blue' : 'btn btn-ghost';
  document.getElementById('toggle-qr').className = isPhone ? 'btn btn-ghost' : 'btn btn-blue';
  if (!isPhone) stopQrPolling();
}

// ═══════════════════════════════════════════════════════════════════
//  Phone auth
// ═══════════════════════════════════════════════════════════════════
async function sendCode() {
  const phone = document.getElementById('phone-input').value.trim();
  if (!phone) return;
  const msg = document.getElementById('phone-msg');
  msg.innerHTML = '<span class="spinner"></span>';
  try {
    const data = await api('POST', '/auth/phone', { phone });
    _phoneCodeHash = data.phone_code_hash;
    document.getElementById('code-block').style.display = '';
    msg.innerHTML = '';
  } catch(e) {
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

async function confirmCode() {
  const phone = document.getElementById('phone-input').value.trim();
  const code = document.getElementById('code-input').value.trim();
  const msg = document.getElementById('phone-msg');
  msg.innerHTML = '<span class="spinner"></span>';
  try {
    await api('POST', '/auth/code', { phone, code, phone_code_hash: _phoneCodeHash });
    msg.innerHTML = '';
    document.getElementById('phone-form').style.display = 'none';
    loadStatus();
  } catch(e) {
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

// ═══════════════════════════════════════════════════════════════════
//  QR auth
// ═══════════════════════════════════════════════════════════════════
let _qrPollTimer = null;
let _qrToken = null;

function stopQrPolling() {
  if (_qrPollTimer) { clearInterval(_qrPollTimer); _qrPollTimer = null; }
}

async function startQrLogin() {
  stopQrPolling();
  const container = document.getElementById('qr-container');
  const msg = document.getElementById('qr-msg');
  container.innerHTML = '<span class="spinner"></span>';
  msg.innerHTML = '';
  try {
    const data = await api('POST', '/auth/qr-session', {});
    _qrToken = 'qr';
    container.innerHTML = `<img src="data:image/png;base64,${data.qr_image}" style="width:200px;height:200px;border-radius:8px" alt="QR code" />
      <div style="margin-top:8px"><button class="btn btn-ghost btn-sm" onclick="startQrLogin()">Оновити</button></div>`;
    msg.innerHTML = '<div class="notice warn" style="margin-top:8px">Очікуємо сканування…</div>';
    _qrPollTimer = setInterval(pollQrStatus, 3000);
  } catch(e) {
    container.innerHTML = '<button class="btn btn-blue" onclick="startQrLogin()">Отримати QR-код</button>';
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

async function pollQrStatus() {
  try {
    const data = await api('POST', '/auth/qr-status', { token: _qrToken || 'qr' });
    if (data.status === 'authorized') {
      stopQrPolling();
      document.getElementById('qr-msg').innerHTML = '<div class="notice ok" style="margin-top:8px">✅ Авторизовано! Підключення…</div>';
      document.getElementById('qr-container').innerHTML = '';
      setTimeout(() => {
        document.getElementById('phone-form').style.display = 'none';
        loadStatus();
      }, 1000);
    }
  } catch(e) {
    stopQrPolling();
    document.getElementById('qr-msg').innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
    document.getElementById('qr-container').innerHTML = '<button class="btn btn-blue" onclick="startQrLogin()">Спробувати знову</button>';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Sources
// ═══════════════════════════════════════════════════════════════════
async function loadSources() {
  const el = document.getElementById('sources-list');
  el.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
  try {
    const sources = await api('GET', '/sources');
    if (!sources.length) {
      el.innerHTML = '<div class="empty">Немає доданих груп</div>';
      return;
    }
    el.innerHTML = sources.map(s => `
      <div class="list-item" id="src-${s.id}">
        <div class="item-info">
          <div class="item-title">${esc(s.chat_title)}</div>
          <div class="item-sub">${s.chat_username ? '@' + esc(s.chat_username) : 'ID: ' + s.chat_id}</div>
        </div>
        <label class="toggle" title="${s.is_active ? 'Вимкнути' : 'Увімкнути'}">
          <input type="checkbox" ${s.is_active ? 'checked' : ''} onchange="toggleSource(${s.id}, this)">
          <span class="toggle-slider"></span>
        </label>
        <button class="btn btn-ghost btn-sm" onclick="deleteSource(${s.id})">✕</button>
      </div>
    `).join('');
  } catch(e) {
    el.innerHTML = `<div class="notice err">${e.message}</div>`;
  }
}

async function addSource() {
  const val = document.getElementById('source-input').value.trim();
  if (!val) return;
  const msg = document.getElementById('source-msg');
  msg.innerHTML = '<span class="spinner"></span>';
  try {
    await api('POST', '/sources', { identifier: val });
    document.getElementById('source-input').value = '';
    msg.innerHTML = '';
    loadSources();
  } catch(e) {
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

async function deleteSource(id) {
  if (!confirm('Видалити це джерело?')) return;
  try {
    await api('DELETE', `/sources/${id}`);
    loadSources();
  } catch(e) {
    alert(e.message);
  }
}

async function toggleSource(id, checkbox) {
  try {
    await api('POST', `/sources/${id}/toggle`);
  } catch(e) {
    checkbox.checked = !checkbox.checked;
    alert(e.message);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Destination
// ═══════════════════════════════════════════════════════════════════
async function loadDestination() {
  const el = document.getElementById('dest-current');
  try {
    const data = await api('GET', '/destination');
    if (data) {
      el.className = 'notice ok';
      el.textContent = `📢 ${data.chat_title} (ID: ${data.chat_id})`;
    } else {
      el.className = 'notice warn';
      el.textContent = 'Канал не встановлено';
    }
  } catch(e) {
    el.className = 'notice err';
    el.textContent = e.message;
  }
}

async function setDestination() {
  const val = document.getElementById('dest-input').value.trim();
  if (!val) return;
  const msg = document.getElementById('dest-msg');
  msg.innerHTML = '<span class="spinner"></span>';
  try {
    await api('POST', '/destination', { identifier: val });
    document.getElementById('dest-input').value = '';
    msg.innerHTML = '';
    loadDestination();
  } catch(e) {
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Keywords
// ═══════════════════════════════════════════════════════════════════
let _keywords = [];

async function loadKeywords() {
  try {
    _keywords = await api('GET', '/keywords');
    renderKeywords();
  } catch(e) {
    document.getElementById('kw-msg').innerHTML = `<div class="notice err">${e.message}</div>`;
  }
}

function renderKeywords() {
  const plus = _keywords.filter(k => k.type === 'PLUS');
  const minus = _keywords.filter(k => k.type === 'MINUS');
  document.getElementById('plus-list').innerHTML =
    plus.length ? plus.map(k => kwPill(k)).join('') : '<span style="color:var(--text-muted);font-size:13px">Немає</span>';
  document.getElementById('minus-list').innerHTML =
    minus.length ? minus.map(k => kwPill(k)).join('') : '<span style="color:var(--text-muted);font-size:13px">Немає</span>';
}

function kwPill(k) {
  const cls = k.type === 'PLUS' ? 'plus' : 'minus';
  return `<span class="kw-pill ${cls}">${esc(k.word)}<button onclick="deleteKeyword(${k.id})" title="Видалити">×</button></span>`;
}

async function addKeyword() {
  const word = document.getElementById('kw-input').value.trim();
  const type = document.getElementById('kw-type').value;
  const msg = document.getElementById('kw-msg');
  if (!word) return;
  msg.innerHTML = '<span class="spinner"></span>';
  try {
    await api('POST', '/keywords', { word, type });
    document.getElementById('kw-input').value = '';
    msg.innerHTML = '';
    loadKeywords();
  } catch(e) {
    msg.innerHTML = `<div class="notice err" style="margin-top:8px">${e.message}</div>`;
  }
}

async function deleteKeyword(id) {
  try {
    await api('DELETE', `/keywords/${id}`);
    loadKeywords();
  } catch(e) {
    alert(e.message);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Utils
// ═══════════════════════════════════════════════════════════════════
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
