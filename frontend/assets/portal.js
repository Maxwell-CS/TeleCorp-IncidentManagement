import { api, $, h, fmt, pill, uuid } from './api.js';

const DRAFT = 'pulsored.draft';   // reporte pendiente (misma idempotency_key en cada reintento)
const store = {
  get() { try { return JSON.parse(localStorage.getItem(DRAFT)); } catch { return null; } },
  set(v) { try { localStorage.setItem(DRAFT, JSON.stringify(v)); } catch {} },
  clear() { try { localStorage.removeItem(DRAFT); } catch {} },
};

// ---- zonas ----
(async () => {
  const r = await api('/zones', { retries: 1 });
  let items = r.data.items;
  if (!items) items = await (await fetch('/zones.json')).json();   // respaldo estático
  const sel = $('#zone');
  sel.append(h('option', { value: '' }, 'Selecciona tu zona'));
  items.forEach((z) => sel.append(h('option', { value: z.id }, `${z.name} (${z.id})`)));
})();

const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
$('#when').value = now; $('#when').max = now;

function show(el, cls, ...kids) { el.replaceChildren(h('div', { class: 'msg ' + cls }, ...kids)); }

async function submitReport(payload) {
  const res = $('#result'), btn = $('#send');
  btn.disabled = true;
  const r = await api('/reports', { method: 'POST', body: payload, retries: 3 });
  btn.disabled = false;
  if (r.status === 202 || r.status === 200) {
    store.clear();
    show(res, 'ok', 'Reporte registrado. Tu código es ', h('b', { class: 'mono' }, r.data.report_id),
      '. Guárdalo para consultar el estado.');
    $('#code').value = r.data.report_id;
    $('#form').reset(); $('#when').value = now;
    lookup();
  } else if (r.status === 0 || r.status >= 500) {
    // El servicio no respondió tras los reintentos: NO mostramos código (aún no existe). Se guarda y se reenvía.
    store.set(payload);
    show(res, 'warn', 'No pudimos enviar tu reporte ahora. Quedó guardado en este dispositivo y se reenviará cuando el servicio vuelva.');
  } else {
    show(res, 'err', r.data.message || 'No se pudo registrar el reporte.');
  }
}

$('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  const draft = store.get();
  const payload = {
    idempotency_key: draft?.idempotency_key || uuid(),
    user_document: $('#doc').value.trim(), phone: $('#phone').value.trim(), zone_id: $('#zone').value,
    occurred_at: new Date($('#when').value).toISOString(), problem_type: $('#ptype').value,
    description: $('#desc').value.trim(),
  };
  const mail = $('#email').value.trim(); if (mail) payload.email = mail;
  submitReport(payload);
});

// Reintenta un borrador pendiente al abrir la página
const pending = store.get();
if (pending) submitReport(pending);

// ---- consulta de estado ----
async function lookup() {
  const code = $('#code').value.trim();
  const out = $('#status');
  if (!code) return;
  const r = await api('/reports/' + encodeURIComponent(code), { retries: 2 });
  if (r.status !== 200) { show(out, 'err', r.data.message || 'No se pudo consultar.'); return; }
  const d = r.data;
  out.replaceChildren(
    h('p', {}, 'Estado: ', pill(d.status), '  ·  Zona ', d.zone_id, '  ·  Registrado ', fmt(d.created_at)),
    d.incident ? h('p', { class: 'mut' }, 'Tu reporte está vinculado a una incidencia colectiva en tu zona (', d.incident.incident_id, ').') : '',
    h('ol', { class: 'tl' }, d.history.map((x) => h('li', {}, h('b', {}, x.action || x.to), ' · ', fmt(x.ts), x.note ? ' · ' + x.note : ''))),
  );
}
$('#lookup').addEventListener('click', lookup);
const q = new URLSearchParams(location.search).get('r');
if (q) { $('#code').value = q; lookup(); }
