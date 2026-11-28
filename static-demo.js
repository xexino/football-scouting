/* Static read-only demo (GitHub Pages). Loaded before app.js only in the static build
   (backend/tools/export_static.py). Serves pre-exported API responses of the FICTIONAL demo
   organization, implements player search / pipeline filters / comparison in the browser and
   refuses every write. The full platform requires the server deployment. */
(() => {
  'use strict';
  const BASE = new URL('.', document.currentScript.src).href;
  window.RSI_STATIC_DEMO = true;
  try { sessionStorage.setItem('rsi_token', 'static-demo'); } catch (_) { /* storage blocked */ }

  const cache = {};
  const load = p => (cache[p] ||= fetch(BASE + 'data/' + p).then(r => { if (!r.ok) throw new Error(p); return r.json(); }));
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const READ_ONLY = { detail: 'Read-only demo: this public snapshot cannot save changes. The full platform runs on a server.' };
  const NOT_AVAILABLE = { detail: 'Not available in the static demo.' };

  // Must match file_name() in backend/tools/export_static.py
  function fileFor(path, params) {
    const q = [...params.entries()].map(([k, v]) => [k, String(v)]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .map(([k, v]) => `${k}=${v}`).join('&');
    return (path.replaceAll('/', '__') + (q ? `__${q}` : '')).replace(/[^A-Za-z0-9_=&.-]/g, '_') + '.json';
  }

  const ordinal = n => { n = Math.round(n); const s = (n % 100 >= 10 && n % 100 <= 20) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'); return n + s; };
  const OPS = { '>=': (a, b) => a >= b, '<=': (a, b) => a <= b, '>': (a, b) => a > b, '<': (a, b) => a < b, '=': (a, b) => a === b };

  async function searchPlayers(sp) {
    let rows = await load('search_index.json');
    const g = k => sp.get(k);
    const num = k => (g(k) == null || g(k) === '' ? null : Number(g(k)));
    const lower = v => String(v || '').toLowerCase();
    if (g('q')) rows = rows.filter(p => lower(p.full_name).includes(lower(g('q'))) || lower(p.known_as).includes(lower(g('q'))));
    if (g('position')) {
      const want = new Set(g('position').toUpperCase().split(',').map(s => s.trim()));
      const primaryOnly = g('primary_only') === 'true';
      rows = rows.filter(p => want.has(p.primary_position) || (!primaryOnly && (p.secondary_positions || []).some(x => want.has(x))));
    }
    if (g('tactical_role')) rows = rows.filter(p => lower(p.tactical_role).includes(lower(g('tactical_role'))));
    if (num('age_min') != null) rows = rows.filter(p => p.age != null && p.age >= num('age_min'));
    if (num('age_max') != null) rows = rows.filter(p => p.age != null && p.age <= num('age_max'));
    if (g('nationality')) {
      const nats = g('nationality').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
      rows = rows.filter(p => nats.includes(lower(p.nationality)) || nats.includes(lower(p.second_nationality)));
    }
    if (g('league_id')) rows = rows.filter(p => String(p.league_id) === g('league_id'));
    if (g('league_country')) rows = rows.filter(p => lower(p.league_country) === lower(g('league_country')));
    if (g('club_id')) rows = rows.filter(p => String(p.current_club_id) === g('club_id'));
    if (num('height_min') != null) rows = rows.filter(p => p.height_cm != null && p.height_cm >= num('height_min'));
    if (num('height_max') != null) rows = rows.filter(p => p.height_cm != null && p.height_cm <= num('height_max'));
    if (g('foot')) rows = rows.filter(p => p.preferred_foot === g('foot'));
    if (g('contract_expiry_before')) rows = rows.filter(p => p.contract_expiry && p.contract_expiry <= g('contract_expiry_before'));
    if (num('fee_min') != null) rows = rows.filter(p => p.estimated_fee != null && p.estimated_fee >= num('fee_min'));
    if (num('fee_max') != null) rows = rows.filter(p => p.estimated_fee != null && p.estimated_fee <= num('fee_max'));
    if (num('salary_max') != null) rows = rows.filter(p => p.salary_expectation != null && p.salary_expectation <= num('salary_max'));
    if (g('availability')) { const a = g('availability').split(','); rows = rows.filter(p => a.includes(p.availability || 'unknown')); }
    if (g('pipeline_stage')) {
      const st = g('pipeline_stage').split(',');
      rows = st.includes('none') ? rows.filter(p => !p.pipeline_stage) : rows.filter(p => st.includes(p.pipeline_stage));
    }
    if (g('include_fictional') === 'false') rows = rows.filter(p => !p.is_fictional);
    if (num('min_minutes') != null) rows = rows.filter(p => (p._minutes || 0) >= num('min_minutes'));
    const filters = [];
    for (const part of (g('stat_filters') || '').split(',').filter(s => s.trim())) {
      const m = part.match(/^\s*([a-z0-9_]+)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*$/);
      if (!m) return { _error: `Invalid statistical filter '${part}'` };
      filters.push([m[1], m[2], Number(m[3])]);
    }
    rows = rows.filter(p => filters.every(([k, op, v]) => p._metrics[k] != null && OPS[op](p._metrics[k], v)));
    const sort = g('sort') || 'full_name', desc = g('order') === 'desc';
    const nullsLast = (a, b, f) => { const x = f(a), y = f(b); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1); };
    const keyFns = {
      full_name: p => p.full_name.toLowerCase(), age: p => p.age, fee: p => p.estimated_fee,
      contract_expiry: p => p.contract_expiry, last_updated: p => p.last_updated, height: p => p.height_cm,
    };
    const metricKey = sort.startsWith('metric:') ? sort.slice(7) : null;
    rows = [...rows].sort((a, b) => nullsLast(a, b, metricKey ? (p => p._metrics[metricKey]) : (keyFns[sort] || keyFns.full_name)));
    const page = Math.max(1, num('page') || 1), size = Math.min(200, num('page_size') || 25);
    const keys = [...new Set(filters.map(f => f[0]).concat(metricKey ? [metricKey] : []))];
    const items = rows.slice((page - 1) * size, page * size).map(p => {
      const { _metrics, _minutes, ...item } = p;
      if (keys.length) item.matched_metrics = Object.fromEntries(keys.map(k => [k, _metrics[k] ?? null]));
      return item;
    });
    return { total: rows.length, page, page_size: size, items };
  }

  async function pipelineBoard(sp) {
    const board = structuredClone(await load('pipeline.json'));
    const me = await load('auth__me.json');
    const keep = e => (!sp.get('priority') || e.priority === sp.get('priority'))
      && (!sp.get('position') || e.position === sp.get('position') || e.target_position === sp.get('position'))
      && (sp.get('assigned_to_me') !== 'true' || e.assigned_scout_id === me.id);
    let total = 0;
    for (const s of Object.keys(board.columns)) { board.columns[s] = board.columns[s].filter(keep); total += board.columns[s].length; }
    board.total = total;
    return board;
  }

  async function compare(body) {
    const ids = body.player_ids || [];
    if (ids.length < 2 || ids.length > 5 || new Set(ids).size !== ids.length) return [422, { detail: 'Select 2 to 5 different players' }];
    const meta = await load('meta.json');
    const players = await Promise.all(ids.map(id => load(`players__${id}.json`)));
    const positions = new Set(players.map(p => p.primary_position));
    if (positions.size > 1) return [422, { detail: 'Players must share the same primary position.' }];
    const position = players[0].primary_position;
    const profile = meta.position_profiles[position];
    const roles = Object.entries(meta.tactical_roles).filter(([, r]) => r.position === position).map(([k]) => k);
    const roleKey = body.tactical_role && roles.includes(body.tactical_role) ? body.tactical_role : roles[0];
    const today = new Date();
    const out = [];
    for (const p of players) {
      const [a, mrs, reps] = await Promise.all([load(`players__${p.id}__analytics.json`),
        load(fileFor('match-reports', new URLSearchParams({ player_id: p.id }))), load(fileFor('reports', new URLSearchParams({ player_id: p.id })))]);
      const pm = Object.fromEntries((a.profile_metrics || []).map(m => [m.key, m]));
      const fit = (a.role_fit || []).find(r => r && r.role === roleKey) || null;
      const ratings = mrs.map(r => r.overall_rating).filter(v => v != null);
      const ce = p.contract_expiry ? new Date(p.contract_expiry) : null;
      out.push({
        player: { id: p.id, full_name: p.full_name, age: p.age, nationality: p.nationality, club: p.club_name, league: p.league_name,
          position: p.primary_position, height_cm: p.height_cm, preferred_foot: p.preferred_foot, is_fictional: p.is_fictional, pipeline_stage: p.pipeline_stage },
        season: a.season, minutes: a.minutes, sample_reliable: !!a.sample_reliable,
        metrics: profile.map(k => ({ key: k, value: pm[k]?.value ?? (a.all_metrics || {})[k] ?? null, league_adjusted: pm[k]?.league_adjusted ?? null, percentile: pm[k]?.percentile ?? null })),
        strengths: (a.profile_metrics || []).filter(m => m.percentile != null && m.percentile >= 70).map(m => `${m.label} (${ordinal(m.percentile)} pct)`),
        weaknesses: (a.profile_metrics || []).filter(m => m.percentile != null && m.percentile <= 30).map(m => `${m.label} (${ordinal(m.percentile)} pct)`),
        strengths_weaknesses_basis: 'data-derived: ≥70th / ≤30th percentile vs. database position pool',
        tactical_suitability: fit,
        financial: { estimated_fee: p.estimated_fee, salary_expectation: p.salary_expectation, currency: p.currency, contract_expiry: p.contract_expiry,
          months_remaining: ce ? (ce.getFullYear() - today.getFullYear()) * 12 + ce.getMonth() - today.getMonth() : null,
          availability: p.availability, redacted: !!p.financials_redacted },
        scouting: { evidence_type: 'scout_opinion', match_reports: mrs.length,
          full_match_or_live_reports: mrs.filter(r => r.observation_type !== 'video_highlights').length,
          highlights_only_reports: mrs.filter(r => r.observation_type === 'video_highlights').length,
          avg_overall_rating: ratings.length ? Math.round(ratings.reduce((x, y) => x + y, 0) / ratings.length * 10) / 10 : null,
          latest_recommendation: reps[0]?.recommendation ?? null, latest_report_id: reps[0]?.id ?? null },
        provenance: a.provenance, caveats: a.caveats || [],
      });
    }
    return [200, { position, profile, tactical_role: roleKey, tactical_role_label: roleKey ? meta.tactical_roles[roleKey].label : null, players: out,
      notes: ['Radar values are database percentiles within the position pool (0–100); they are relative, not absolute quality.',
        'Compare players only with sufficient minutes; small samples are flagged.',
        'Scouting figures are opinions of named scouts; highlights-only reports are counted separately.'] }];
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const at = url.pathname.indexOf('/api/');
    if (at === -1 || url.origin !== location.origin) return realFetch(input, init);
    const path = url.pathname.slice(at + 5);
    const method = (init.method || 'GET').toUpperCase();
    try {
      if (method === 'POST' && path === 'auth/token') return json({ access_token: 'static-demo', token_type: 'bearer', organization_id: 1 });
      if (method === 'POST' && path === 'compare') { const [status, body] = await compare(JSON.parse(init.body || '{}')); return json(body, status); }
      if (method !== 'GET') return json(READ_ONLY, 403);
      if (path === 'players') { const r = await searchPlayers(url.searchParams); return r._error ? json({ detail: r._error }, 422) : json(r); }
      if (path === 'pipeline') return json(await pipelineBoard(url.searchParams));
      return json(await load(fileFor(path, url.searchParams)));
    } catch (_) {
      return json(NOT_AVAILABLE, 404);
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const bar = document.createElement('div');
    bar.textContent = 'Public read-only demo · fictional data · changes are not saved';
    bar.setAttribute('role', 'status');
    bar.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:10px;z-index:300;white-space:nowrap;pointer-events:none;padding:6px 12px;border-radius:99px;font:600 12px system-ui;'
      + 'background:#3a2a06;color:#ffd28a;border:1px solid rgba(240,160,48,.5);box-shadow:0 4px 18px rgba(0,0,0,.4)';
    document.body.appendChild(bar);
  });
})();
