import { api, $, h, fmt, pill } from './api.js';

let token = null, selected = null, timer = null;
try { token = sessionStorage.getItem('pulsored.op'); } catch {}

const call = (path, opts = {}) => api(path, { token, retries: 1, ...opts });
function msg(el, cls, text) { el.replaceChildren(h('div', { class: 'msg ' + cls }, text)); }

async function enter() {
  token = $('#token').value.trim() || token;
  const r = await call('/incidents');
  if (r.status === 401) { msg($('#loginmsg'), 'err', 'Token inválido.'); token = null; return; }
  if (r.status !== 200) { msg($('#loginmsg'), 'err', r.data.message || 'Servicio no disponible.'); return; }
  try { sessionStorage.setItem('pulsored.op', token); } catch {}
  $('#login').hidden = true; $('#app').hidden = false;
  const z = await api('/zones', { retries: 1 });
  (z.data.items || []).forEach((x) => $('#fzone').append(h('option', { value: x.id }, `${x.name} (${x.id})`)));
  refresh();
  clearInterval(timer); timer = setInterval(refresh, 15000);
}

async function refresh() {
  const q = new URLSearchParams();
  if ($('#fzone').value) q.set('zone_id', $('#fzone').value);
  if ($('#fclosed').value === '1') q.set('include_closed', '1');
  const [r, ev] = await Promise.all([call('/incidents?' + q), call('/infra/events' + ($('#fzone').value ? '?zone_id=' + $('#fzone').value : ''))]);
  if (r.status === 401) { location.reload(); return; }
  renderList(r.data.items || []);
  renderInfra(ev.data.items || []);
  $('#upd').textContent = 'Actualizado ' + new Date().toLocaleTimeString();
  if (selected) openIncident(selected, true);
}

function renderList(items) {
  const box = $('#list');
  if (!items.length) { box.replaceChildren(h('p', { class: 'mut' }, 'Sin incidentes.')); return; }
  box.replaceChildren(h('table', {},
    h('thead', {}, h('tr', {}, ...['Prioridad', 'Zona', 'Grupo', 'Estado', 'Usuarios', 'Origen'].map((t) => h('th', {}, t)))),
    h('tbody', {}, items.map((i) => h('tr', { class: 'row-click' + (i.incident_id === selected ? ' sel' : ''), onclick: () => openIncident(i.incident_id) },
      h('td', {}, pill(i.priority_level), ' ', String(i.priority_score ?? '')), h('td', {}, i.zone_id), h('td', {}, i.problem_group),
      h('td', {}, pill(i.status)), h('td', {}, String(i.users_affected)), h('td', {}, i.origin))))));
}

function renderInfra(items) {
  const box = $('#infra');
  if (!items.length) { box.replaceChildren(h('p', { class: 'mut' }, 'Sin eventos recibidos.')); return; }
  box.replaceChildren(h('table', {},
    h('thead', {}, h('tr', {}, ...['Hora', 'Evento', 'Antena', 'Zona', 'Severidad'].map((t) => h('th', {}, t)))),
    h('tbody', {}, items.slice(0, 15).map((e) => h('tr', {}, h('td', {}, fmt(e.occurred_at)), h('td', {}, e.event_type),
      h('td', {}, e.antenna_id), h('td', {}, e.zone_id), h('td', {}, e.severity || '—'))))));
}

async function openIncident(id, silent) {
  selected = id;
  const r = await call('/incidents/' + encodeURIComponent(id));
  const box = $('#detail');
  if (r.status !== 200) { msg(box, 'err', r.data.message || 'Error'); return; }
  const d = r.data;
  const act = (label, body, cls = 'sec') => h('button', { class: cls, onclick: async () => {
    const note = prompt('Nota (opcional)') ?? '';
    const res = await call('/incidents/' + encodeURIComponent(id), { method: 'PATCH', body: { ...body, note } });
    if (res.status >= 400) alert(res.data.message || 'No permitido');
    setTimeout(refresh, 800);
  } }, label);
  const next = { REGISTRADA: ['EN_REVISION'], EN_REVISION: ['EN_ATENCION'], EN_ATENCION: ['SOLUCIONADA'], SOLUCIONADA: ['CERRADA', 'EN_REVISION'] }[d.status] || [];
  box.replaceChildren(
    h('p', {}, pill(d.priority_level), ' ', h('b', {}, String(d.priority_score)), '/100  ·  ', pill(d.status), '  ·  ', String(d.users_affected), ' usuarios'),
    h('p', { class: 'mut' }, 'Zona ', d.zone_id, ' · origen ', d.origin, ' · antenas: ', (d.antenna_ids || []).join(', ') || 'sin evidencia (verificar en campo)',
      d.detection_lag_s != null ? ` · la red avisó ${d.detection_lag_s >= 0 ? d.detection_lag_s + ' s antes' : -d.detection_lag_s + ' s después'} que los usuarios` : ''),
    d.ai ? h('p', {}, h('b', {}, 'Resumen (' + d.ai_source + '): '), d.ai.summary) : '',
    h('p', { class: 'mut mono' }, 'Factores: ', JSON.stringify(d.priority_factors || {})),
    h('div', { class: 'actions' },
      ['REGISTRADA', 'EN_REVISION'].includes(d.status) ? [act('Confirmar infraestructura', { action: 'CONFIRMAR' }), act('Descartar (falso positivo)', { action: 'DESCARTAR' }, 'bad')] : '',
      next.map((to) => act('→ ' + to, { action: 'CAMBIAR_ESTADO', to }))),
    h('h2', { style: 'margin-top:16px' }, 'Historial'),
    h('ol', { class: 'tl' }, (d.history || []).slice().reverse().map((x) => h('li', {}, h('b', {}, x.action), ' · ', x.actor, ' · ', fmt(x.ts), x.from !== x.to ? ` · ${x.from ?? '∅'} → ${x.to}` : '', x.note ? ' · ' + x.note : ''))),
    h('h2', { style: 'margin-top:16px' }, `Reportes vinculados (${(d.reports || []).length})`),
    h('ul', { class: 'mut' }, (d.reports || []).slice(0, 10).map((x) => h('li', {}, h('span', { class: 'mono' }, x.report_id), ' · ', x.problem_type, ' · ', x.description))),
  );
  if (!silent) renderListSelection();
}
function renderListSelection() { document.querySelectorAll('#list tr.row-click').forEach((tr) => tr.classList.remove('sel')); }

$('#enter').addEventListener('click', enter);
$('#token').addEventListener('keydown', (e) => e.key === 'Enter' && enter());
$('#refresh').addEventListener('click', refresh);
$('#fzone').addEventListener('change', refresh);
$('#fclosed').addEventListener('change', refresh);
if (token) enter();
