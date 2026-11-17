// TERRA-Sim Live-Demo: lädt die vorberechneten Seiten (scripts/build_demo.py) und schickt die
// Szene an den echten 3D-Viewer (modules/viewer_webgpu/frontend) – mit derselben Nachricht, die
// sonst Streamlit schickt ("streamlit:render").

const ICONS = { modell: '🏙️', hochwasser: '🌊', starkregen: '🌧️', starkwind: '💨', erdbeben: '🫨',
                tornado: '🌪️', kaiju: '👾', aliens: '🛸' };
const TEXTS = {
  modell: 'Gebäude aus OpenStreetMap auf dem amtlichen Geländemodell – als Klötzchenmodell oder mit Dachformen, im vollen Werkzeug exportierbar für CAD und 3D-Druck.',
  hochwasser: '„Badewannen-Modell“: Alles, was unter dem Wasserspiegel liegt, gilt als überflutet. Dazu die amtlichen Hochwassergefahrenkarten der Länder.',
  starkregen: 'Der Regen fließt je nach Versiegelung ab, folgt dem Gefälle und staut sich in Senken. Wie selten so ein Regen ist, sagt die Statistik des Deutschen Wetterdienstes.',
  starkwind: 'Welche Fassaden stehen frei im Wind, wo wird er in engen Gassen beschleunigt, und wie strömt die Luft am Boden durch die Stadt? Die Windrose um den Sockel zeigt, woher der Wind hier wirklich kommt.',
  erdbeben: 'Wie stark bebt es am Standort, und welche Gebäude werden beschädigt? Makroseismische Methode nach der Europäischen Skala EMS-98.',
  tornado: 'Ein Wirbelsturm zieht über das Gebiet: Wo trifft er auf Gebäude, und wie schwer werden sie beschädigt?',
  kaiju: 'Planspiel: Ein Riesenmonster läuft quer durch das Gebiet. Welche Gebäude liegen in der Schneise, und wo bieten hohe Häuser Deckung?',
  aliens: 'Planspiel: UFOs kreuzen über dem Gebiet, bleiben stehen und holen mit dem Traktorstrahl Menschen nach oben.',
};
const LABELS = { flood: '🌊 Hochwasser', rain: '🌧️ Starkregen', wind: '💨 Sturm', quake: '🫨 Erdbeben',
                 tornado: '🌪️ Tornado', kaiju: '👾 Kaiju', alien: '🛸 Aliens' };
const ODDS_COLORS = { risk: '#d33a3a', warn: '#f08c28', ok: '#2f9e5f', none: '#9fb5a8' };
const DEFAULT_PAGE = 'starkwind';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const KIND_ICONS = { paper: '📚', norm: '📏', data: '🗂️' };
const cache = {};
let project, base, current = null;

// ------------------------------------------------------------------ 3D-Viewer
const viewer = $('viewer');
let viewerReady = false, pendingScene = null;
window.addEventListener('message', (ev) => {
  if (ev.source !== viewer.contentWindow || !ev.data) return;
  if (ev.data.type === 'streamlit:componentReady') {
    viewerReady = true;
    if (pendingScene) sendScene(pendingScene);
  }
});
// Falls die Bereit-Meldung schon vor diesem Skript kam: spätestens nach dem Laden senden
viewer.addEventListener('load', () => {
  if (!viewerReady) { viewerReady = true; if (pendingScene) sendScene(pendingScene); }
});
function sendScene(scene) {
  pendingScene = scene;
  if (!viewerReady) return;
  viewer.contentWindow.postMessage({ type: 'streamlit:render', args: { scene, height: viewer.clientHeight } }, '*');
}
window.addEventListener('resize', () => { if (pendingScene) sendScene(pendingScene); });

// ------------------------------------------------------------------ Daten
async function load(name) {
  if (!cache[name]) cache[name] = fetch(`data/${name}.json`).then((r) => {
    if (!r.ok) throw new Error(`${name}.json: ${r.status}`);
    return r.json();
  });
  return cache[name];
}

// ------------------------------------------------------------------ Bausteine
function factsHtml(items) {
  return '<div class="terra-facts">' + items.map(([lbl, val, note]) =>
    `<div class="terra-fact"><div class="lbl">${esc(lbl)}</div><div class="val">${esc(val)}</div>` +
    (note ? `<div class="note">${esc(note)}</div>` : '') + '</div>').join('') + '</div>';
}

function oddsCard(key, explain) {
  const o = project.odds[key];
  if (!o) return '';
  const tone = o.level === 'risk' ? 'risk' : o.level === 'warn' ? 'warn' : 'mint';
  const years = project.project.lifetime_years;
  let body;
  if (o.T == null) {
    body = `<p>${esc(o.text || 'Für dieses Szenario liegen keine Daten zur Häufigkeit vor.')}</p>`;
  } else {
    const tiny = o.p_life < 0.001;
    body = factsHtml([
      ['Wie oft?', o.text, 'im Mittel – nicht „genau alle …“'],
      [`Chance in ${years} Jahren`, o.life, (tiny ? `also ${o.one_in}` : 'mindestens einmal') + `; pro Jahr ${o.year}`],
    ]);
  }
  const note = [explain, o.source ? `Quelle: ${o.source}.` : ''].filter(Boolean).join(' ');
  return `<article class="card ${tone}"><h3>Wie wahrscheinlich ist dieses Szenario?</h3>${body}` +
         (note ? `<p class="side-note">${esc(note)}</p>` : '') + '</article>';
}

