// Cliente de API compartido (portal y consola). Sin dependencias.
let _cfg;
export async function cfg() {
  if (!_cfg) _cfg = await (await fetch('/config.json', { cache: 'no-store' })).json();
  return _cfg;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** fetch con timeout, reintentos con backoff exponencial + jitter (solo ante 5xx/429/red). */
export async function api(path, { method = 'GET', body, token, retries = 3 } = {}) {
  const { apiBase } = await cfg();
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['x-operator-token'] = token;
  let last;
  for (let i = 0; i <= retries; i++) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 12000);
    try {
      const r = await fetch(apiBase + '/api' + path, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctl.signal });
      clearTimeout(t);
      const data = await r.json().catch(() => ({}));
      if (r.status < 500 && r.status !== 429) return { status: r.status, data };
      last = { status: r.status, data };
    } catch (e) {
      clearTimeout(t);
      last = { status: 0, data: { error: 'NETWORK', message: 'Sin conexión con el servicio' } };
    }
    if (i < retries) await sleep(Math.min(8000, 600 * 2 ** i) * (0.5 + Math.random()));
  }
  return last;
}

export const $ = (s, el = document) => el.querySelector(s);
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(kid ?? ''));
  return el; // todo texto entra por nodos de texto: sin innerHTML, sin XSS
}
export const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : '—');
export const pill = (v) => h('span', { class: 'pill ' + v }, v ?? '—');
export function uuid() {
  return crypto.randomUUID ? crypto.randomUUID() : 'k-' + Date.now() + '-' + Math.random().toString(36).slice(2);
}
