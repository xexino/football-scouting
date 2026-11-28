/* Raja Scout Intelligence — single-page frontend (no build step, no external dependencies). */
(() => {
  'use strict';

  // ------------------------------------------------------------------ state & utils
  const S = { token: null, user: null, meta: null, compare: new Set() };
  try { S.token = sessionStorage.getItem('rsi_token'); const c = JSON.parse(sessionStorage.getItem('rsi_compare') || '[]'); c.forEach(i => S.compare.add(i)); } catch (_) { /* storage unavailable */ }

  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = s => new Raw(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const val = v => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(val).join('') : (v === null || v === undefined || v === false) ? '' : esc(v);
  const h = (strings, ...vals) => raw(strings.reduce((acc, s, i) => acc + s + (i < vals.length ? val(vals[i]) : ''), ''));
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const can = p => !!S.user && S.user.permissions.includes(p);
  const setToken = t => { S.token = t; try { sessionStorage.setItem('rsi_token', t); } catch (_) { } };
  const saveCompare = () => { try { sessionStorage.setItem('rsi_compare', JSON.stringify([...S.compare])); } catch (_) { } };

  const currency = () => (S.user && S.user.organization && S.user.organization.currency) || 'EUR';
  const fmtMoney = v => {
    if (v == null) return '—';
    try { return new Intl.NumberFormat('en', { style: 'currency', currency: currency(), notation: 'compact', maximumFractionDigits: 2 }).format(v); }
    catch (_) { return `${v} ${currency()}`; }
  };
  const fmtDate = v => v ? new Date(v).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
  const fmtDateTime = v => v ? new Date(v).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
  const fmtNum = (v, d = 2) => v == null ? '—' : (Number.isInteger(v) ? String(v) : Number(v).toFixed(d));
  const label = s => s ? String(s).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '—';
  const ordinal = n => { n = Math.round(n); const s = (n % 100 >= 10 && n % 100 <= 20) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'); return n + s; };
  const tsFmt = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const parseTs = str => { const p = String(str).trim().split(':').map(Number); if (p.some(isNaN)) return null; return p.length === 1 ? p[0] : p.length === 2 ? p[0] * 60 + p[1] : p[0] * 3600 + p[1] * 60 + p[2]; };

  const STAGE_COLORS = { identified: 'b-grey', under_observation: 'b-blue', data_analysis: 'b-purple', video_analysis: 'b-purple', shortlisted: 'b-green', live_scouting: 'b-green', approved: 'b-gold', negotiation: 'b-gold', signed: 'b-gold', rejected: 'b-red' };
  const stageBadge = s => s ? h`<span class="badge ${STAGE_COLORS[s] || 'b-grey'}">${label(s)}</span>` : h`<span class="faint">—</span>`;
  const posBadge = p => h`<span class="pos">${p}</span>`;
  const fictBadge = f => f ? h`<span class="badge b-amber" title="Fictional sample data — demonstration only">FICTIONAL</span>` : '';
  const prioBadge = p => h`<span class="badge ${p === 'high' ? 'b-gold' : p === 'medium' ? 'b-blue' : 'b-grey'}">${label(p)}</span>`;
  const EV = {
    verified_data: ['DATA', 'b-green'], fictional_sample: ['FICTIONAL', 'b-amber'], scout_opinion: ['SCOUT', 'b-blue'],
    model_estimate: ['MODEL', 'b-purple'], insufficient_evidence: ['NO EVIDENCE', 'b-grey'], scout_input_required: ['INPUT REQUIRED', 'b-red'],
  };
  const evBadge = t => h`<span class="badge ${(EV[t] || ['', 'b-grey'])[1]}">${(EV[t] || [t])[0]}</span>`;
  const availBadge = a => h`<span class="badge ${a === 'available' || a === 'transfer_listed' || a === 'free_agent' ? 'b-green' : a === 'contract_expiring' || a === 'loan_possible' ? 'b-gold' : a === 'not_available' ? 'b-red' : 'b-grey'}">${label(a)}</span>`;

  function toast(msg, err = false) {
    if (!msg) return;
    const t = document.createElement('div');
    t.className = 'toast' + (err ? ' err' : '');
    t.textContent = msg;
    $('#toast-root').appendChild(t);
    setTimeout(() => t.remove(), err ? 6000 : 3000);
  }

  // A view that finishes loading after the user has navigated elsewhere must not overwrite
  // the newer page: every request remembers the route it was issued under, and responses
  // arriving after a navigation abort the stale view (StaleView is swallowed by the router).
  class StaleView extends Error { constructor() { super(''); } }
  let routeSeq = 0;
  async function api(path, opts = {}) {
    const seq = routeSeq;
    const out = await apiRaw(path, opts);
    if (seq !== routeSeq) throw new StaleView();
    return out;
  }
  async function apiRaw(path, { method = 'GET', body, form, raw: rawResp } = {}) {
    const headers = {};
    if (S.token) headers.Authorization = 'Bearer ' + S.token;
    let payload;
    if (form) payload = form;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const res = await fetch(path, { method, headers, body: payload });
    if (res.status === 401 && path !== '/api/auth/token') { logout(); throw new Error('Session expired — please log in again'); }
    if (rawResp) { if (!res.ok) throw new Error(`Request failed (${res.status})`); return res; }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
      throw new Error(msg || `Request failed (${res.status})`);
    }
    return data;
  }

  async function download(path, filename) {
    try {
      const res = await api(path, { raw: true });
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = filename; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { toast(e.message, true); }
  }

  function formData(form) {
    const out = {};
    for (const el of form.elements) {
      if (!el.name || el.disabled) continue;
      if (el.type === 'checkbox') { out[el.name] = el.checked; continue; }
      if (el.multiple) { out[el.name] = [...el.selectedOptions].map(o => o.value); continue; }
      let v = el.value.trim();
      if (v === '') { out[el.name] = null; continue; }
      if (el.type === 'number' || el.dataset.type === 'number') v = Number(v);
      out[el.name] = v;
    }
    return out;
  }
  const clean = o => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length)));

  // ------------------------------------------------------------------ modal
  function modal(title, body, { wide = false, onSubmit, submitLabel = 'Save', foot } = {}) {
    const root = $('#modal-root');
    root.innerHTML = h`<div class="modal-back"><form class="modal ${wide ? 'wide' : ''}" novalidate>
      <div class="modal-head"><h2>${title}</h2><button type="button" class="btn ghost sm" data-close aria-label="Close">✕</button></div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot">${foot || ''}<button type="button" class="btn" data-close>Cancel</button>${onSubmit ? h`<button class="btn primary" type="submit">${submitLabel}</button>` : ''}</div>
    </form></div>`.s;
    const form = $('form', root);
    const close = () => { root.innerHTML = ''; };
    $$('[data-close]', root).forEach(b => b.onclick = close);
    $('.modal-back', root).addEventListener('mousedown', e => { if (e.target.classList.contains('modal-back')) close(); });
    form.onsubmit = async e => {
      e.preventDefault();
      if (!onSubmit) return close();
      const btn = $('button[type=submit]', form); btn.disabled = true;
      try { const keep = await onSubmit(form); if (keep !== true) close(); } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
    };
    return { form, close, root };
  }

  // ------------------------------------------------------------------ charts (SVG)
  const PALETTE = ['#00c26e', '#d4af37', '#4ea1ff', '#e5484d', '#a78bfa'];
  function radar(axes, series, size = 380) {
    const pad = 80, cx = size / 2 + pad, cy = size / 2 + 10, r = size / 2 - 40, n = axes.length;
    if (n < 3) return h`<div class="empty">Not enough metrics for a radar chart.</div>`;
    const pt = (i, v) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; return [cx + Math.cos(a) * r * v / 100, cy + Math.sin(a) * r * v / 100]; };
    let g = '';
    [25, 50, 75, 100].forEach(lv => { g += `<polygon points="${axes.map((_, i) => pt(i, lv).join(',')).join(' ')}" fill="none" stroke="#1f4434" stroke-width="1"/>`; });
    axes.forEach((ax, i) => {
      const [x, y] = pt(i, 100); const [lx, ly] = pt(i, 122);
      g += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#1f4434"/>`;
      const anchor = lx < cx - 5 ? 'end' : lx > cx + 5 ? 'start' : 'middle';
      g += `<text x="${lx}" y="${ly}" font-size="10.5" text-anchor="${anchor}" dominant-baseline="middle">${esc(ax)}</text>`;
    });
    g += `<text x="${cx + 3}" y="${cy - r / 2}" font-size="9" fill="#5f8473">50</text>`;
    series.forEach((s, si) => {
      const c = s.color || PALETTE[si % PALETTE.length];
      const pts = s.values.map((v, i) => pt(i, v ?? 0));
      g += `<polygon points="${pts.map(p => p.join(',')).join(' ')}" fill="${c}" fill-opacity=".14" stroke="${c}" stroke-width="2"/>`;
      s.values.forEach((v, i) => { if (v == null) return; const [x, y] = pts[i]; g += `<circle cx="${x}" cy="${y}" r="3" fill="${c}"><title>${esc(s.label)} — ${esc(axes[i])}: ${ordinal(v)} pct</title></circle>`; });
    });
    const legend = series.map((s, si) => `<span><i style="background:${s.color || PALETTE[si % PALETTE.length]}"></i>${esc(s.label)}</span>`).join('');
    return raw(`<svg viewBox="0 0 ${size + pad * 2} ${size + 20}" width="100%" style="max-width:${size + pad * 2}px;display:block;margin:auto;overflow:visible" role="img" aria-label="Radar chart">${g}</svg><div class="chart-legend" style="justify-content:center">${legend}</div><p class="faint" style="text-align:center;font-size:11.5px;margin:6px 0 0">Axis = percentile vs. database position pool (missing metrics plotted at 0).</p>`);
  }

  function hbars(entries, { gold = false, fmt = v => v } = {}) {
    const max = Math.max(1, ...entries.map(e => e[1]));
    return raw(entries.map(([k, v]) => `<div class="bar-row"><span title="${esc(k)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(k)}</span><div class="bar-track"><div class="bar-fill ${gold ? 'gold' : ''}" style="width:${(v / max) * 100}%"></div></div><span class="num" style="text-align:right">${esc(fmt(v))}</span></div>`).join('') || '<div class="empty">No data</div>');
  }

  function weeklyChart(weeks) {
    const W = 640, H = 170, pad = 28, bw = (W - pad * 2) / weeks.length;
    const max = Math.max(1, ...weeks.map(w => w.match_reports + w.video_observations + w.pipeline_moves));
    let g = `<line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="#1f4434"/>`;
    weeks.forEach((w, i) => {
      let y = H - pad; const x = pad + i * bw + 4;
      [['match_reports', '#00c26e'], ['video_observations', '#4ea1ff'], ['pipeline_moves', '#d4af37']].forEach(([k, c]) => {
        const hgt = (w[k] / max) * (H - pad * 2); y -= hgt;
        if (hgt > 0) g += `<rect x="${x}" y="${y}" width="${bw - 8}" height="${hgt}" fill="${c}" rx="2"><title>${esc(label(k))}: ${w[k]} (week of ${w.week_start})</title></rect>`;
      });
      if (i % 2 === 0) g += `<text x="${x + (bw - 8) / 2}" y="${H - 10}" font-size="9" text-anchor="middle">${w.week_start.slice(5)}</text>`;
    });
    return raw(`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Weekly scouting activity">${g}</svg><div class="chart-legend"><span><i style="background:#00c26e"></i>Match reports</span><span><i style="background:#4ea1ff"></i>Video observations</span><span><i style="background:#d4af37"></i>Pipeline decisions</span></div>`);
  }

  const pctCell = p => p == null ? h`<span class="faint">n/a</span>` : h`<div class="pct-cell"><div class="bar-track"><div class="bar-fill ${p >= 70 ? 'gold' : ''}" style="width:${p}%"></div></div><span>${Math.round(p)}</span></div>`;

  // ------------------------------------------------------------------ shell
  const NOT_AFFILIATED = 'Raja Scout Intelligence is independent software. It is not affiliated with, endorsed or sponsored by Raja Club Athletic or any club using it.';
  const ICONS = {
    platform: '<path d="M4 4h16v4H4zm0 6h16v4H4zm0 6h16v4H4zM6 5.5h2v1H6zm0 6h2v1H6zm0 6h2v1H6z"/>',
    organization: '<path d="M12 7V3H2v18h20V7H12zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z"/>',
    dashboard: '<path d="M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z"/>',
    players: '<path d="M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.33 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
    compare: '<path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5v2h2V1h-2zm0 15H5l5-6zm9-15h-5v2h5v13l-5-6v9h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z"/>',
    pipeline: '<path d="M4 5h4v14H4zm6 0h4v9h-4zm6 0h4v5h-4z"/>',
    video: '<path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11z"/>',
    reports: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm2 16H8v-2h8zm0-4H8v-2h8zm-3-5V3.5L18.5 9z"/>',
    import: '<path d="M19 9h-4V3H9v6H5l7 7zM5 18v2h14v-2z"/>',
    admin: '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11z"/>',
  };
  const NAV = [
    ['dashboard', 'Dashboard', 'players:read'], ['players', 'Player database', 'players:read'], ['compare', 'Comparison', 'players:read'],
    ['pipeline', 'Recruitment pipeline', 'pipeline:read'], ['video', 'Video scouting', 'players:read'], ['reports', 'Scouting reports', 'players:read'],
    ['import', 'Data import', 'import:run'], ['organization', 'Organization', 'org:manage'], ['admin', 'Administration', null],
    ['platform', 'Platform console', '__platform'],
  ];
  // Product mark: a neutral analytics glyph (radar chart). Deliberately NOT a club crest.
  const shield = '<svg class="brand-mark" viewBox="0 0 64 64" aria-hidden="true"><rect x="3" y="3" width="58" height="58" rx="14" fill="#0e241a" stroke="#2c5c47" stroke-width="2"/><polygon points="32,12 50,25 44,47 20,47 14,25" fill="none" stroke="#5f8473" stroke-width="1.5"/><polygon points="32,19 45,27 39,41 24,43 20,28" fill="#00a05a" fill-opacity=".35" stroke="#00c26e" stroke-width="2"/><circle cx="32" cy="19" r="2.6" fill="#d4af37"/></svg>';

  const initials = n => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  function orgBrand() {
    const o = S.user.organization || { name: 'Platform operator', short_name: 'Platform' };
    const logo = o.logo_data_url && /^data:image\/(png|jpeg|webp);base64,/.test(o.logo_data_url)
      ? h`<img class="org-logo" src="${o.logo_data_url}" alt="">` : h`<div class="org-logo ph">${initials(o.short_name || o.name)}</div>`;
    const orgs = S.user.organizations || [];
    return h`<div class="brand">${logo}<div style="min-width:0"><div class="brand-name" title="${o.name}">${o.short_name || o.name}</div><div class="brand-sub">Raja Scout Intelligence</div></div></div>
      ${orgs.length > 1 ? h`<div class="field" style="padding:0 6px"><label for="org-switch">Organization</label><select id="org-switch">${orgs.map(x => h`<option value="${x.id}" ${x.id === o.id ? raw('selected') : ''}>${x.name}${x.is_demo ? ' (demo)' : ''}</option>`)}</select></div>` : ''}`;
  }
  async function loadSubscription() {
    S.sub = null;
    if (S.user && S.user.organization) { try { S.sub = await api('/api/subscription'); } catch (_) { } }
  }
  function subscriptionBanner() {
    const x = S.sub;
    if (!x || x.plan === 'demo') return '';
    if (!x.writable) return h`<div class="notice err"><strong>Read-only workspace.</strong> Subscription status: ${label(x.effective_status === 'none' ? 'not set up' : x.effective_status)}. Your data remains visible and exportable; changes are disabled until the subscription is renewed.</div>`;
    if (x.effective_status === 'past_due') return h`<div class="notice warn"><strong>Payment overdue.</strong> Renew within the ${x.grace_days}-day grace period to avoid read-only mode.</div>`;
    if (x.effective_status === 'trialing' && x.trial_days_left != null && x.trial_days_left <= 14) return h`<div class="notice info">Trial of <strong>${x.plan_name}</strong> — ${x.trial_days_left} day${x.trial_days_left === 1 ? '' : 's'} left.</div>`;
    return '';
  }
  function applyBranding() {
    const o = (S.user && S.user.organization) || {};
    const accent = (o.settings || {}).accent_color;
    document.documentElement.style.setProperty('--gold', /^#[0-9a-fA-F]{6}$/.test(accent || '') ? accent : '#d4af37');
    document.documentElement.lang = o.primary_language || 'en';
    document.title = o.name ? `${o.short_name || o.name} · Raja Scout Intelligence` : 'Raja Scout Intelligence';
  }
  async function switchOrganization(id) {
    try {
      const r = await api('/api/auth/switch-organization', { method: 'POST', body: { organization_id: id } });
      setToken(r.access_token); S.user = await api('/api/auth/me'); await loadSubscription(); S.compare.clear(); saveCompare(); refCache = null;
      applyBranding(); location.hash = '#/dashboard'; route();
    } catch (e) { toast(e.message, true); }
  }

  function shell(active, title, content, actions = '') {
    const showAdmin = can('users:manage') || can('audit:read') || can('backup:run') || can('budget:manage');
    if (!S.user.organization) S.user.organization = null;
    $('#app').innerHTML = h`<div class="shell">
      <aside class="sidebar" id="sidebar">
        ${orgBrand()}
        <nav class="nav">${NAV.filter(([k, , p]) => k === 'admin' ? showAdmin : p === '__platform' ? S.user.is_platform_admin : can(p)).map(([k, t]) => h`<a href="#/${k}" class="${active === k ? 'active' : ''}"><svg viewBox="0 0 24 24" fill="currentColor">${raw(ICONS[k])}</svg>${t}${k === 'compare' && S.compare.size ? h` <span class="badge b-gold">${S.compare.size}</span>` : ''}</a>`)}</nav>
        <div class="side-foot"><div class="who">${S.user.full_name}</div><div class="muted">${S.user.role ? (S.meta?.roles?.[S.user.role] || S.user.role) : 'Platform operator'}</div>
          <div class="row" style="margin-top:8px"><button class="btn sm" id="pw-btn">Password</button><button class="btn sm" id="logout-btn">Log out</button></div></div>
      </aside>
      <div class="main">
        <header class="topbar"><button class="btn sm menu-btn" id="menu-btn" aria-label="Menu">☰</button><div class="title">${title}</div><div class="spacer"></div>${actions}</header>
        <main class="content"><div id="banners">${subscriptionBanner()}${S.user.organization?.is_demo ? h`<div class="fict-banner"><strong>Demo organization.</strong> Everything here is fictional sample data. Never enter real club data in a demo environment.</div>` : ''}</div><div id="content">${content}</div></main>
      </div></div>`.s;
    $('#logout-btn').onclick = logout;
    $('#pw-btn').onclick = changePassword;
    if ($('#org-switch')) $('#org-switch').onchange = e => switchOrganization(Number(e.target.value));
    $('#menu-btn').onclick = () => $('#sidebar').classList.toggle('open');
    $$('.nav a').forEach(a => a.addEventListener('click', () => $('#sidebar').classList.remove('open')));
  }
  const loading = (active, title) => shell(active, title, h`<div class="empty">Loading…</div>`);

  function changePassword() {
    modal('Change password', h`<div class="field"><label>Current password</label><input type="password" name="current_password" required autocomplete="current-password"></div>
      <div class="field"><label>New password (≥10 chars, letters and digits)</label><input type="password" name="new_password" required autocomplete="new-password"></div>`,
      { onSubmit: async f => { const r = await api('/api/auth/change-password', { method: 'POST', body: formData(f) }); setToken(r.access_token); toast('Password changed — other sessions were signed out'); } });
  }

  function logout() {
    S.token = null; S.user = null;
    try { sessionStorage.removeItem('rsi_token'); } catch (_) { }
    location.hash = '#/login';
    route();
  }

  // ------------------------------------------------------------------ login
  function loginView() {
    $('#app').innerHTML = h`<div class="login-wrap"><form class="login-card" id="login-form">
      <div class="brand">${raw(shield)}<div class="brand-name" style="font-size:20px">RAJA SCOUT INTELLIGENCE</div><div class="brand-sub">Football recruitment intelligence</div></div>
      <div class="field"><label for="email">Email</label><input id="email" name="username" type="email" autocomplete="username" required></div>
      <div class="field"><label for="pw">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" required></div>
      <button class="btn primary" style="width:100%" type="submit">Sign in</button>
      <div id="demo-hint"></div>
      <p class="faint" style="font-size:11px;margin-top:14px;text-align:center">${NOT_AFFILIATED}</p>
    </form></div>`.s;
    fetch('/api/public/config').then(r => r.json()).then(cfg => {
      if (cfg.deployment_mode === 'demo' && cfg.demo_accounts) $('#demo-hint').innerHTML = h`<p class="muted" style="font-size:12px;margin-top:16px"><span class="badge b-amber">DEMO</span> Fictional data only. Accounts: ${cfg.demo_accounts.map((a, i) => h`${i ? ', ' : ''}<code>${a}</code>`)} — password <code>RajaDemo2026!</code> unless changed by the operator.</p>`.s;
    }).catch(() => { });
    $('#login-form').onsubmit = async e => {
      e.preventDefault();
      const fd = new URLSearchParams(new FormData(e.target));
      try {
        const res = await fetch('/api/auth/token', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');
        setToken(data.access_token);
        S.user = await api('/api/auth/me');
        S.meta = await api('/api/meta');
        await loadSubscription();
        applyBranding();
        if (!S.user.organization && S.user.is_platform_admin) { location.hash = '#/platform'; return; }
        location.hash = '#/dashboard';
      } catch (err) { toast(err.message, true); }
    };
  }

  // ------------------------------------------------------------------ dashboard
  async function dashboardView() {
    loading('dashboard', 'Executive dashboard');
    const d = await api('/api/dashboard');
    const P = d.players, PL = d.pipeline, A = d.activity, B = d.budget;
    const posLabels = S.meta.positions;
    const listTable = (rows, empty) => rows.length ? h`<div class="table-wrap"><table><thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>Club</th><th>Stage</th><th>Priority</th>${can('financials:read') ? h`<th class="num">Est. fee</th>` : ''}</tr></thead><tbody>
      ${rows.map(r => h`<tr class="clickable" data-href="#/players/${r.player_id}"><td>${r.player_name} ${fictBadge(r.is_fictional)}</td><td>${posBadge(r.position)}</td><td>${r.age ?? '—'}</td><td class="muted">${r.club || '—'}</td><td>${stageBadge(r.stage)}</td><td>${prioBadge(r.priority)}</td>${can('financials:read') ? h`<td class="num">${fmtMoney(r.estimated_fee)}</td>` : ''}</tr>`)}
      </tbody></table></div>` : h`<div class="empty">${empty}</div>`;
    const content = h`
      ${P.fictional ? h`<div class="fict-banner"><strong>Demonstration mode:</strong> ${P.fictional} of ${P.total} players are FICTIONAL sample records. Import licensed data to begin real recruitment work.</div>` : ''}
      <div class="grid g4">
        <div class="kpi"><div class="label">Players in database</div><div class="value">${P.total}</div><div class="sub">${P.real} real · ${P.fictional} fictional · ${P.stale_records} stale (&gt;180d)</div></div>
        <div class="kpi"><div class="label">Under observation</div><div class="value">${PL.by_stage.under_observation}</div><div class="sub">${PL.active} active pipeline targets</div></div>
        <div class="kpi gold"><div class="label">Shortlisted</div><div class="value">${PL.by_stage.shortlisted + PL.by_stage.live_scouting}</div><div class="sub">incl. live scouting · ${PL.by_stage.approved} approved</div></div>
        <div class="kpi"><div class="label">Match reports (90 days)</div><div class="value">${A.match_reports_90d}</div><div class="sub">${A.live_reports_total} live · ${A.highlights_only_reports} highlights-only</div></div>
      </div>
      <div class="grid g3" style="margin-top:16px">
        <div class="card span2"><div class="card-head"><h3>Recruitment funnel</h3><a href="#/pipeline" class="btn sm">Open pipeline</a></div>
          ${hbars(S.meta.pipeline_stages.map(s => [label(s), PL.by_stage[s] || 0]), {})}</div>
        <div class="card"><div class="card-head"><h3>Recruitment budget ${B?.season ? h`<span class="muted">${B.season}</span>` : ''}</h3></div>
          ${B ? (B.transfer_budget != null ? h`
            <div class="kv"><dt>Transfer budget</dt><dd><strong>${fmtMoney(B.transfer_budget)}</strong></dd><dt>Committed (signed)</dt><dd>${fmtMoney(B.committed)}</dd><dt>Pending (approved / negotiating)</dt><dd>${fmtMoney(B.pending)}</dd><dt>Remaining</dt><dd style="color:${B.remaining < 0 ? 'var(--red)' : 'var(--gold)'}"><strong>${fmtMoney(B.remaining)}</strong></dd><dt>Shortlist value</dt><dd>${fmtMoney(B.shortlist_value)}</dd><dt>Wage budget</dt><dd>${fmtMoney(B.wage_budget)}</dd></div>
            <div class="bar-track" style="margin-top:14px;height:10px"><div class="bar-fill gold" style="width:${Math.min(100, ((B.committed + B.pending) / Math.max(1, B.transfer_budget)) * 100)}%"></div></div>
            <p class="faint" style="font-size:11.5px">${B.note}</p>` : h`<div class="empty">No budget set. ${can('budget:manage') ? h`<a href="#/admin">Set budget</a>` : ''}</div>`) : h`<div class="empty">Financial information is restricted for your role.</div>`}
        </div>
      </div>
      <div class="grid g2" style="margin-top:16px">
        <div class="card"><div class="card-head"><h3>Priority recruitment targets</h3></div>${listTable(PL.priority_targets, 'No high-priority targets.')}</div>
        <div class="card"><div class="card-head"><h3>Shortlisted candidates</h3></div>${listTable(PL.shortlisted, 'No shortlisted players.')}</div>
        <div class="card"><div class="card-head"><h3>Under observation</h3></div>${listTable(PL.under_observation, 'Nobody under observation.')}</div>
        <div class="card"><div class="card-head"><h3>Scouting activity (12 weeks)</h3></div>${weeklyChart(A.weekly)}
          <div class="grid g3" style="margin-top:10px;gap:8px;font-size:12.5px"><div><strong>${A.videos_linked}</strong> <span class="muted">videos (${A.full_match_videos} full)</span></div><div><strong>${A.video_observations}</strong> <span class="muted">observations</span></div><div><strong>${A.final_reports}/${A.scouting_reports}</strong> <span class="muted">reports final</span></div></div></div>
        <div class="card"><div class="card-head"><h3>Players by position</h3></div>${hbars(Object.keys(posLabels).map(p => [posLabels[p], P.by_position[p] || 0]))}</div>
        <div class="card"><div class="card-head"><h3>Players by nationality</h3></div>${hbars(Object.entries(P.by_nationality).slice(0, 12), { gold: true })}</div>
        <div class="card span2" style="grid-column:1/-1"><div class="card-head"><h3>Scout productivity</h3><span class="muted">${A.pipeline_decisions_30d} pipeline decisions in last 30 days</span></div>
          ${A.per_scout.length ? h`<div class="table-wrap"><table><thead><tr><th>Scout</th><th class="num">Match reports</th><th class="num">Live reports</th><th class="num">Video observations</th><th class="num">Reports (30d)</th><th class="num">Players covered</th></tr></thead><tbody>${A.per_scout.map(s => h`<tr><td>${s.scout}</td><td class="num">${s.match_reports}</td><td class="num">${s.live_reports}</td><td class="num">${s.video_observations}</td><td class="num">${s.reports_30d}</td><td class="num">${s.players_covered}</td></tr>`)}</tbody></table></div>` : h`<div class="empty">No scouting activity yet.</div>`}</div>
      </div>`;
    $('#content').innerHTML = content.s;
    bindRowLinks();
  }

  function bindRowLinks(root = document) { $$('[data-href]', root).forEach(el => el.onclick = e => { if (e.target.closest('a,button,input,label')) return; location.hash = el.dataset.href; }); }

  // ------------------------------------------------------------------ players: search
  const searchState = { params: { sort: 'full_name', order: 'asc', page: 1, page_size: 25 } };
  let refCache = null;
  async function refs() {
    if (!refCache) {
      const [leagues, clubs, sources] = await Promise.all([api('/api/leagues'), api('/api/clubs'), api('/api/data-sources')]);
      refCache = { leagues, clubs, sources };
    }
    return refCache;
  }

  async function playersView() {
    const { leagues } = await refs();
    const p = searchState.params;
    const M = S.meta;
    const opt = (v, t, sel) => h`<option value="${v}" ${sel ? raw('selected') : ''}>${t}</option>`;
    const metricOpts = Object.entries(M.metrics).map(([k, m]) => opt(k, m.label, false));
    const actions = h`${can('players:write') ? h`<a class="btn primary" href="#/players/new">+ New player</a>` : ''}<button class="btn" id="export-btn">Export CSV</button>`;
    shell('players', 'Player database', h`
      <form class="card" id="filters">
        <div class="filters">
          <div class="field"><label>Name</label><input name="q" value="${p.q || ''}" placeholder="Search name…"></div>
          <div class="field"><label>Position</label><select name="position"><option value="">Any</option>${Object.entries(M.positions).map(([k, t]) => opt(k, `${k} — ${t}`, p.position === k))}</select></div>
          <div class="field"><label>Tactical role</label><input name="tactical_role" value="${p.tactical_role || ''}" placeholder="e.g. playmaker"></div>
          <div class="field"><label>Age min</label><input name="age_min" type="number" min="15" max="45" value="${p.age_min || ''}"></div>
          <div class="field"><label>Age max</label><input name="age_max" type="number" min="15" max="45" value="${p.age_max || ''}"></div>
          <div class="field"><label>Nationality</label><input name="nationality" value="${p.nationality || ''}" placeholder="e.g. Senegal,Mali"></div>
          <div class="field"><label>League</label><select name="league_id"><option value="">Any</option>${leagues.map(l => opt(l.id, `${l.name} (${l.country})`, String(p.league_id) === String(l.id)))}</select></div>
          <div class="field"><label>League country</label><input name="league_country" value="${p.league_country || ''}"></div>
          <div class="field"><label>Height min (cm)</label><input name="height_min" type="number" value="${p.height_min || ''}"></div>
          <div class="field"><label>Height max (cm)</label><input name="height_max" type="number" value="${p.height_max || ''}"></div>
          <div class="field"><label>Preferred foot</label><select name="foot"><option value="">Any</option>${M.feet.map(f => opt(f, label(f), p.foot === f))}</select></div>
          <div class="field"><label>Contract expires before</label><input name="contract_expiry_before" type="date" value="${p.contract_expiry_before || ''}"></div>
          ${can('financials:read') ? h`<div class="field"><label>Max est. fee (${currency()})</label><input name="fee_max" type="number" step="50000" value="${p.fee_max || ''}"></div><div class="field"><label>Max salary (${currency()}/yr)</label><input name="salary_max" type="number" step="10000" value="${p.salary_max || ''}"></div>` : ''}
          <div class="field"><label>Availability</label><select name="availability"><option value="">Any</option>${M.availability.map(a => opt(a, label(a), p.availability === a))}</select></div>
          <div class="field"><label>Pipeline</label><select name="pipeline_stage"><option value="">Any</option>${opt('none', 'Not in pipeline', p.pipeline_stage === 'none')}${M.pipeline_stages.map(s => opt(s, label(s), p.pipeline_stage === s))}</select></div>
          <div class="field"><label>Min minutes (latest season)</label><input name="min_minutes" type="number" step="90" value="${p.min_minutes || ''}"></div>
        </div>
        <fieldset><legend>Statistical indicators (latest season, per 90 / %)</legend>
          <div class="filters" id="stat-rows">${(p._stats || [{}]).map(sf => statRow(metricOpts, sf))}</div>
          <button type="button" class="btn sm" id="add-stat">+ Add indicator</button>
        </fieldset>
        <div class="row end">
          <label class="check" style="margin:0 auto 0 0"><input type="checkbox" name="primary_only" ${p.primary_only ? raw('checked') : ''}> Primary position only</label>
          <label class="check" style="margin:0"><input type="checkbox" name="exclude_fictional" ${p.include_fictional === false ? raw('checked') : ''}> Exclude fictional data</label>
          <button type="button" class="btn ghost" id="reset">Reset</button><button class="btn primary" type="submit">Search</button>
        </div>
      </form>
      <div class="card"><div id="results"><div class="empty">Searching…</div></div></div>`, actions);

    function statRow(opts, sf = {}) {
      return h`<div class="row stat-row" style="gap:6px;margin-bottom:10px;flex-wrap:nowrap"><select name="_metric" style="flex:2"><option value="">— metric —</option>${Object.entries(M.metrics).map(([k, m]) => h`<option value="${k}" ${sf.k === k ? raw('selected') : ''}>${m.label}</option>`)}</select><select name="_op" style="width:64px;flex:none">${['>=', '<='].map(o => h`<option ${sf.op === o ? raw('selected') : ''}>${o}</option>`)}</select><input name="_val" type="number" step="any" style="width:80px;flex:none" value="${sf.v ?? ''}"></div>`;
    }
    $('#add-stat').onclick = () => $('#stat-rows').insertAdjacentHTML('beforeend', statRow(metricOpts).s);
    $('#reset').onclick = () => { searchState.params = { sort: 'full_name', order: 'asc', page: 1, page_size: 25 }; playersView(); };
    $('#export-btn').onclick = () => download('/api/players/export.csv', 'players.csv');
    $('#filters').onsubmit = e => {
      e.preventDefault();
      const f = e.target; const fd = formData(f);
      const stats = $$('.stat-row', f).map(r => ({ k: $('[name=_metric]', r).value, op: $('[name=_op]', r).value, v: $('[name=_val]', r).value })).filter(s => s.k && s.v !== '');
      const np = { sort: p.sort, order: p.order, page: 1, page_size: p.page_size, _stats: stats.length ? stats : undefined };
      for (const [k, v] of Object.entries(fd)) { if (!k.startsWith('_') && v !== null && v !== false && k !== 'exclude_fictional') np[k] = v; }
      if (fd.exclude_fictional) np.include_fictional = false;
      if (stats.length) np.stat_filters = stats.map(s => `${s.k}${s.op}${s.v}`).join(',');
      searchState.params = np;
      runSearch();
    };
    runSearch();
  }

  async function runSearch() {
    const p = searchState.params;
    const qs = new URLSearchParams(Object.entries(p).filter(([k, v]) => !k.startsWith('_') && v !== undefined && v !== null && v !== ''));
    const el = $('#results');
    try {
      const data = await api('/api/players?' + qs);
      const fin = can('financials:read');
      const sortTh = (k, t, cls = '') => h`<th class="sortable ${cls}" data-sort="${k}">${t}${p.sort === k ? (p.order === 'asc' ? ' ▲' : ' ▼') : ''}</th>`;
      const statKeys = (p._stats || []).map(s => s.k);
      const pages = Math.max(1, Math.ceil(data.total / p.page_size));
      el.innerHTML = h`<div class="card-head"><h3>${data.total} player${data.total === 1 ? '' : 's'}</h3>
          <div class="row"><span class="muted">Sort by metric</span><select id="metric-sort" style="width:auto"><option value="">—</option>${Object.entries(S.meta.metrics).map(([k, m]) => h`<option value="${k}" ${p.sort === 'metric:' + k ? raw('selected') : ''}>${m.label}</option>`)}</select>
          <button class="btn gold sm" id="cmp-go" ${S.compare.size < 2 ? raw('disabled') : ''}>Compare selected (${S.compare.size})</button></div></div>
        ${data.items.length ? h`<div class="table-wrap"><table><thead><tr><th></th>${sortTh('full_name', 'Player')}<th>Pos</th>${sortTh('age', 'Age')}<th>Nationality</th><th>Club / League</th>${sortTh('height', 'Height', 'num')}<th>Foot</th>${sortTh('contract_expiry', 'Contract')}${fin ? sortTh('fee', 'Est. fee', 'num') : ''}<th>Availability</th><th class="num">Min (latest)</th>${statKeys.map(k => h`<th class="num">${S.meta.metrics[k].label}</th>`)}<th>Pipeline</th>${sortTh('last_updated', 'Updated')}</tr></thead><tbody>
          ${data.items.map(r => h`<tr class="clickable" data-href="#/players/${r.id}">
            <td><input type="checkbox" class="cmp" data-id="${r.id}" ${S.compare.has(r.id) ? raw('checked') : ''} aria-label="Select for comparison"></td>
            <td><strong>${r.full_name}</strong> ${fictBadge(r.is_fictional)}<div class="faint" style="font-size:11.5px">${r.tactical_role || ''}</div></td>
            <td>${posBadge(r.primary_position)} <span class="faint">${(r.secondary_positions || []).join(' ')}</span></td><td>${r.age ?? '—'}</td><td>${r.nationality}</td>
            <td>${r.club_name || '—'}<div class="faint" style="font-size:11.5px">${r.league_name || ''}</div></td><td class="num">${r.height_cm ?? '—'}</td><td>${label(r.preferred_foot)}</td>
            <td>${fmtDate(r.contract_expiry)}</td>${fin ? h`<td class="num">${fmtMoney(r.estimated_fee)}</td>` : ''}<td>${availBadge(r.availability)}</td>
            <td class="num">${r.latest_minutes ?? '—'}</td>${statKeys.map(k => h`<td class="num">${fmtNum(r.matched_metrics?.[k])}</td>`)}<td>${stageBadge(r.pipeline_stage)}</td><td class="faint">${fmtDate(r.last_updated)}</td></tr>`)}
          </tbody></table></div>
          <div class="pager"><span class="muted">Page ${p.page} / ${pages}</span><button class="btn sm" id="prev" ${p.page <= 1 ? raw('disabled') : ''}>‹ Prev</button><button class="btn sm" id="next" ${p.page >= pages ? raw('disabled') : ''}>Next ›</button></div>`
          : h`<div class="empty">No players match these filters.</div>`}`.s;
      bindRowLinks(el);
      $$('th[data-sort]', el).forEach(th => th.onclick = () => { const k = th.dataset.sort; p.order = p.sort === k && p.order === 'asc' ? 'desc' : 'asc'; p.sort = k; runSearch(); });
      $('#metric-sort', el).onchange = e => { if (e.target.value) { p.sort = 'metric:' + e.target.value; p.order = S.meta.metrics[e.target.value].higher_is_better ? 'desc' : 'asc'; } else { p.sort = 'full_name'; p.order = 'asc'; } runSearch(); };
      $$('.cmp', el).forEach(cb => cb.onchange = () => { const id = Number(cb.dataset.id); if (cb.checked) { if (S.compare.size >= 5) { cb.checked = false; return toast('Maximum 5 players in a comparison', true); } S.compare.add(id); } else S.compare.delete(id); saveCompare(); $('#cmp-go').textContent = `Compare selected (${S.compare.size})`; $('#cmp-go').disabled = S.compare.size < 2; });
      $('#cmp-go', el).onclick = () => { location.hash = '#/compare'; };
      if ($('#prev', el)) { $('#prev', el).onclick = () => { p.page--; runSearch(); }; $('#next', el).onclick = () => { p.page++; runSearch(); }; }
    } catch (e) { el.innerHTML = h`<div class="notice err">${e.message}</div>`.s; }
  }

  // ------------------------------------------------------------------ player form
  async function playerFormView(id) {
    const { clubs, sources } = await refs();
    const p = id ? await api(`/api/players/${id}`) : { availability: 'unknown', secondary_positions: [] };
    const M = S.meta; const fin = can('financials:read');
    const sel = (name, options, cur, empty = true) => h`<select name="${name}">${empty ? h`<option value="">—</option>` : ''}${options.map(([v, t]) => h`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${t}</option>`)}</select>`;
    const inp = (name, lbl, type = 'text', extra = '') => h`<div class="field"><label>${lbl}</label><input name="${name}" type="${type}" value="${p[name] ?? ''}" ${raw(extra)}></div>`;
    shell('players', id ? `Edit — ${p.full_name}` : 'New player', h`<form class="card" id="pform">
      <fieldset><legend>Identity</legend><div class="form-grid">${inp('full_name', 'Full name *', 'text', 'required')}${inp('known_as', 'Known as')}${inp('date_of_birth', 'Date of birth', 'date')}${inp('nationality', 'Nationality *', 'text', 'required')}${inp('second_nationality', 'Second nationality')}</div></fieldset>
      <fieldset><legend>Club & position</legend><div class="form-grid">
        <div class="field"><label>Current club</label>${sel('current_club_id', clubs.map(c => [c.id, `${c.name} (${c.country})`]), p.current_club_id)}</div>
        <div class="field"><label>Primary position *</label>${sel('primary_position', Object.entries(M.positions).map(([k, t]) => [k, `${k} — ${t}`]), p.primary_position, false)}</div>
        <div class="field"><label>Secondary positions</label><select name="secondary_positions" multiple size="3">${Object.keys(M.positions).map(k => h`<option ${p.secondary_positions.includes(k) ? raw('selected') : ''}>${k}</option>`)}</select></div>
        ${inp('tactical_role', 'Tactical role')}</div></fieldset>
      <fieldset><legend>Physical</legend><div class="form-grid">${inp('height_cm', 'Height (cm)', 'number', 'min=140 max=220')}${inp('weight_kg', 'Weight (kg)', 'number', 'min=40 max=130')}
        <div class="field"><label>Preferred foot</label>${sel('preferred_foot', M.feet.map(f => [f, label(f)]), p.preferred_foot)}</div></div>
        <div class="field"><label>Physical characteristics (scout notes)</label><textarea name="physical_profile">${p.physical_profile || ''}</textarea></div></fieldset>
      <fieldset><legend>Contract & market</legend><div class="form-grid">${inp('contract_expiry', 'Contract expiry', 'date')}
        <div class="field"><label>Availability</label>${sel('availability', M.availability.map(a => [a, label(a)]), p.availability, false)}</div>
        ${fin ? h`${inp('estimated_fee', `Estimated fee (${currency()})`, 'number', 'min=0 step=10000')}${inp('fee_estimate_source', 'Fee estimate source')}${inp('salary_expectation', `Salary expectation (${currency()} / year gross)`, 'number', 'min=0 step=1000')}${inp('agent_name', 'Agent / representative')}` : h`<p class="muted">Financial fields are restricted for your role.</p>`}</div></fieldset>
      <fieldset><legend>Provenance</legend><div class="form-grid">
        <div class="field"><label>Data source</label>${sel('data_source_id', sources.map(s => [s.id, s.name + (s.is_fictional ? ' (fictional)' : '')]), p.data_source_id)}</div>${inp('source_reference', 'Source reference / ID')}</div>
        <div class="field"><label>Notes</label><textarea name="notes">${p.notes || ''}</textarea></div></fieldset>
      <div class="row end">${id && can('players:delete') ? h`<button type="button" class="btn danger" id="del" style="margin-right:auto">Delete player</button>` : ''}<a class="btn" href="${id ? '#/players/' + id : '#/players'}">Cancel</a><button class="btn primary" type="submit">${id ? 'Save changes' : 'Create player'}</button></div>
    </form>`);
    $('#pform').onsubmit = async e => {
      e.preventDefault();
      const body = formData(e.target);
      ['current_club_id', 'data_source_id'].forEach(k => { if (body[k] != null) body[k] = Number(body[k]); });
      if (!fin) ['estimated_fee', 'fee_estimate_source', 'salary_expectation', 'agent_name'].forEach(k => delete body[k]);
      try {
        const res = id ? await api(`/api/players/${id}`, { method: 'PATCH', body }) : await api('/api/players', { method: 'POST', body: clean(body) });
        toast(id ? 'Player updated' : 'Player created'); location.hash = `#/players/${res.id}`;
      } catch (err) { toast(err.message, true); }
    };
    if ($('#del')) $('#del').onclick = async () => { if (!confirm(`Delete ${p.full_name} and all linked scouting data? This cannot be undone.`)) return; try { await api(`/api/players/${id}`, { method: 'DELETE' }); toast('Player deleted'); location.hash = '#/players'; } catch (e) { toast(e.message, true); } };
  }

  // ------------------------------------------------------------------ player detail
  async function playerDetailView(id, tab = 'overview') {
    loading('players', 'Player');
    const [p, pipe] = await Promise.all([api(`/api/players/${id}`), can('pipeline:read') ? api(`/api/pipeline/player/${id}`) : null]);
    const inCmp = S.compare.has(p.id);
    const actions = h`<button class="btn gold" id="cmp-toggle">${inCmp ? '✓ In comparison' : '+ Compare'}</button>
      ${!pipe && can('pipeline:move') ? h`<button class="btn primary" id="add-pipe">+ Add to pipeline</button>` : ''}
      ${can('reports:write') ? h`<button class="btn" id="gen-report">Generate report</button>` : ''}
      ${can('players:write') ? h`<a class="btn" href="#/players/${p.id}/edit">Edit</a>` : ''}`;
    const tabs = [['overview', 'Overview'], ['analytics', 'Statistics & analytics'], ['video', 'Video'], ['match', 'Match reports'], ['reports', 'Reports'], ['history', 'Pipeline history']];
    shell('players', p.full_name, h`
      ${p.is_fictional ? h`<div class="fict-banner"><strong>FICTIONAL SAMPLE PLAYER.</strong> All data on this page is randomly generated for demonstration and must not be used for recruitment decisions.</div>` : ''}
      <div class="card" style="margin-bottom:16px"><div class="row" style="justify-content:space-between;align-items:flex-start">
        <div><h1 style="margin-bottom:4px">${p.full_name} ${fictBadge(p.is_fictional)}</h1>
          <div class="row muted">${posBadge(p.primary_position)} ${S.meta.positions[p.primary_position]} ${p.secondary_positions.length ? h`· also ${p.secondary_positions.join(', ')}` : ''} · ${p.age ?? '?'} yrs · ${p.nationality} · ${p.club_name || 'No club'} ${p.league_name ? h`(${p.league_name})` : ''}</div></div>
        <div class="row">${pipe ? h`<span class="muted">Pipeline:</span> ${stageBadge(pipe.stage)} ${prioBadge(pipe.priority)}` : h`<span class="badge b-grey">Not in pipeline</span>`} ${availBadge(p.availability)}</div></div></div>
      <div class="tabs">${tabs.map(([k, t]) => h`<button class="tab ${tab === k ? 'active' : ''}" data-tab="${k}">${t}</button>`)}</div>
      <div id="tab-body"><div class="empty">Loading…</div></div>`, actions);
    $$('.tab').forEach(b => b.onclick = () => { history.replaceState(null, '', `#/players/${id}/${b.dataset.tab}`); playerTab(p, pipe, b.dataset.tab); $$('.tab').forEach(x => x.classList.toggle('active', x === b)); });
    $('#cmp-toggle').onclick = () => { if (S.compare.has(p.id)) S.compare.delete(p.id); else { if (S.compare.size >= 5) return toast('Maximum 5 players', true); S.compare.add(p.id); } saveCompare(); playerDetailView(id, tab); };
    if ($('#add-pipe')) $('#add-pipe').onclick = () => addToPipeline(p, () => playerDetailView(id, tab));
    if ($('#gen-report')) $('#gen-report').onclick = () => generateReport(p);
    playerTab(p, pipe, tab);
  }

  async function generateReport(p) {
    const roles = Object.entries(S.meta.tactical_roles).filter(([, r]) => r.position === p.primary_position);
    modal('Generate scouting report draft', h`<p class="muted">The draft compiles verified data, scout opinions and model estimates — each item is labelled with its evidence type. Scouts must complete qualitative sections before finalising.</p>
      <div class="field"><label>Season</label><select name="season"><option value="">Latest</option><option value="all">All seasons</option>${[...new Set(p.stats.map(s => s.season))].map(s => h`<option>${s}</option>`)}</select></div>
      <div class="field"><label>Tactical role focus</label><select name="tactical_role"><option value="">All roles for position</option>${roles.map(([k, r]) => h`<option value="${k}">${r.label}</option>`)}</select></div>`,
      { submitLabel: 'Generate', onSubmit: async f => { const r = await api('/api/reports/generate', { method: 'POST', body: { player_id: p.id, ...clean(formData(f)) } }); toast('Draft report created'); location.hash = `#/reports/${r.id}`; } });
  }

  async function addToPipeline(p, after) {
    const users = await api('/api/users/directory');
    modal(`Add ${p.full_name} to pipeline`, h`<div class="form-grid">
      <div class="field"><label>Priority</label><select name="priority">${S.meta.priorities.map(x => h`<option ${x === 'medium' ? raw('selected') : ''}>${x}</option>`)}</select></div>
      <div class="field"><label>Target position</label><select name="target_position">${Object.keys(S.meta.positions).map(k => h`<option ${k === p.primary_position ? raw('selected') : ''}>${k}</option>`)}</select></div>
      <div class="field"><label>Assigned scout</label><select name="assigned_scout_id"><option value="">—</option>${users.map(u => h`<option value="${u.id}">${u.full_name}</option>`)}</select></div></div>
      <div class="field"><label>Reason for identification</label><textarea name="note" placeholder="Why is this player being identified?"></textarea></div>`,
      { submitLabel: 'Add', onSubmit: async f => { const b = clean(formData(f)); if (b.assigned_scout_id) b.assigned_scout_id = Number(b.assigned_scout_id); await api('/api/pipeline', { method: 'POST', body: { player_id: p.id, ...b } }); toast('Added to pipeline'); after && after(); } });
  }

  async function playerTab(p, pipe, tab) {
    const el = $('#tab-body');
    el.innerHTML = '<div class="empty">Loading…</div>';
    try {
      if (tab === 'overview') return overviewTab(el, p);
      if (tab === 'analytics') return analyticsTab(el, p);
      if (tab === 'video') return videoTab(el, p);
      if (tab === 'match') return matchTab(el, p);
      if (tab === 'reports') return reportsTab(el, p);
      if (tab === 'history') return historyTab(el, p, pipe);
    } catch (e) { el.innerHTML = h`<div class="notice err">${e.message}</div>`.s; }
  }

  function overviewTab(el, p) {
    const fin = !p.financials_redacted;
    el.innerHTML = h`<div class="grid g3">
      <div class="card"><h3>Profile</h3><dl class="kv"><dt>Full name</dt><dd>${p.full_name}</dd><dt>Known as</dt><dd>${p.known_as || '—'}</dd><dt>Date of birth</dt><dd>${fmtDate(p.date_of_birth)} (${p.age ?? '?'})</dd><dt>Nationality</dt><dd>${p.nationality}${p.second_nationality ? ' / ' + p.second_nationality : ''}</dd><dt>Club</dt><dd>${p.club_name || '—'}</dd><dt>League</dt><dd>${p.league_name || '—'} ${p.league_country ? h`<span class="muted">(${p.league_country})</span>` : ''}</dd><dt>Tactical role</dt><dd>${p.tactical_role || '—'}</dd></dl></div>
      <div class="card"><h3>Physical</h3><dl class="kv"><dt>Height</dt><dd>${p.height_cm ? p.height_cm + ' cm' : '—'}</dd><dt>Weight</dt><dd>${p.weight_kg ? p.weight_kg + ' kg' : '—'}</dd><dt>Preferred foot</dt><dd>${label(p.preferred_foot)}</dd></dl>
        <h4 style="margin-top:12px">Physical characteristics</h4><p>${p.physical_profile || h`<span class="faint">No scout notes recorded.</span>`}</p></div>
      <div class="card"><h3>Contract & market</h3><dl class="kv"><dt>Contract expiry</dt><dd>${fmtDate(p.contract_expiry)}</dd><dt>Availability</dt><dd>${availBadge(p.availability)}</dd>
        ${fin ? h`<dt>Estimated fee</dt><dd><strong style="color:var(--gold)">${fmtMoney(p.estimated_fee)}</strong></dd><dt>Fee source</dt><dd class="muted">${p.fee_estimate_source || '—'}</dd><dt>Salary expectation</dt><dd>${fmtMoney(p.salary_expectation)} / yr</dd><dt>Representative</dt><dd>${p.agent_name || '—'}</dd>` : h`<dt>Financials</dt><dd class="muted">Restricted for your role</dd>`}</dl></div>
      <div class="card span2"><h3>Season statistics (raw totals)</h3>${statsTable(p)}</div>
      <div class="card"><h3>Data provenance</h3><dl class="kv"><dt>Profile source</dt><dd>${p.data_source || h`<span class="badge b-red">No source</span>`}</dd><dt>Reference</dt><dd>${p.source_reference || '—'}</dd><dt>Last updated</dt><dd>${fmtDateTime(p.last_updated)}</dd><dt>Created</dt><dd>${fmtDateTime(p.created_at)}</dd></dl>
        ${p.notes ? h`<h4 style="margin-top:12px">Notes</h4><p>${p.notes}</p>` : ''}</div></div>`.s;
    if ($('#add-stats', el)) $('#add-stats', el).onclick = () => statsForm(p);
    $$('.del-stat', el).forEach(b => b.onclick = async () => { if (!confirm('Delete this stat line?')) return; try { await api(`/api/players/${p.id}/stats/${b.dataset.id}`, { method: 'DELETE' }); toast('Deleted'); playerDetailView(p.id, 'overview'); } catch (e) { toast(e.message, true); } });
  }

  function statsTable(p) {
    const cols = [['minutes', 'Min'], ['appearances', 'Apps'], ['starts', 'Starts'], ['goals', 'G'], ['assists', 'A'], ['npxg', 'npxG'], ['xa', 'xA'], ['passes_completed', 'Pass cmp'], ['progressive_passes', 'Prog P'], ['tackles_won', 'Tkl W'], ['interceptions', 'Int'], ['aerial_duels_won', 'Aer W']];
    return h`${p.stats.length ? h`<div class="table-wrap"><table><thead><tr><th>Season</th><th>League</th>${cols.map(([, t]) => h`<th class="num">${t}</th>`)}<th>Source</th><th>Updated</th>${can('stats:write') ? h`<th></th>` : ''}</tr></thead><tbody>
      ${p.stats.map(s => h`<tr><td>${s.season}</td><td class="muted">${s.league_name || '—'}</td>${cols.map(([k]) => h`<td class="num">${s[k] ?? h`<span class="faint">—</span>`}</td>`)}<td>${s.data_source} ${fictBadge(s.is_fictional)}</td><td class="faint">${fmtDate(s.last_updated)}</td>${can('stats:write') ? h`<td><button class="btn ghost sm del-stat" data-id="${s.id}">✕</button></td>` : ''}</tr>`)}
      </tbody></table></div><p class="faint" style="font-size:12px">"—" = not provided by the source (never treated as zero).</p>` : h`<div class="empty">No statistics recorded.</div>`}
      ${can('stats:write') ? h`<div class="row end" style="margin-top:10px"><button class="btn sm" id="add-stats">+ Add season stat line</button></div>` : ''}`;
  }

  async function statsForm(p) {
    const { leagues, sources } = await refs();
    const groups = {
      Volume: ['appearances', 'starts', 'minutes', 'team_matches'], Attacking: ['goals', 'non_penalty_goals', 'assists', 'shots', 'shots_on_target', 'xg', 'npxg', 'xa', 'key_passes', 'touches_in_box'],
      'Passing & progression': ['passes_attempted', 'passes_completed', 'progressive_passes', 'passes_final_third', 'long_passes_attempted', 'long_passes_completed', 'crosses_attempted', 'crosses_completed', 'progressive_carries', 'dribbles_attempted', 'dribbles_completed'],
      Defending: ['tackles', 'tackles_won', 'interceptions', 'recoveries', 'defensive_duels', 'defensive_duels_won', 'aerial_duels', 'aerial_duels_won', 'clearances', 'blocks', 'pressures', 'fouls_committed', 'yellow_cards', 'red_cards'],
      Goalkeeping: ['saves', 'shots_on_target_faced', 'goals_conceded', 'clean_sheets', 'psxg_faced'],
    };
    modal(`Add statistics — ${p.full_name}`, h`<div class="notice">Only enter figures from an identified, licensed source. Leave a field empty if the source does not provide it — empty is stored as "not available", not zero.</div>
      <div class="form-grid"><div class="field"><label>Season *</label><input name="season" placeholder="2025-26" required></div>
      <div class="field"><label>Competition</label><select name="league_id"><option value="">—</option>${leagues.map(l => h`<option value="${l.id}">${l.name} (${l.country})</option>`)}</select></div>
      <div class="field"><label>Club</label><input name="club_name" value="${p.club_name || ''}"></div>
      <div class="field"><label>Data source *</label><select name="data_source_id" required>${sources.map(s => h`<option value="${s.id}">${s.name}</option>`)}</select></div></div>
      ${Object.entries(groups).map(([g, fs]) => h`<fieldset><legend>${g}</legend><div class="form-grid">${fs.map(f => h`<div class="field"><label>${label(f)}</label><input name="${f}" type="number" min="0" step="${['xg', 'npxg', 'xa', 'psxg_faced'].includes(f) ? '0.01' : '1'}"></div>`)}</div></fieldset>`)}`,
      { wide: true, onSubmit: async f => { const b = clean(formData(f)); b.data_source_id = Number(b.data_source_id); if (b.league_id) b.league_id = Number(b.league_id); await api(`/api/players/${p.id}/stats`, { method: 'POST', body: b }); toast('Statistics saved'); playerDetailView(p.id, 'overview'); } });
  }

  async function analyticsTab(el, p, season) {
    const seasons = [...new Set(p.stats.map(s => s.season))];
    const a = await api(`/api/players/${p.id}/analytics${season ? '?season=' + encodeURIComponent(season) : ''}`);
    if (!a.has_data) { el.innerHTML = h`<div class="empty">${a.caveats.join(' ')}</div>`.s; return; }
    const pm = a.profile_metrics;
    const c = a.consistency;
    const profileKeys = S.meta.position_profiles[p.primary_position];
    el.innerHTML = h`<div class="row" style="margin-bottom:12px"><span class="muted">Season</span><select id="season-sel" style="width:auto">${seasons.map(s => h`<option ${a.season === s ? raw('selected') : ''}>${s}</option>`)}<option value="all" ${a.season === 'all' ? raw('selected') : ''}>All seasons combined</option></select>
        <span class="badge ${a.sample_reliable ? 'b-green' : 'b-amber'}">${Math.round(a.minutes)} minutes · ${a.sample_reliable ? 'reliable sample' : 'small sample'}</span>
        <span class="badge ${a.provenance.is_fictional ? 'b-amber' : 'b-green'}">${a.provenance.sources.join(', ')}</span><span class="faint">updated ${fmtDate(a.provenance.last_updated)}</span></div>
      <div class="notice warn"><strong>How to read this:</strong><ul class="caveats">${a.caveats.map(x => h`<li>${x}</li>`)}</ul></div>
      <div class="grid g2" style="margin-top:12px">
        <div class="card"><div class="card-head"><h3>${S.meta.positions[p.primary_position]} profile</h3><span class="muted">pool: ${a.pool.size} ${a.pool.position}s ≥${a.pool.min_minutes} min</span></div>
          ${radar(pm.map(m => m.label.replace(' /90', '').replace(' %', '%')), [{ label: p.full_name, values: pm.map(m => m.percentile) }])}</div>
        <div class="card"><h3>Position-specific indicators</h3><div class="table-wrap"><table><thead><tr><th>Metric</th><th class="num">Value</th><th class="num">League-adj.</th><th>Percentile</th><th class="num">Pool</th></tr></thead><tbody>
          ${pm.map(m => h`<tr><td>${m.label}${m.higher_is_better ? '' : h` <span class="faint" title="Lower is better">↓</span>`}</td><td class="num"><strong>${fmtNum(m.value, m.unit === '%' ? 1 : 2)}${m.value != null ? m.unit : ''}</strong></td><td class="num muted">${fmtNum(m.league_adjusted)}</td><td>${pctCell(m.percentile)}</td><td class="num faint">${m.pool_size}</td></tr>`)}
          </tbody></table></div>
          <h3 style="margin-top:16px">Tactical role fit <span class="badge b-purple">MODEL</span></h3>
          ${a.role_fit.map(r => h`<div class="bar-row" style="grid-template-columns:180px 1fr 60px"><span>${r.label}</span><div class="bar-track"><div class="bar-fill gold" style="width:${r.score ?? 0}%"></div></div><span class="num">${r.score != null ? Math.round(r.score) : 'n/a'}<span class="faint" style="font-size:10px"> ${r.data_coverage_pct}%cov</span></span></div>`)}
          <p class="faint" style="font-size:11.5px">${a.role_fit[0]?.note || ''}</p></div>
        <div class="card span2" style="grid-column:1/-1"><h3>Minutes & consistency</h3>
          <div class="table-wrap"><table><thead><tr><th>Season</th><th class="num">Minutes</th><th class="num">Apps</th><th class="num">Starts</th><th class="num">Minutes share</th><th class="num">Start rate</th>${profileKeys.map(k => h`<th class="num" title="${S.meta.metrics[k].label}">${S.meta.metrics[k].label.replace(' /90', '').slice(0, 18)}</th>`)}</tr></thead><tbody>
          ${c.seasons.map(s => h`<tr><td>${s.season}</td><td class="num">${s.minutes ?? '—'}</td><td class="num">${s.appearances ?? '—'}</td><td class="num">${s.starts ?? '—'}</td><td class="num">${s.minutes_share_pct != null ? s.minutes_share_pct + '%' : '—'}</td><td class="num">${s.start_rate_pct != null ? s.start_rate_pct + '%' : '—'}</td>${profileKeys.map(k => h`<td class="num">${fmtNum(s.metrics[k])}</td>`)}</tr>`)}
          ${Object.keys(c.season_to_season_variation_pct).length ? h`<tr><td colspan="6" class="muted">Season-to-season variation (CV%)</td>${profileKeys.map(k => h`<td class="num faint">${c.season_to_season_variation_pct[k] != null ? c.season_to_season_variation_pct[k] + '%' : '—'}</td>`)}</tr>` : ''}
          </tbody></table></div><p class="faint" style="font-size:12px">${c.note}</p></div>
      </div>`.s;
    $('#season-sel', el).onchange = e => analyticsTab(el, p, e.target.value);
  }

  async function videoTab(el, p) {
    const vids = await api(`/api/videos?player_id=${p.id}`);
    el.innerHTML = h`<div class="row end" style="margin-bottom:12px">${can('video:write') ? h`<button class="btn primary" id="add-video">+ Link licensed footage</button>` : ''}</div>
      ${vids.length ? vids.map(v => videoCard(v)) : h`<div class="empty">No footage linked. Only link footage your organization is licensed or authorised to view — the platform stores links, never video files.</div>`}`.s;
    if ($('#add-video', el)) $('#add-video', el).onclick = () => videoForm(p.id, () => playerTab(p, null, 'video'));
    bindVideoCards(el, () => playerTab(p, null, 'video'));
  }

  function videoCard(v) {
    return h`<div class="card"><div class="card-head"><div><h3>${v.home_team} v ${v.away_team}</h3><span class="muted">${fmtDate(v.match_date)} · ${v.competition || '—'}${v.player_name ? h` · <a href="#/players/${v.player_id}">${v.player_name}</a>` : ''}</span></div>
        <div class="row">${v.is_full_match ? h`<span class="badge b-green">FULL MATCH</span>` : h`<span class="badge b-amber">PARTIAL / HIGHLIGHTS</span>`}<span class="badge b-grey">${label(v.license_type)}</span><a class="btn sm" href="${v.video_url}" target="_blank" rel="noopener noreferrer">Open footage ↗</a>
        ${can('video:write') ? h`<button class="btn sm primary add-obs" data-vid="${v.id}" data-dur="${v.duration_minutes || ''}">+ Observation</button>` : ''}
        ${can('match_reports:write') ? h`<button class="btn sm gold add-mr" data-vid="${v.id}" data-pid="${v.player_id}" data-full="${v.is_full_match ? 1 : ''}">Write match report</button>` : ''}</div></div>
      ${v.scope_warning ? h`<div class="notice warn">${v.scope_warning}</div>` : ''}
      <p class="faint" style="font-size:12px">Rights holder: ${v.rights_holder} · licence confirmed ${v.license_confirmed ? '✓' : '✗'} ${v.notes ? h`· ${v.notes}` : ''}</p>
      ${v.observations.length ? h`<div class="table-wrap"><table><thead><tr><th>Time</th><th>Category</th><th>Phase</th><th>Assessment</th><th>Technical</th><th>Tactical</th><th></th></tr></thead><tbody>
        ${v.observations.map(o => h`<tr><td class="video-ts">${tsFmt(o.timestamp_seconds)}</td><td>${label(o.category)}</td><td class="muted">${label(o.phase)}</td><td><span class="badge ${o.assessment === 'positive' ? 'b-green' : o.assessment === 'negative' ? 'b-red' : 'b-grey'}">${o.assessment}</span></td><td style="white-space:normal;min-width:180px">${o.technical_comment || ''}</td><td style="white-space:normal;min-width:180px">${o.tactical_comment || ''}</td><td>${can('video:write') ? h`<button class="btn ghost sm del-obs" data-vid="${v.id}" data-id="${o.id}">✕</button>` : ''}</td></tr>`)}
      </tbody></table></div>` : h`<div class="empty">No observations yet.</div>`}</div>`;
  }

  function bindVideoCards(el, refresh) {
    $$('.add-obs', el).forEach(b => b.onclick = () => observationForm(Number(b.dataset.vid), b.dataset.dur, refresh));
    $$('.add-mr', el).forEach(b => b.onclick = () => matchReportForm(Number(b.dataset.pid), { video_id: Number(b.dataset.vid), full: !!b.dataset.full }, refresh));
    $$('.del-obs', el).forEach(b => b.onclick = async () => { if (!confirm('Delete observation?')) return; try { await api(`/api/videos/${b.dataset.vid}/observations/${b.dataset.id}`, { method: 'DELETE' }); refresh(); } catch (e) { toast(e.message, true); } });
  }

  function videoForm(playerId, after) {
    const M = S.meta;
    modal('Link licensed match footage', h`<div class="notice">Raja Scout Intelligence never hosts or redistributes footage. Link only to licensed platforms or club-owned recordings. Highlight packages are never treated as complete match analysis.</div>
      <div class="form-grid"><div class="field"><label>Home team *</label><input name="home_team" required></div><div class="field"><label>Away team *</label><input name="away_team" required></div>
      <div class="field"><label>Match date</label><input name="match_date" type="date"></div><div class="field"><label>Competition</label><input name="competition"></div></div>
      <div class="field"><label>Footage URL (licensed platform) *</label><input name="video_url" type="url" required placeholder="https://"></div>
      <div class="form-grid"><div class="field"><label>Licence type *</label><select name="license_type" id="lic">${M.video_licenses.map(l => h`<option value="${l}">${label(l)}</option>`)}</select></div>
      <div class="field"><label>Rights holder *</label><input name="rights_holder" required></div><div class="field"><label>Duration (min)</label><input name="duration_minutes" type="number" min="1" max="200"></div></div>
      <label class="check"><input type="checkbox" name="is_full_match" id="full"> This is complete, unedited full-match footage</label>
      <label class="check" style="margin-top:6px"><input type="checkbox" name="license_confirmed"> I confirm my organization holds a licence or authorisation to view this footage</label>
      <div class="field" style="margin-top:10px"><label>Notes</label><textarea name="notes"></textarea></div>`,
      { onSubmit: async f => { const b = clean(formData(f)); b.is_full_match = !!b.is_full_match; b.license_confirmed = !!b.license_confirmed; await api('/api/videos', { method: 'POST', body: { player_id: playerId, ...b } }); toast('Footage linked'); after(); } });
    const sync = () => { const hl = $('#lic').value === 'highlights'; $('#full').disabled = hl; if (hl) $('#full').checked = false; };
    $('#lic').onchange = sync;
  }

  function observationForm(videoId, dur, after) {
    const M = S.meta;
    modal('Add timestamped observation', h`<div class="form-grid"><div class="field"><label>Timestamp (mm:ss) *</label><input name="ts" placeholder="34:12" required></div>
      <div class="field"><label>Category *</label><select name="category">${M.observation_categories.map(c => h`<option value="${c}">${label(c)}</option>`)}</select></div>
      <div class="field"><label>Phase of play</label><select name="phase"><option value="">—</option>${M.game_phases.map(c => h`<option value="${c}">${label(c)}</option>`)}</select></div>
      <div class="field"><label>Assessment</label><select name="assessment">${M.observation_assessments.map(c => h`<option ${c === 'neutral' ? raw('selected') : ''}>${c}</option>`)}</select></div></div>
      <div class="field"><label>Technical comment</label><textarea name="technical_comment"></textarea></div><div class="field"><label>Tactical comment</label><textarea name="tactical_comment"></textarea></div>`,
      { onSubmit: async f => { const b = clean(formData(f)); const s = parseTs(b.ts); if (s == null) throw new Error('Invalid timestamp — use mm:ss'); delete b.ts; b.timestamp_seconds = s; await api(`/api/videos/${videoId}/observations`, { method: 'POST', body: b }); toast('Observation saved'); after(); return false; } });
  }

  function matchReportForm(playerId, { video_id, full } = {}, after) {
    const M = S.meta;
    const types = video_id ? (full ? ['video_full_match', 'video_highlights'] : ['video_highlights']) : ['live'];
    const rating = n => h`<div class="field"><label>${label(n)} (1–10)</label><input name="${n}_rating" type="number" min="1" max="10"></div>`;
    modal('Match report', h`<div class="notice info">Ratings and notes are recorded as <strong>your</strong> scouting opinion and attributed to you. Leave a rating blank if you could not assess it in this match. Only record mental/behavioural observations you actually witnessed.</div>
      <div class="form-grid"><div class="field"><label>Observation type</label><select name="observation_type">${types.map(t => h`<option value="${t}">${label(t)}</option>`)}</select></div>
      <div class="field"><label>Match date</label><input name="match_date" type="date"></div><div class="field"><label>Opponent</label><input name="opponent"></div><div class="field"><label>Competition</label><input name="competition"></div>
      <div class="field"><label>Position played</label><select name="position_played"><option value="">—</option>${Object.keys(M.positions).map(k => h`<option>${k}</option>`)}</select></div><div class="field"><label>Minutes observed</label><input name="minutes_observed" type="number" min="0" max="130"></div></div>
      <fieldset><legend>Ratings (opinion)</legend><div class="form-grid">${['technical', 'tactical', 'physical', 'mental', 'overall'].map(rating)}</div></fieldset>
      <div class="grid g2" style="gap:0 14px">${['technical_notes', 'tactical_notes', 'physical_notes', 'mental_notes', 'strengths', 'weaknesses'].map(n => h`<div class="field"><label>${label(n)}</label><textarea name="${n}"></textarea></div>`)}</div>
      <div class="field"><label>Summary</label><textarea name="summary"></textarea></div>
      <div class="field"><label>Recommendation</label><select name="recommendation"><option value="">—</option>${M.recommendations.map(r => h`<option value="${r}">${label(r)}</option>`)}</select></div>`,
      { wide: true, onSubmit: async f => { const b = clean(formData(f)); await api('/api/match-reports', { method: 'POST', body: { player_id: playerId, video_id: video_id || null, ...b } }); toast('Match report saved'); after && after(); } });
  }

  async function matchTab(el, p) {
    const reps = await api(`/api/match-reports?player_id=${p.id}`);
    el.innerHTML = h`<div class="row end" style="margin-bottom:12px">${can('match_reports:write') ? h`<button class="btn primary" id="add-live">+ Live scouting report</button>` : ''}<span class="faint">Video reports are created from the Video tab.</span></div>
      ${reps.length ? reps.map(r => h`<div class="card"><div class="card-head"><div><h3>${fmtDate(r.match_date)} vs ${r.opponent || '—'} <span class="muted">${r.competition || ''}</span></h3><span class="muted">by ${r.scout_name || 'Unknown'} · ${label(r.observation_type)} · ${r.minutes_observed ?? '?'} min observed · ${r.position_played || ''}</span></div>
          <div class="row"><span class="badge b-blue">SCOUT OPINION</span>${r.is_complete_match_analysis ? '' : h`<span class="badge b-amber">HIGHLIGHTS ONLY</span>`}${r.recommendation ? h`<span class="badge b-gold">${label(r.recommendation)}</span>` : ''}</div></div>
          ${r.evidence_warning ? h`<div class="notice warn">${r.evidence_warning}</div>` : ''}
          <div class="grid g4" style="gap:8px;margin-bottom:10px">${['technical', 'tactical', 'physical', 'mental', 'overall'].map(k => h`<div><span class="muted" style="font-size:12px">${label(k)}</span><div style="font-size:18px;font-weight:700">${r[k + '_rating'] ?? h`<span class="faint">—</span>`}${r[k + '_rating'] != null ? h`<span class="faint" style="font-size:12px">/10</span>` : ''}</div></div>`)}</div>
          <div class="grid g2" style="gap:6px 16px">${['technical_notes', 'tactical_notes', 'physical_notes', 'mental_notes', 'strengths', 'weaknesses', 'summary'].filter(k => r[k]).map(k => h`<div><h4>${label(k)}</h4><p style="margin:0">${r[k]}</p></div>`)}</div></div>`)
        : h`<div class="empty">No match reports yet.</div>`}`.s;
    if ($('#add-live', el)) $('#add-live', el).onclick = () => matchReportForm(p.id, {}, () => playerTab(p, null, 'match'));
  }

  async function reportsTab(el, p) {
    const reps = await api(`/api/reports?player_id=${p.id}`);
    el.innerHTML = reportsTable(reps, false).s;
    bindRowLinks(el);
  }

  function reportsTable(reps, withPlayer = true) {
    return reps.length ? h`<div class="table-wrap"><table><thead><tr><th>Title</th>${withPlayer ? h`<th>Player</th>` : ''}<th>Status</th><th>Recommendation</th><th>Risk</th><th>Author</th><th>Updated</th></tr></thead><tbody>
      ${reps.map(r => h`<tr class="clickable" data-href="#/reports/${r.id}"><td>${r.title} ${r.auto_generated ? h`<span class="badge b-purple">draft-assisted</span>` : ''}</td>${withPlayer ? h`<td>${r.player_name}</td>` : ''}<td><span class="badge ${r.status === 'final' ? 'b-gold' : 'b-grey'}">${r.status}</span></td><td>${label(r.recommendation)}</td><td>${r.risk_level ? h`<span class="badge ${r.risk_level === 'high' ? 'b-red' : r.risk_level === 'medium' ? 'b-amber' : 'b-green'}">${r.risk_level}</span>` : '—'}</td><td class="muted">${r.author_name || '—'}</td><td class="faint">${fmtDateTime(r.updated_at)}</td></tr>`)}
      </tbody></table></div>` : h`<div class="empty">No scouting reports yet.</div>`;
  }

  async function historyTab(el, p, pipe) {
    if (!pipe) { el.innerHTML = h`<div class="empty">This player is not in the recruitment pipeline.</div>`.s; return; }
    el.innerHTML = h`<div class="grid g2"><div class="card"><div class="card-head"><h3>Decision history</h3>${can('pipeline:move') ? h`<button class="btn sm primary" id="mv">Move stage</button>` : ''}</div>
      <ul class="timeline">${pipe.history.slice().reverse().map(ev => h`<li><div>${ev.from_stage ? h`${stageBadge(ev.from_stage)} → ` : ''}${stageBadge(ev.to_stage)}</div><div style="margin:4px 0">${ev.note || ''}</div><div class="when">${ev.user_name || 'Unknown'} · ${fmtDateTime(ev.created_at)}</div></li>`)}</ul></div>
      <div class="card"><h3>Pipeline entry</h3><dl class="kv"><dt>Stage</dt><dd>${stageBadge(pipe.stage)}</dd><dt>Priority</dt><dd>${prioBadge(pipe.priority)}</dd><dt>Target position</dt><dd>${pipe.target_position || '—'}</dd><dt>Assigned scout</dt><dd>${pipe.assigned_scout_name || '—'}</dd><dt>Added</dt><dd>${fmtDateTime(pipe.created_at)}</dd>${pipe.rejection_reason ? h`<dt>Rejection reason</dt><dd>${pipe.rejection_reason}</dd>` : ''}</dl></div></div>`.s;
    if ($('#mv', el)) $('#mv', el).onclick = () => moveDialog(pipe, () => playerDetailView(p.id, 'history'));
  }

  function moveDialog(entry, after) {
    const stages = S.meta.pipeline_stages.filter(s => s !== entry.stage);
    const order = S.meta.pipeline_stages.filter(s => s !== 'rejected');
    const next = order[order.indexOf(entry.stage) + 1];
    modal(`Move ${entry.player_name}`, h`<p class="muted">Current stage: ${stageBadge(entry.stage)}. Every decision is recorded permanently with your name and rationale.</p>
      <div class="field"><label>New stage</label><select name="to_stage">${stages.map(s => h`<option value="${s}" ${s === next ? raw('selected') : ''}>${label(s)}</option>`)}</select></div>
      <div class="field"><label>Decision rationale *</label><textarea name="note" required minlength="3" placeholder="Evidence and reasoning for this decision"></textarea></div>
      <p class="faint" style="font-size:12px">Rules: stages advance in order; Shortlisted requires a match report; Approved requires a finalised scouting report and Sporting Director rights; Negotiation/Signed are reserved to the Sporting Director.</p>`,
      { submitLabel: 'Record decision', onSubmit: async f => { await api(`/api/pipeline/${entry.id}/move`, { method: 'POST', body: formData(f) }); toast('Decision recorded'); after(); } });
  }

  // ------------------------------------------------------------------ compare
  async function compareView() {
    loading('compare', 'Player comparison');
    const ids = [...S.compare];
    if (ids.length < 2) {
      shell('compare', 'Player comparison', h`<div class="empty">Select 2–5 players of the same position from the <a href="#/players">player database</a> (tick the checkbox) or a player page (“+ Compare”).${ids.length ? h`<div style="margin-top:10px"><button class="btn sm" id="clr">Clear selection</button></div>` : ''}</div>`);
      if ($('#clr')) $('#clr').onclick = () => { S.compare.clear(); saveCompare(); compareView(); };
      return;
    }
    let role = compareView.role || null;
    let data;
    try { data = await api('/api/compare', { method: 'POST', body: { player_ids: ids, tactical_role: role } }); }
    catch (e) {
      shell('compare', 'Player comparison', h`<div class="notice err">${e.message}</div><div class="row"><button class="btn" id="clr">Clear selection</button><a class="btn" href="#/players">Back to search</a></div>`);
      $('#clr').onclick = () => { S.compare.clear(); saveCompare(); compareView(); }; return;
    }
    const M = S.meta; const P = data.players;
    const roles = Object.entries(M.tactical_roles).filter(([, r]) => r.position === data.position);
    const best = k => { const m = M.metrics[k]; const vals = P.map(x => x.metrics.find(y => y.key === k)?.value).filter(v => v != null); if (!vals.length) return null; return m.higher_is_better ? Math.max(...vals) : Math.min(...vals); };
    shell('compare', `Comparison — ${M.positions[data.position]}`, h`
      ${P.some(x => x.player.is_fictional) ? h`<div class="fict-banner">Comparison includes FICTIONAL sample players.</div>` : ''}
      <div class="row" style="margin-bottom:14px"><span class="muted">Tactical role lens</span><select id="role" style="width:auto">${roles.map(([k, r]) => h`<option value="${k}" ${data.tactical_role === k ? raw('selected') : ''}>${r.label}</option>`)}</select><span style="flex:1"></span><button class="btn sm" id="clr">Clear selection</button></div>
      <div class="grid g2">
        <div class="card"><h3>Percentile radar</h3>${radar(data.profile.map(k => M.metrics[k].label.replace(' /90', '').replace(' %', '%')), P.map(x => ({ label: x.player.full_name, values: x.metrics.map(m => m.percentile) })), 420)}</div>
        <div class="card"><h3>Profiles</h3><div class="table-wrap"><table><thead><tr><th></th>${P.map((x, i) => h`<th><span style="color:${PALETTE[i]}">●</span> <a href="#/players/${x.player.id}">${x.player.full_name}</a></th>`)}</tr></thead><tbody>
          <tr><td class="muted">Age</td>${P.map(x => h`<td>${x.player.age ?? '—'}</td>`)}</tr><tr><td class="muted">Nationality</td>${P.map(x => h`<td>${x.player.nationality}</td>`)}</tr>
          <tr><td class="muted">Club</td>${P.map(x => h`<td>${x.player.club || '—'}</td>`)}</tr><tr><td class="muted">League</td>${P.map(x => h`<td class="muted">${x.player.league || '—'}</td>`)}</tr>
          <tr><td class="muted">Height / foot</td>${P.map(x => h`<td>${x.player.height_cm ?? '—'} · ${label(x.player.preferred_foot)}</td>`)}</tr>
          <tr><td class="muted">Minutes (${P[0].season})</td>${P.map(x => h`<td>${x.minutes != null ? Math.round(x.minutes) : '—'} ${x.sample_reliable ? '' : h`<span class="badge b-amber">small</span>`}</td>`)}</tr>
          <tr><td class="muted">Pipeline</td>${P.map(x => h`<td>${stageBadge(x.player.pipeline_stage)}</td>`)}</tr>
          <tr><td class="muted">Role fit <span class="badge b-purple">MODEL</span></td>${P.map(x => h`<td><strong style="color:var(--gold)">${x.tactical_suitability?.score != null ? Math.round(x.tactical_suitability.score) : 'n/a'}</strong><span class="faint">/100 · ${x.tactical_suitability?.data_coverage_pct ?? 0}% cov</span></td>`)}</tr>
          </tbody></table></div></div>
        <div class="card span2" style="grid-column:1/-1"><h3>Statistical comparison</h3><div class="table-wrap"><table><thead><tr><th>Metric</th>${P.map(x => h`<th class="num">${x.player.full_name}</th>`)}</tr></thead><tbody>
          ${data.profile.map(k => { const b = best(k); return h`<tr><td>${M.metrics[k].label}</td>${P.map(x => { const m = x.metrics.find(y => y.key === k); const isBest = m?.value != null && m.value === b && P.length > 1; return h`<td class="num" style="${isBest ? 'color:var(--gold);font-weight:700' : ''}">${fmtNum(m?.value, M.metrics[k].unit === '%' ? 1 : 2)}${m?.value != null ? M.metrics[k].unit : ''} <span class="faint" style="font-size:11px">${m?.percentile != null ? '(' + ordinal(m.percentile) + ')' : ''}</span></td>`; })}</tr>`; })}
          </tbody></table></div><p class="faint" style="font-size:12px">Gold = best value in this comparison. Percentiles in brackets are relative to the database pool.</p></div>
        <div class="card"><h3>Strengths & weaknesses <span class="badge b-purple">DATA-DERIVED</span></h3>${P.map((x, i) => h`<div style="margin-bottom:12px"><strong style="color:${PALETTE[i]}">${x.player.full_name}</strong>
          <div><span class="badge b-green">+</span> ${x.strengths.length ? x.strengths.join(' · ') : h`<span class="faint">none ≥70th pct</span>`}</div><div><span class="badge b-red">−</span> ${x.weaknesses.length ? x.weaknesses.join(' · ') : h`<span class="faint">none ≤30th pct</span>`}</div></div>`)}
          <p class="faint" style="font-size:12px">${P[0].strengths_weaknesses_basis}</p></div>
        <div class="card"><h3>Financial profile</h3>${P[0].financial.redacted ? h`<p class="muted">Fee and salary restricted for your role.</p>` : ''}<div class="table-wrap"><table><thead><tr><th></th>${P.map(x => h`<th>${x.player.full_name}</th>`)}</tr></thead><tbody>
          ${P[0].financial.redacted ? '' : h`<tr><td class="muted">Est. fee</td>${P.map(x => h`<td>${fmtMoney(x.financial.estimated_fee)}</td>`)}</tr><tr><td class="muted">Salary / yr</td>${P.map(x => h`<td>${fmtMoney(x.financial.salary_expectation)}</td>`)}</tr>`}
          <tr><td class="muted">Contract</td>${P.map(x => h`<td>${fmtDate(x.financial.contract_expiry)} <span class="faint">${x.financial.months_remaining != null ? x.financial.months_remaining + ' mo' : ''}</span></td>`)}</tr><tr><td class="muted">Availability</td>${P.map(x => h`<td>${availBadge(x.financial.availability)}</td>`)}</tr></tbody></table></div>
          <h3 style="margin-top:16px">Scouting assessments <span class="badge b-blue">SCOUT OPINION</span></h3><div class="table-wrap"><table><thead><tr><th></th>${P.map(x => h`<th>${x.player.full_name}</th>`)}</tr></thead><tbody>
          <tr><td class="muted">Match reports</td>${P.map(x => h`<td>${x.scouting.match_reports} <span class="faint">(${x.scouting.full_match_or_live_reports} full/live, ${x.scouting.highlights_only_reports} highlights)</span></td>`)}</tr>
          <tr><td class="muted">Avg overall rating</td>${P.map(x => h`<td>${x.scouting.avg_overall_rating ?? '—'}</td>`)}</tr>
          <tr><td class="muted">Latest report</td>${P.map(x => h`<td>${x.scouting.latest_report_id ? h`<a href="#/reports/${x.scouting.latest_report_id}">${label(x.scouting.latest_recommendation) || 'view'}</a>` : '—'}</td>`)}</tr></tbody></table></div></div>
      </div>
      <div class="notice" style="margin-top:16px"><ul class="caveats">${data.notes.map(n => h`<li>${n}</li>`)}</ul></div>`);
    $('#role').onchange = e => { compareView.role = e.target.value; compareView(); };
    $('#clr').onclick = () => { S.compare.clear(); saveCompare(); compareView(); };
  }

  // ------------------------------------------------------------------ pipeline
  async function pipelineView() {
    loading('pipeline', 'Recruitment pipeline');
    const f = pipelineView.filters || {};
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const [board, events] = await Promise.all([api('/api/pipeline?' + qs), api('/api/pipeline/events?limit=15')]);
    const M = S.meta;
    shell('pipeline', 'Recruitment pipeline', h`
      <div class="row" style="margin-bottom:14px"><select id="f-prio" style="width:auto"><option value="">All priorities</option>${M.priorities.map(p => h`<option ${f.priority === p ? raw('selected') : ''}>${p}</option>`)}</select>
        <select id="f-pos" style="width:auto"><option value="">All positions</option>${Object.keys(M.positions).map(p => h`<option ${f.position === p ? raw('selected') : ''}>${p}</option>`)}</select>
        <label class="check"><input type="checkbox" id="f-me" ${f.assigned_to_me ? raw('checked') : ''}> Assigned to me</label><span style="flex:1"></span><span class="muted">${board.total} players · click a card to record a decision</span></div>
      <div class="board">${board.stages.map(s => h`<div class="col ${s}"><div class="col-head">${label(s)}<span class="count">${board.columns[s].length}</span></div><div class="col-body">
        ${board.columns[s].map(e => h`<div class="pcard prio-${e.priority}" data-id="${e.id}"><div class="nm">${e.player_name}</div><div class="row" style="gap:6px">${posBadge(e.position)} <span class="muted">${e.age ?? '?'} · ${e.nationality}</span></div>
          <div class="faint" style="margin-top:4px">${e.club || '—'}</div><div class="row" style="gap:6px;margin-top:6px">${prioBadge(e.priority)} ${fictBadge(e.is_fictional)} ${e.estimated_fee != null ? h`<span class="badge b-gold">${fmtMoney(e.estimated_fee)}</span>` : ''}</div>
          ${e.assigned_scout_name ? h`<div class="faint" style="margin-top:4px;font-size:11.5px">👤 ${e.assigned_scout_name}</div>` : ''}</div>`)}
        ${board.columns[s].length ? '' : h`<div class="faint" style="text-align:center;padding:16px;font-size:12px">Empty</div>`}</div></div>`)}</div>
      <div class="card" style="margin-top:16px"><h3>Latest decisions</h3><ul class="timeline">${events.map(ev => h`<li><div><a href="#/players/${ev.player_id}">${ev.player_name}</a>: ${ev.from_stage ? h`${stageBadge(ev.from_stage)} → ` : ''}${stageBadge(ev.to_stage)}</div><div style="margin:3px 0">${ev.note || ''}</div><div class="when">${ev.user_name || '—'} · ${fmtDateTime(ev.created_at)}</div></li>`)}</ul></div>`);
    const setF = () => { pipelineView.filters = { priority: $('#f-prio').value, position: $('#f-pos').value, assigned_to_me: $('#f-me').checked ? 'true' : '' }; pipelineView(); };
    ['#f-prio', '#f-pos', '#f-me'].forEach(s => $(s).onchange = setF);
    const all = Object.values(board.columns).flat();
    $$('.pcard').forEach(c => c.onclick = async () => {
      const entry = await api(`/api/pipeline/${c.dataset.id}`);
      const users = await api('/api/users/directory');
      const m = modal(entry.player_name, h`<div class="row" style="margin-bottom:10px">${stageBadge(entry.stage)} ${prioBadge(entry.priority)} ${fictBadge(entry.is_fictional)} <a href="#/players/${entry.player_id}" data-close-link>Open player profile →</a></div>
        ${can('pipeline:move') ? h`<div class="form-grid"><div class="field"><label>Priority</label><select id="e-prio">${M.priorities.map(p => h`<option ${entry.priority === p ? raw('selected') : ''}>${p}</option>`)}</select></div>
        <div class="field"><label>Assigned scout</label><select id="e-scout"><option value="">—</option>${users.map(u => h`<option value="${u.id}" ${entry.assigned_scout_id === u.id ? raw('selected') : ''}>${u.full_name}</option>`)}</select></div></div><button type="button" class="btn sm" id="e-save">Save assignment</button>` : ''}
        <h3 style="margin-top:16px">History</h3><ul class="timeline">${entry.history.slice().reverse().map(ev => h`<li><div>${ev.from_stage ? h`${stageBadge(ev.from_stage)} → ` : ''}${stageBadge(ev.to_stage)}</div><div>${ev.note || ''}</div><div class="when">${ev.user_name || '—'} · ${fmtDateTime(ev.created_at)}</div></li>`)}</ul>`,
        { wide: true, foot: can('pipeline:move') && entry.stage !== 'signed' ? h`<button type="button" class="btn primary" id="e-move" style="margin-right:auto">Move stage…</button>` : '' });
      $$('[data-close-link]', m.root).forEach(a => a.onclick = () => m.close());
      if ($('#e-save')) $('#e-save').onclick = async () => { try { const sid = $('#e-scout').value; await api(`/api/pipeline/${entry.id}`, { method: 'PATCH', body: { priority: $('#e-prio').value, assigned_scout_id: sid ? Number(sid) : null } }); toast('Saved'); m.close(); pipelineView(); } catch (e) { toast(e.message, true); } };
      if ($('#e-move')) $('#e-move').onclick = () => moveDialog(entry, pipelineView);
    });
    void all;
  }

  // ------------------------------------------------------------------ video scouting
  async function videoView() {
    loading('video', 'Video scouting');
    const [vids, reps] = await Promise.all([api('/api/videos'), api('/api/match-reports')]);
    shell('video', 'Video scouting', h`
      <div class="notice">Video scouting links to <strong>licensed full-match footage</strong>. Highlights are flagged and never counted as complete match analysis. Add new footage from a player's <em>Video</em> tab.</div>
      <div class="grid g4" style="margin:14px 0"><div class="kpi"><div class="label">Videos linked</div><div class="value">${vids.length}</div></div><div class="kpi"><div class="label">Full matches</div><div class="value">${vids.filter(v => v.is_full_match).length}</div></div>
        <div class="kpi"><div class="label">Observations</div><div class="value">${vids.reduce((a, v) => a + v.observations.length, 0)}</div></div><div class="kpi gold"><div class="label">Match reports</div><div class="value">${reps.length}</div><div class="sub">${reps.filter(r => !r.is_complete_match_analysis).length} highlights-only</div></div></div>
      <div class="tabs"><button class="tab active" data-t="v">Footage & observations</button><button class="tab" data-t="r">Match reports</button></div>
      <div id="vbody"></div>`);
    const show = t => {
      $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.t === t));
      const el = $('#vbody');
      if (t === 'v') { el.innerHTML = (vids.length ? vids.map(videoCard) : [h`<div class="empty">No footage linked yet.</div>`]).map(x => x.s).join(''); bindVideoCards(el, videoView); }
      else el.innerHTML = (reps.length ? h`<div class="table-wrap"><table><thead><tr><th>Date</th><th>Player</th><th>Type</th><th>Scout</th><th class="num">Overall</th><th>Recommendation</th></tr></thead><tbody>${reps.map(r => h`<tr class="clickable" data-href="#/players/${r.player_id}/match"><td>${fmtDate(r.match_date)}</td><td>#${r.player_id}</td><td>${label(r.observation_type)} ${r.is_complete_match_analysis ? '' : h`<span class="badge b-amber">highlights</span>`}</td><td>${r.scout_name || '—'}</td><td class="num">${r.overall_rating ?? '—'}</td><td>${label(r.recommendation)}</td></tr>`)}</tbody></table></div>` : h`<div class="empty">No match reports.</div>`).s;
      bindRowLinks(el);
    };
    $$('.tab').forEach(b => b.onclick = () => show(b.dataset.t));
    show('v');
  }

  // ------------------------------------------------------------------ reports
  async function reportsView() {
    loading('reports', 'Scouting reports');
    const reps = await api('/api/reports');
    shell('reports', 'Scouting reports', h`<div class="notice">Generate a draft from any player page. Drafts label every statement: <span class="badge b-green">DATA</span> verified source data, <span class="badge b-blue">SCOUT</span> scout opinion, <span class="badge b-purple">MODEL</span> platform calculation, <span class="badge b-amber">FICTIONAL</span> demo data, <span class="badge b-red">INPUT REQUIRED</span> gaps for staff.</div><div class="card" style="margin-top:14px">${reportsTable(reps)}</div>`);
    bindRowLinks();
  }

  async function reportDetailView(id) {
    loading('reports', 'Report');
    const r = await api(`/api/reports/${id}`);
    const editable = r.status !== 'final' && can('reports:write');
    const M = S.meta;
    const secs = Object.entries(r.sections).filter(([k]) => !k.startsWith('_'));
    const meta = r.sections._meta || {};
    const actions = h`<a class="btn" href="#/players/${r.player_id}">Player</a><button class="btn" id="md">Export .md</button><button class="btn" onclick="window.print()">Print</button>${editable && can('reports:finalize') ? h`<button class="btn gold" id="fin">Finalise</button>` : ''}${can('reports:write') && (r.status !== 'final' || can('users:manage')) ? h`<button class="btn danger" id="del">Delete</button>` : ''}`;
    shell('reports', r.title, h`
      ${meta.is_fictional ? h`<div class="fict-banner"><strong>FICTIONAL SAMPLE DATA.</strong> This report is a demonstration and must not inform real decisions.</div>` : ''}
      <div class="card"><div class="row" style="justify-content:space-between"><div><h1>${r.title}</h1><div class="muted">${r.author_name || '—'} · created ${fmtDateTime(r.created_at)} · updated ${fmtDateTime(r.updated_at)} ${meta.season ? h`· season ${meta.season}` : ''}</div></div>
        <div class="row"><span class="badge ${r.status === 'final' ? 'b-gold' : 'b-grey'}">${r.status.toUpperCase()}</span></div></div>
        <form id="hdr" class="form-grid" style="margin-top:14px">
          <div class="field"><label>Recruitment recommendation</label><select name="recommendation" ${editable ? '' : raw('disabled')}><option value="">— not set —</option>${M.recommendations.map(x => h`<option value="${x}" ${r.recommendation === x ? raw('selected') : ''}>${label(x)}</option>`)}</select></div>
          <div class="field"><label>Potential (1–10, scout opinion)</label><input name="potential_rating" type="number" min="1" max="10" value="${r.potential_rating ?? ''}" ${editable ? '' : raw('disabled')}></div>
          <div class="field"><label>Overall risk</label><select name="risk_level" ${editable ? '' : raw('disabled')}><option value="">—</option>${['low', 'medium', 'high'].map(x => h`<option ${r.risk_level === x ? raw('selected') : ''}>${x}</option>`)}</select></div>
          ${editable ? h`<div class="field" style="align-self:end"><button class="btn primary" type="submit">Save</button></div>` : ''}</form></div>
      ${secs.map(([key, sec]) => h`<div class="card"><div class="card-head"><h2>${sec.title}</h2>${editable ? h`<button class="btn sm add-item" data-sec="${key}">+ Add scout assessment</button>` : ''}</div>
        ${(sec.items || []).map((it, i) => h`<div class="ev">${evBadge(it.evidence_type)}<div style="flex:1">${it.text}${it.source ? h`<span class="src">Source: ${it.source}</span>` : ''}</div>${editable && it.evidence_type !== 'verified_data' && it.evidence_type !== 'fictional_sample' ? h`<button class="btn ghost sm rm-item" data-sec="${key}" data-i="${i}" title="Remove">✕</button>` : ''}</div>`)}</div>`)}
      <div class="card"><h4>Evidence legend</h4><div class="row">${Object.entries(meta.legend || {}).map(([k, v]) => h`<span>${evBadge(k)} <span class="muted" style="font-size:12px">${v}</span></span>`)}</div><p class="faint" style="font-size:12px;margin-top:8px">${meta.generator || ''} · ${meta.generated_on || ''}. The platform never makes signing decisions.</p></div>`, actions);
    const save = async body => { try { await api(`/api/reports/${id}`, { method: 'PATCH', body }); toast('Report saved'); reportDetailView(id); } catch (e) { toast(e.message, true); } };
    if ($('#hdr') && editable) $('#hdr').onsubmit = e => { e.preventDefault(); const b = formData(e.target); save({ recommendation: b.recommendation, potential_rating: b.potential_rating, risk_level: b.risk_level }); };
    $('#md').onclick = () => download(`/api/reports/${id}/export.md`, `report_${id}.md`);
    if ($('#fin')) $('#fin').onclick = async () => { if (!confirm('Finalise this report? It will be locked.')) return; try { await api(`/api/reports/${id}/finalize`, { method: 'POST' }); toast('Report finalised'); reportDetailView(id); } catch (e) { toast(e.message, true); } };
    if ($('#del')) $('#del').onclick = async () => { if (!confirm('Delete this report?')) return; try { await api(`/api/reports/${id}`, { method: 'DELETE' }); location.hash = '#/reports'; } catch (e) { toast(e.message, true); } };
    $$('.add-item').forEach(b => b.onclick = () => modal('Add scout assessment', h`<p class="muted">This text will be labelled as <span class="badge b-blue">SCOUT</span> opinion and attributed to you.</p><div class="field"><label>Assessment</label><textarea name="text" required style="min-height:120px"></textarea></div><div class="field"><label>Evidence basis (e.g. "3 full matches + live vs X")</label><input name="basis"></div>`,
      { onSubmit: async f => { const d = formData(f); if (!d.text) throw new Error('Text required'); const sections = structuredClone(r.sections); sections[b.dataset.sec].items.unshift({ evidence_type: 'scout_opinion', text: d.text, source: `${S.user.full_name}${d.basis ? ' — ' + d.basis : ''}` }); await save({ sections }); } }));
    $$('.rm-item').forEach(b => b.onclick = () => { const sections = structuredClone(r.sections); sections[b.dataset.sec].items.splice(Number(b.dataset.i), 1); save({ sections }); });
  }

  // ------------------------------------------------------------------ import
  async function importView() {
    loading('import', 'Data import');
    refCache = null;
    const { sources } = await refs();
    shell('import', 'Data import', h`
      <div class="notice warn"><strong>Data governance:</strong> import only data your organization is licensed to use. Do not import scraped data or redistribute licensed provider data. Every import is linked to a registered data source and logged in the audit trail. Empty cells are stored as "not available", never zero.</div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h3>1 · Data sources</h3><div class="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Licence notes</th></tr></thead><tbody>${sources.map(s => h`<tr><td>${s.name} ${fictBadge(s.is_fictional)}</td><td class="muted">${label(s.source_type)}</td><td style="white-space:normal" class="faint">${s.license_notes || '—'}</td></tr>`)}</tbody></table></div>
          <div class="row end" style="margin-top:10px"><button class="btn sm" id="new-src">+ Register data source</button></div></div>
        <div class="card"><h3>2 · Upload CSV</h3><form id="imp">
          <div class="form-grid"><div class="field"><label>Import type</label><select name="kind"><option value="players">Player profiles</option><option value="stats">Season statistics</option></select></div>
          <div class="field"><label>Data source *</label><select name="data_source_id" required>${sources.map(s => h`<option value="${s.id}">${s.name}</option>`)}</select></div></div>
          <div class="field"><label>CSV file (UTF-8, max 10 MB)</label><input type="file" name="file" accept=".csv,text/csv" required></div>
          <label class="check"><input type="checkbox" name="dry_run" checked> Dry run (validate only, no changes)</label>
          <div class="row end" style="margin-top:10px"><button type="button" class="btn sm" id="tpl-p">Players template</button><button type="button" class="btn sm" id="tpl-s">Stats template</button><button class="btn primary" type="submit">Run import</button></div></form>
          <div id="imp-res"></div></div>
        <div class="card span2" style="grid-column:1/-1"><h3>API integration</h3><p class="muted">Licensed provider feeds and ETL jobs can push data to <code>POST /api/import/json</code> with <code>{"data_source_id", "players": [...], "stats": [...]}</code> using the same column names as the CSV templates. Interactive API documentation: <a href="/docs" target="_blank" rel="noopener">/docs</a> (OpenAPI: <a href="/openapi.json" target="_blank" rel="noopener">/openapi.json</a>).</p></div>
      </div>`);
    $('#tpl-p').onclick = () => download('/api/import/templates/players.csv', 'players_template.csv');
    $('#tpl-s').onclick = () => download('/api/import/templates/stats.csv', 'stats_template.csv');
    $('#new-src').onclick = () => modal('Register data source', h`<div class="field"><label>Name *</label><input name="name" required></div><div class="field"><label>Type</label><select name="source_type">${S.meta.source_types.filter(t => t !== 'fictional_sample').map(t => h`<option value="${t}">${label(t)}</option>`)}</select></div><div class="field"><label>URL</label><input name="url"></div><div class="field"><label>Licence / usage terms *</label><textarea name="license_notes" required placeholder="Contract reference, permitted use, redistribution restrictions"></textarea></div>`,
      { onSubmit: async f => { await api('/api/data-sources', { method: 'POST', body: clean(formData(f)) }); toast('Source registered'); importView(); } });
    $('#imp').onsubmit = async e => {
      e.preventDefault();
      const f = e.target; const fd = new FormData();
      fd.append('file', f.file.files[0]); fd.append('data_source_id', f.data_source_id.value); fd.append('dry_run', f.dry_run.checked ? 'true' : 'false');
      try {
        const r = await api(`/api/import/${f.kind.value}`, { method: 'POST', form: fd });
        $('#imp-res').innerHTML = h`<div class="notice ${r.errors.length ? 'warn' : 'info'}" style="margin-top:12px"><strong>${r.dry_run ? 'Dry run' : 'Import'} complete:</strong> ${r.rows} rows · ${r.created} new · ${r.updated} updated · ${r.errors.length} errors${r.dry_run ? ' — nothing was saved' : ''}.
          ${r.errors.length ? h`<ul class="caveats">${r.errors.slice(0, 30).map(er => h`<li>Row ${er.row}: ${er.error}</li>`)}</ul>` : ''}</div>`.s;
        refCache = null;
      } catch (err) { toast(err.message, true); }
    };
  }

  // ------------------------------------------------------------------ public account pages
  function publicCard(inner) {
    $('#app').innerHTML = h`<div class="login-wrap"><div class="login-card"><div class="brand">${raw(shield)}<div class="brand-name" style="font-size:18px">RAJA SCOUT INTELLIGENCE</div></div>${inner}<p class="faint" style="font-size:11px;margin-top:14px;text-align:center">${NOT_AFFILIATED}</p></div></div>`.s;
  }
  async function inviteView(token) {
    let inv;
    try { inv = await api(`/api/auth/invitations/${encodeURIComponent(token)}`); }
    catch (e) { return publicCard(h`<div class="notice err">${e.message}</div><a class="btn" href="#/login">Go to sign in</a>`); }
    publicCard(h`<h2 style="text-align:center">Join ${inv.organization}</h2>
      <p class="muted" style="text-align:center">Invitation for <strong>${inv.email}</strong> as ${label(inv.role)}.</p>
      <form id="acc">${inv.existing_account ? h`<div class="notice info">You already have an account. Confirm with your current password to add this organization.</div>`
        : h`<div class="field"><label>Full name</label><input name="full_name" required minlength="2"></div>`}
      <div class="field"><label>${inv.existing_account ? 'Current password' : 'Choose a password (≥10 characters, letters and digits)'}</label><input name="password" type="password" required autocomplete="${inv.existing_account ? 'current-password' : 'new-password'}"></div>
      <button class="btn primary" style="width:100%" type="submit">${inv.existing_account ? 'Join organization' : 'Create account'}</button></form>`);
    $('#acc').onsubmit = async e => {
      e.preventDefault();
      try {
        const r = await api('/api/auth/invitations/accept', { method: 'POST', body: { token, ...clean(formData(e.target)) } });
        setToken(r.access_token); S.user = null; location.hash = '#/dashboard';
      } catch (err) { toast(err.message, true); }
    };
  }
  function resetView(token) {
    publicCard(h`<h2 style="text-align:center">Set a new password</h2><form id="rst"><div class="field"><label>New password (≥10 characters, letters and digits)</label><input name="new_password" type="password" required autocomplete="new-password"></div><button class="btn primary" style="width:100%" type="submit">Save password</button></form>`);
    $('#rst').onsubmit = async e => {
      e.preventDefault();
      try { await api('/api/auth/password-reset', { method: 'POST', body: { token, ...formData(e.target) } }); toast('Password updated — please sign in'); logout(); }
      catch (err) { toast(err.message, true); }
    };
  }
  function showLink(title, url, note) {
    modal(title, h`<p class="muted">${note}</p><div class="field"><input id="link-out" readonly value="${url}"></div>`,
      { foot: h`<button type="button" class="btn primary" id="copy-link" style="margin-right:auto">Copy link</button>` });
    $('#copy-link').onclick = async () => { try { await navigator.clipboard.writeText(url); toast('Link copied'); } catch (_) { $('#link-out').select(); } };
  }

  const lim = v => v == null ? 'unlimited' : v;
  function planCard(x) {
    if (!x) return '';
    const u = x.usage, l = x.limits;
    const meter = (used, cap) => cap == null ? '' : h`<div class="bar-track" style="margin-top:4px"><div class="bar-fill ${used > cap ? '' : 'gold'}" style="width:${Math.min(100, used / Math.max(1, cap) * 100)}%"></div></div>`;
    return h`<div class="card span2" style="grid-column:1/-1"><div class="card-head"><h3>Plan & usage</h3><span class="badge ${x.writable ? 'b-green' : 'b-red'}">${label(x.effective_status)}</span></div>
      <div class="grid g3"><div><div class="muted">Plan</div><div style="font-size:20px;font-weight:700">${x.plan_name || '—'}</div>
        ${x.trial_ends_at && x.effective_status === 'trialing' ? h`<div class="faint">Trial ends ${fmtDate(x.trial_ends_at)}</div>` : ''}${x.current_period_end ? h`<div class="faint">Paid until ${fmtDate(x.current_period_end)}</div>` : ''}</div>
      <div><div class="muted">Seats (members + pending invitations)</div><div style="font-size:20px;font-weight:700">${u.seats_used} / ${lim(l.seats)}</div>${meter(u.seats_used, l.seats)}</div>
      <div><div class="muted">Private players</div><div style="font-size:20px;font-weight:700">${u.private_players} / ${lim(l.private_players)}</div>${meter(u.private_players, l.private_players)}</div></div>
      <p class="faint" style="font-size:12px;margin-top:10px">Included: ${l.features.map(f => label(f)).join(' · ') || '—'}. Plan changes are handled by your account manager.</p></div>`;
  }

  // ------------------------------------------------------------------ platform console (SaaS operator)
  async function platformView() {
    loading('platform', 'Platform console');
    const [orgs, plans] = await Promise.all([api('/api/platform/organizations'), api('/api/platform/plans')]);
    const statusBadge = st => h`<span class="badge ${st === 'active' || st === 'trialing' || st === 'demo' ? 'b-green' : st === 'past_due' ? 'b-amber' : 'b-red'}">${label(st)}</span>`;
    shell('platform', 'Platform console', h`
      <div class="notice">Operator view: organization metadata, subscriptions and usage counts only. Scouting data of customer organizations is not accessible from here.</div>
      <div class="card" style="margin-top:14px"><div class="card-head"><h3>Organizations (${orgs.length})</h3><button class="btn primary sm" id="new-org">+ New organization</button></div>
      <div class="table-wrap"><table><thead><tr><th>Organization</th><th>Type</th><th>Plan</th><th>Status</th><th>Trial / paid until</th><th class="num">Seats</th><th class="num">Players</th><th></th></tr></thead><tbody>
      ${orgs.map(o => { const x = o.subscription; return h`<tr><td><strong>${o.name}</strong><div class="faint">${o.slug} · ${o.country || '—'} · ${o.currency}</div></td>
        <td>${o.is_demo ? h`<span class="badge b-amber">demo</span>` : h`<span class="badge b-blue">customer</span>`}${o.status !== 'active' ? h` <span class="badge b-red">${label(o.status)}</span>` : ''}</td>
        <td>${x.plan_name || '—'}</td><td>${statusBadge(x.effective_status)}</td>
        <td class="faint">${x.effective_status === 'trialing' ? fmtDate(x.trial_ends_at) : fmtDate(x.current_period_end)}</td>
        <td class="num">${x.usage.seats_used} / ${lim(x.limits.seats)}</td><td class="num">${x.usage.private_players} / ${lim(x.limits.private_players)}</td>
        <td>${o.is_demo ? '' : h`<button class="btn sm sub-edit" data-id="${o.id}">Subscription</button>`}
          ${o.status === 'pending_deletion' ? h`<button class="btn sm ghost del-cancel" data-id="${o.id}">Cancel deletion</button> <button class="btn sm danger del-purge" data-id="${o.id}" data-slug="${o.slug}">Purge</button>`
            : h`<button class="btn sm ghost del-sched" data-id="${o.id}" data-name="${o.name}">Delete…</button>`}</td></tr>`; })}
      </tbody></table></div></div>`);
    $('#new-org').onclick = () => modal('New organization', h`<div class="form-grid">
      <div class="field"><label>Name *</label><input name="name" required></div><div class="field"><label>Slug * (lowercase, hyphens)</label><input name="slug" required pattern="[a-z0-9-]+"></div>
      <div class="field"><label>Country</label><input name="country"></div><div class="field"><label>Currency</label><input name="currency" value="MAD" maxlength="3"></div>
      <div class="field"><label>Plan</label><select name="plan">${plans.map(p => h`<option value="${p.code}" ${p.code === 'club_pro' ? raw('selected') : ''}>${p.name}</option>`)}</select></div>
      <div class="field"><label>Trial days</label><input name="trial_days" type="number" value="30" min="0" max="90"></div>
      <div class="field"><label>First administrator email *</label><input name="admin_email" type="email" required></div></div>`,
      { submitLabel: 'Create', onSubmit: async f => { const r = await api('/api/platform/organizations', { method: 'POST', body: clean(formData(f)) }); showLink('First administrator invitation', r.admin_invite_url, `Send this link to the club's administrator. ${r.name} starts a ${r.subscription.plan_name} trial.`); platformView(); return true; } });
    $$('.sub-edit').forEach(b => b.onclick = () => {
      const o = orgs.find(x => x.id === Number(b.dataset.id)); const x = o.subscription;
      const d = v => v ? String(v).slice(0, 10) : '';
      modal(`Subscription — ${o.name}`, h`<div class="form-grid">
        <div class="field"><label>Plan</label><select name="plan">${plans.map(p => h`<option value="${p.code}" ${p.code === x.plan ? raw('selected') : ''}>${p.name}</option>`)}</select></div>
        <div class="field"><label>Status</label><select name="status">${['trialing', 'active', 'past_due', 'suspended', 'canceled', 'expired'].map(st => h`<option ${st === x.status ? raw('selected') : ''}>${st}</option>`)}</select></div>
        <div class="field"><label>Trial ends</label><input name="trial_ends_at" type="date" value="${d(x.trial_ends_at)}"></div>
        <div class="field"><label>Paid until (period end)</label><input name="current_period_end" type="date" value="${d(x.current_period_end)}"></div>
        <div class="field"><label>Seat override</label><input name="seats_override" type="number" min="0" placeholder="plan default"></div>
        <div class="field"><label>Player override</label><input name="players_override" type="number" min="0" placeholder="plan default"></div></div>
        <p class="faint" style="font-size:12px">Manual billing: record invoices / bank transfers by setting status "active" and the paid-until date.</p>`,
        { onSubmit: async f => { const v = formData(f); const body = { plan: v.plan, status: v.status };
          if (v.trial_ends_at) body.trial_ends_at = v.trial_ends_at + 'T23:59:59Z'; if (v.current_period_end) body.current_period_end = v.current_period_end + 'T23:59:59Z';
          if (v.seats_override != null) body.seats_override = v.seats_override; if (v.players_override != null) body.players_override = v.players_override;
          await api(`/api/platform/organizations/${o.id}/subscription`, { method: 'PATCH', body }); toast('Subscription updated'); platformView(); } });
    });
    $$('.del-sched').forEach(b => b.onclick = async () => { if (!confirm(`Schedule deletion of ${b.dataset.name}? All members lose access immediately; data is kept until purged.`)) return; await api(`/api/platform/organizations/${b.dataset.id}/schedule-deletion`, { method: 'POST' }); platformView(); });
    $$('.del-cancel').forEach(b => b.onclick = async () => { await api(`/api/platform/organizations/${b.dataset.id}/cancel-deletion`, { method: 'POST' }); platformView(); });
    $$('.del-purge').forEach(b => b.onclick = async () => {
      const typed = prompt(`PERMANENT deletion. Type the slug "${b.dataset.slug}" to purge all of its data:`);
      if (typed == null) return;
      try { const r = await api(`/api/platform/organizations/${b.dataset.id}/purge`, { method: 'POST', body: { confirm_slug: typed } }); toast(`Purged ${r.slug}`); platformView(); } catch (e) { toast(e.message, true); }
    });
  }

  // ------------------------------------------------------------------ organization settings
  async function organizationView() {
    loading('organization', 'Organization');
    const o = await api('/api/organization');
    const st = o.settings || {};
    const opt = (list, cur) => list.map(x => h`<option ${x === cur ? raw('selected') : ''}>${x}</option>`);
    const langs = { en: 'English', fr: 'Français', ar: 'العربية' };
    shell('organization', 'Organization', h`<div class="grid g2">
      <form class="card" id="org-form"><h3>Identity</h3>
        <div class="form-grid"><div class="field"><label>Organization name *</label><input name="name" value="${o.name}" required></div>
        <div class="field"><label>Short name</label><input name="short_name" value="${o.short_name || ''}" maxlength="40"></div>
        <div class="field"><label>Country</label><input name="country" value="${o.country || ''}"></div>
        <div class="field"><label>Primary language</label><select name="primary_language">${o.options.languages.map(l => h`<option value="${l}" ${l === o.primary_language ? raw('selected') : ''}>${langs[l] || l}</option>`)}</select></div>
        <div class="field"><label>Currency (fees, salaries, budgets)</label><select name="currency">${opt(o.options.currencies, o.currency)}</select></div>
        <div class="field"><label>Timezone</label><input name="timezone" value="${o.timezone}" placeholder="Africa/Casablanca"></div></div>
        <h3 style="margin-top:8px">Settings</h3>
        <div class="form-grid"><div class="field"><label>Home league (used in report risk notes)</label><input name="home_league" value="${st.home_league || ''}" placeholder="e.g. Botola Pro"></div>
        <div class="field"><label>Accent colour</label><input name="accent_color" type="color" value="${st.accent_color || '#d4af37'}" style="height:38px"></div></div>
        <div class="field"><label>Report footer</label><textarea name="report_footer" maxlength="300">${st.report_footer || ''}</textarea></div>
        <p class="faint" style="font-size:12px">Changing the currency does not convert existing amounts — they are reinterpreted in the new currency.</p>
        <div class="row end"><button class="btn primary" type="submit">Save</button></div></form>
      <div class="card"><h3>Logo</h3>
        <div class="row" style="align-items:center;gap:16px;margin:8px 0 14px">${o.logo_data_url ? h`<img src="${o.logo_data_url}" alt="Logo" style="width:96px;height:96px;object-fit:contain;background:var(--bg-2);border:1px solid var(--border);border-radius:12px">` : h`<div class="org-logo ph" style="width:96px;height:96px;font-size:30px">${initials(o.short_name || o.name)}</div>`}
          <div class="muted" style="font-size:12.5px">PNG, JPEG or WebP, max 256 KB.<br>SVG is not accepted for security reasons.</div></div>
        <div class="row"><input type="file" id="logo-file" accept="image/png,image/jpeg,image/webp" style="flex:1"><button class="btn primary" id="logo-up">Upload</button>${o.logo_data_url ? h`<button class="btn danger" id="logo-del">Remove</button>` : ''}</div>
        <h3 style="margin-top:22px">Workspace</h3><dl class="kv"><dt>Identifier</dt><dd><code>${o.slug}</code></dd><dt>Type</dt><dd>${o.is_demo ? h`<span class="badge b-amber">Demo (fictional data)</span>` : h`<span class="badge b-green">Customer</span>`}</dd><dt>Status</dt><dd>${label(o.status)}</dd></dl>
        <p class="faint" style="font-size:11.5px;margin-top:14px">${NOT_AFFILIATED}</p></div>
      ${planCard(S.sub)}</div>`);
    const refreshMe = async () => { S.user = await api('/api/auth/me'); applyBranding(); organizationView(); };
    $('#org-form').onsubmit = async e => {
      e.preventDefault();
      const f = formData(e.target);
      const body = { name: f.name, short_name: f.short_name, country: f.country, primary_language: f.primary_language, currency: f.currency,
        timezone: f.timezone, settings: { home_league: f.home_league || '', report_footer: f.report_footer || '', accent_color: f.accent_color === '#d4af37' ? '' : f.accent_color } };
      try { await api('/api/organization', { method: 'PATCH', body }); toast('Organization updated'); refreshMe(); } catch (err) { toast(err.message, true); }
    };
    $('#logo-up').onclick = async () => {
      const file = $('#logo-file').files[0]; if (!file) return toast('Choose an image first', true);
      const fd = new FormData(); fd.append('file', file);
      try { await api('/api/organization/logo', { method: 'POST', form: fd }); toast('Logo updated'); refreshMe(); } catch (err) { toast(err.message, true); }
    };
    if ($('#logo-del')) $('#logo-del').onclick = async () => { try { await api('/api/organization/logo', { method: 'DELETE' }); refreshMe(); } catch (err) { toast(err.message, true); } };
  }

  // ------------------------------------------------------------------ admin
  async function adminView() {
    loading('admin', 'Administration');
    const [users, roles, invites, logs, budgets] = await Promise.all([
      can('users:manage') ? api('/api/users') : null, api('/api/users/roles'),
      can('users:manage') ? api('/api/users/invitations') : null,
      can('audit:read') ? api('/api/admin/audit-logs?limit=150') : null, can('financials:read') ? api('/api/budgets') : null]);
    const M = S.meta;
    shell('admin', 'Administration', h`<div class="grid g2">
      ${users ? h`<div class="card span2" style="grid-column:1/-1"><div class="card-head"><h3>Members</h3><div class="row"><button class="btn sm primary" id="invite-user">+ Invite member</button><button class="btn sm" id="new-user" title="Create an account with a temporary password">Create directly</button></div></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Region</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>
        ${users.map(u => h`<tr><td>${u.full_name}</td><td class="muted">${u.email}</td><td>${M.roles[u.role]}</td><td>${u.region || '—'}</td><td>${u.is_active ? h`<span class="badge b-green">active</span>` : h`<span class="badge b-red">disabled</span>`}</td><td class="faint">${fmtDateTime(u.last_login_at)}</td><td><button class="btn sm edit-user" data-id="${u.id}">Edit</button> <button class="btn sm ghost reset-user" data-id="${u.id}">Reset link</button></td></tr>`)}</tbody></table></div></div>` : ''}
      ${invites ? h`<div class="card span2" style="grid-column:1/-1"><h3>Invitations</h3><div id="invites"></div></div>` : ''}
      ${budgets ? h`<div class="card"><div class="card-head"><h3>Recruitment budgets</h3>${can('budget:manage') ? h`<button class="btn sm" id="budget">Set budget</button>` : ''}</div><div class="table-wrap"><table><thead><tr><th>Season</th><th class="num">Transfer</th><th class="num">Wages</th><th>Notes</th></tr></thead><tbody>${budgets.map(b => h`<tr><td>${b.season}</td><td class="num">${fmtMoney(b.transfer_budget)}</td><td class="num">${fmtMoney(b.wage_budget)}</td><td class="muted">${b.notes || ''}</td></tr>`)}</tbody></table></div></div>` : ''}
      <div class="card"><h3>Backup & export</h3><p class="muted">JSON export of all of this organization's data (password hashes excluded). For full database backups use <code>scripts/backup.sh</code> (pg_dump) — see docs/DEPLOYMENT.md.</p>
        <div class="row">${can('backup:run') ? h`<button class="btn primary" id="exp">Download full export (JSON)</button>` : ''}<button class="btn" id="exp-csv">Players CSV</button></div></div>
      <div class="card span2" style="grid-column:1/-1"><h3>Role permissions</h3><div class="table-wrap"><table><thead><tr><th>Permission</th>${roles.map(r => h`<th>${r.label}</th>`)}</tr></thead><tbody>
        ${[...new Set(roles.flatMap(r => r.permissions))].sort().map(p => h`<tr><td><code>${p}</code></td>${roles.map(r => h`<td>${r.permissions.includes(p) ? h`<span style="color:var(--green)">✓</span>` : h`<span class="faint">·</span>`}</td>`)}</tr>`)}</tbody></table></div></div>
      ${logs ? h`<div class="card span2" style="grid-column:1/-1"><div class="card-head"><h3>Audit log</h3><span class="muted">latest ${logs.length} entries</span></div><div class="table-wrap" style="max-height:520px;overflow:auto"><table><thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Details</th><th>IP</th></tr></thead><tbody>
        ${logs.map(l => h`<tr><td class="faint">${fmtDateTime(l.created_at)}</td><td>${l.user_email || '—'}</td><td><code>${l.action}</code></td><td class="muted">${l.entity_type || ''}${l.entity_id ? ' #' + l.entity_id : ''}</td><td style="white-space:normal;max-width:420px;font-size:12px" class="faint">${l.details ? JSON.stringify(l.details).slice(0, 220) : ''}</td><td class="faint">${l.ip_address || ''}</td></tr>`)}</tbody></table></div></div>` : ''}
    </div>`);
    if ($('#exp')) $('#exp').onclick = () => download('/api/admin/export', `raja_scout_export_${new Date().toISOString().slice(0, 10)}.json`);
    $('#exp-csv').onclick = () => download('/api/players/export.csv', 'players.csv');
    if ($('#budget')) $('#budget').onclick = () => modal('Set recruitment budget', h`<div class="field"><label>Season *</label><input name="season" required placeholder="2026-27"></div><div class="field"><label>Transfer budget (${currency()}) *</label><input name="transfer_budget" type="number" min="0" required></div><div class="field"><label>Wage budget (${currency()} / yr)</label><input name="wage_budget" type="number" min="0"></div><div class="field"><label>Notes</label><textarea name="notes"></textarea></div>`,
      { onSubmit: async f => { await api('/api/budgets', { method: 'PUT', body: clean(formData(f)) }); toast('Budget saved'); adminView(); } });
    const userForm = u => modal(u ? `Edit ${u.full_name}` : 'New user', h`<div class="form-grid">${u ? '' : h`<div class="field"><label>Email *</label><input name="email" type="email" required></div>`}
      <div class="field"><label>Full name *</label><input name="full_name" value="${u?.full_name || ''}" required></div><div class="field"><label>Role *</label><select name="role">${Object.entries(M.roles).map(([k, t]) => h`<option value="${k}" ${u?.role === k ? raw('selected') : ''}>${t}</option>`)}</select></div>
      <div class="field"><label>Region</label><input name="region" value="${u?.region || ''}"></div><div class="field"><label>${u ? 'New password (optional)' : 'Password *'}</label><input name="password" type="password" autocomplete="new-password" ${u ? '' : raw('required')}></div></div>
      ${u ? h`<label class="check"><input type="checkbox" name="is_active" ${u.is_active ? raw('checked') : ''}> Active</label>` : ''}`,
      { onSubmit: async f => { const b = formData(f); if (u) { if (!b.password) delete b.password; await api(`/api/users/${u.id}`, { method: 'PATCH', body: b }); } else await api('/api/users', { method: 'POST', body: clean(b) }); toast('User saved'); adminView(); } });
    if ($('#new-user')) $('#new-user').onclick = () => userForm(null);
    if ($('#invite-user')) $('#invite-user').onclick = () => modal('Invite a member', h`<p class="muted">Creates a single-use link (valid 7 days). The person chooses their own password.</p>
      <div class="form-grid"><div class="field"><label>Email *</label><input name="email" type="email" required></div><div class="field"><label>Role *</label><select name="role">${Object.entries(M.roles).map(([k, t]) => h`<option value="${k}">${t}</option>`)}</select></div><div class="field"><label>Region</label><input name="region"></div></div>`,
      { submitLabel: 'Create invitation', onSubmit: async f => { const r = await api('/api/users/invitations', { method: 'POST', body: clean(formData(f)) }); showLink('Invitation link', r.invite_url, `Send this link privately to ${r.email}. It is shown only once and expires ${fmtDateTime(r.expires_at)}.`); adminInvites(); return true; } });
    $$('.reset-user').forEach(b => b.onclick = async () => {
      try { const r = await api(`/api/users/${b.dataset.id}/password-reset-link`, { method: 'POST' }); showLink('Password reset link', r.reset_url, `Single use, valid ${r.expires_in_hours} hours. Existing sessions are signed out when it is used.`); }
      catch (e) { toast(e.message, true); }
    });
    const adminInvites = async () => {
      const list = await api('/api/users/invitations'); const el = $('#invites'); if (!el) return;
      el.innerHTML = (list.length ? h`<div class="table-wrap"><table><thead><tr><th>Email</th><th>Role</th><th>Status</th><th>Expires</th><th></th></tr></thead><tbody>${list.map(i => h`<tr><td>${i.email}</td><td>${M.roles[i.role]}</td><td><span class="badge ${i.status === 'pending' ? 'b-blue' : i.status === 'accepted' ? 'b-green' : 'b-grey'}">${i.status}</span></td><td class="faint">${fmtDateTime(i.expires_at)}</td><td>${i.status === 'pending' ? h`<button class="btn sm ghost rev-inv" data-id="${i.id}">Revoke</button>` : ''}</td></tr>`)}</tbody></table></div>` : h`<div class="empty">No invitations yet.</div>`).s;
      $$('.rev-inv', el).forEach(b => b.onclick = async () => { await api(`/api/users/invitations/${b.dataset.id}`, { method: 'DELETE' }); adminInvites(); });
    };
    if (invites) adminInvites();
    $$('.edit-user').forEach(b => b.onclick = () => userForm(users.find(u => u.id === Number(b.dataset.id))));
  }

  // ------------------------------------------------------------------ router
  const ROUTES = [
    [/^#\/login$/, () => loginView()],
    [/^#\/dashboard$/, () => dashboardView()],
    [/^#\/players$/, () => playersView()],
    [/^#\/players\/new$/, () => playerFormView(null)],
    [/^#\/players\/(\d+)\/edit$/, m => playerFormView(Number(m[1]))],
    [/^#\/players\/(\d+)(?:\/(\w+))?$/, m => playerDetailView(Number(m[1]), m[2] || 'overview')],
    [/^#\/compare$/, () => compareView()],
    [/^#\/pipeline$/, () => pipelineView()],
    [/^#\/video$/, () => videoView()],
    [/^#\/reports$/, () => reportsView()],
    [/^#\/reports\/(\d+)$/, m => reportDetailView(Number(m[1]))],
    [/^#\/import$/, () => importView()],
    [/^#\/admin$/, () => adminView()],
    [/^#\/organization$/, () => organizationView()],
    [/^#\/platform$/, () => platformView()],
  ];

  async function route() {
    $('#modal-root').innerHTML = '';
    const hash = location.hash || '#/dashboard';
    routeSeq++;  // responses to requests issued by the previous view will be discarded
    const pub = hash.match(/^#\/(invite|reset)\/([A-Za-z0-9_-]+)$/);
    if (pub) return pub[1] === 'invite' ? inviteView(pub[2]) : resetView(pub[2]);
    if (!S.token) { if (hash !== '#/login') { location.hash = '#/login'; return; } return loginView(); }
    if (!S.user) {
      try { S.user = await api('/api/auth/me'); S.meta = await api('/api/meta'); await loadSubscription(); applyBranding(); }
      catch (_) { return logout(); }
    }
    if (hash === '#/login') { location.hash = '#/dashboard'; return; }
    if (!S.user.organization && hash !== '#/platform') { location.hash = S.user.is_platform_admin ? '#/platform' : '#/login'; return; }
    for (const [re, fn] of ROUTES) {
      const m = hash.match(re);
      if (m) {
        try { await fn(m); } catch (e) { if (e instanceof StaleView) return; if ($('#content')) $('#content').innerHTML = h`<div class="notice err">${e.message}</div>`.s; else toast(e.message, true); }
        window.scrollTo(0, 0);
        return;
      }
    }
    location.hash = '#/dashboard';
  }
  window.addEventListener('hashchange', route);
  route();
})();