function oddsBar(key) {
  const o = project.odds[key];
  const p = o.p_life;
  const width = p ? Math.max(2, Math.min(100, (Math.log10(Math.max(p, 1e-5)) + 5) / 5 * 100)) : 0;
  const color = ODDS_COLORS[o.level] || ODDS_COLORS.none;
  const value = p != null ? `${o.life} in ${project.project.lifetime_years} J.` : 'keine Angabe';
  return `<div class="terra-prob"><span class="label">${esc(LABELS[key] || key)}</span>` +
         `<span class="value">${esc(o.text)} · ${esc(value)}</span>` +
         `<div class="bar"><span style="width:${width.toFixed(0)}%;background:${color}"></span></div>` +
         `<div class="note">${esc(o.source)}</div></div>`;
}

function inline(text) {
  return esc(text).replace(/`([^`]+)`/g, '<code>$1</code>');
}

function methodHtml(m) {
  const refLink = (n) => {
    const s = m.sources[n - 1];
    return s && s.link ? `<a href="${esc(s.link)}" target="_blank" rel="noopener">[${n}]</a>` : `[${n}]`;
  };
  const steps = m.steps.map((s) =>
    `<li>${inline(s.text)} <span class="refs">${s.refs.map(refLink).join(' ')}</span>` +
    (s.formula ? `<div class="formula" data-tex="${esc(s.formula)}"></div>` : '') + '</li>').join('');
  const list = (items, icon = '') => '<ul>' + items.map((t) => `<li>${icon}${inline(t)}</li>`).join('') + '</ul>';
  const sources = m.sources.map((s) => `<li>${KIND_ICONS[s.kind] || ''} ${esc(s.text)}` +
    (s.link ? ` <a href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.link.replace('https://', ''))}</a>` : '') +
    '</li>').join('');
  return `<summary>🔬 Methode &amp; Quellen – so rechnet TERRA-Sim (${m.sources.length} Quellen)</summary>` +
    `<div class="body"><p>${inline(m.summary)}</p><h4>Rechenweg</h4><ol>${steps}</ol>` +
    (m.assumptions.length ? `<h4>Annahmen – von TERRA-Sim gesetzt, nicht aus der Literatur</h4>${list(m.assumptions, '⚙️ ')}` : '') +
    (m.limits.length ? `<h4>Grenzen</h4>${list(m.limits)}` : '') +
    `<h4>Quellen</h4><ol class="sources">${sources}</ol></div>`;
}

function renderFormulas(root) {
  if (!window.katex) { setTimeout(() => renderFormulas(root), 300); return; }   // KaTeX lädt verzögert
  root.querySelectorAll('.formula[data-tex]').forEach((el) => {
    window.katex.render(el.dataset.tex, el, { displayMode: true, throwOnError: false });
    el.removeAttribute('data-tex');
  });
}

// ------------------------------------------------------------------ Seiten
async function show(key) {
  if (!project.pages.some((p) => p.key === key)) key = DEFAULT_PAGE;
  current = key;
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.key === key));
  const meta = project.pages.find((p) => p.key === key);
  $('page-title').textContent = `${ICONS[key] || ''} ${meta.title}`;
  $('page-text').textContent = TEXTS[key] || '';

  const page = await load(key);
  if (current !== key) return;              // inzwischen anderer Reiter gewählt
  $('page-scenario').textContent = page.scenario || '';

  const side = page.side && page.side.length ? `<article class="card mint">${page.side.join('')}</article>` : '';
  $('band').innerHTML = page.odds_key ? oddsCard(page.odds_key, page.explain) + side : side;

  $('kpis').innerHTML = page.metrics.map((m) =>
    `<div class="kpi"${m.help ? ` title="${esc(m.help)}"` : ''}><div class="lbl">${esc(m.label)}</div>` +
    `<div class="val">${esc(m.value)}</div></div>`).join('');
  $('legends').innerHTML = page.legends.join('');
  const methods = await load('methods');
  const method = $('method');
  method.innerHTML = methods[key] ? methodHtml(methods[key]) : '';
  method.style.display = methods[key] ? '' : 'none';
  renderFormulas(method);
  sendScene({ ...base, ...page.scene });
}

async function start() {
  [project, base] = await Promise.all([load('project'), load('base')]);
  const p = project.project;
  $('project-name').textContent = p.name;
  document.title = `TERRA-Sim · Live-Demo · ${p.name}`;
  $('project-facts').innerHTML = [
    `📍 ${p.lat.toFixed(4)}° N, ${p.lon.toFixed(4)}° E`,
    `${p.width_m} × ${p.height_m} m`,
    `${p.buildings} Gebäude`,
    `Gelände: ${p.terrain}`,
  ].map((t) => `<span>${esc(t)}</span>`).join('');
  $('terrain-source').textContent = p.terrain;
  $('climate-source').textContent = p.climate || '–';
  $('built').textContent = new Date(project.built).toLocaleDateString('de-DE');

  $('tabs').innerHTML = project.pages.map((pg) =>
    `<button type="button" data-key="${pg.key}">${ICONS[pg.key] || ''} ${esc(pg.title)}</button>`).join('');
  $('tabs').addEventListener('click', (ev) => {
    const b = ev.target.closest('button');
    if (b) location.hash = b.dataset.key;
  });

  const order = Object.keys(project.odds).sort((a, b) => (project.odds[b].p_life ?? -1) - (project.odds[a].p_life ?? -1));
  $('ranking').innerHTML = order.map(oddsBar).join('');

  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  await show(location.hash.slice(1) || DEFAULT_PAGE);
  // die übrigen Seiten schon einmal laden, damit der Wechsel sofort geht
  project.pages.forEach((pg) => load(pg.key));
}

start().catch((err) => {
  console.error(err);
  $('page-title').textContent = 'Die Demo-Daten konnten nicht geladen werden.';
  $('page-text').textContent = String(err.message || err);
});
