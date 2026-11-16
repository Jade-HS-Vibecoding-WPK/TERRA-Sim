// TERRA-Sim – 3D-Ansicht mit three.js (WebGPU, sonst automatisch WebGL 2)
//
// Läuft als Streamlit-Komponente in einem iframe. Python schickt bei jedem
// Neuzeichnen die Szene (siehe scene.py); hier wird nur ausgetauscht, was sich
// geändert hat – die Kamera bleibt stehen.
//
// Koordinaten aus Python: x = Osten, y = Norden, z = Höhe (Meter, relativ zur
// Szenenmitte). three.js: x = Osten, y = oben, z = Süden  ->  (x, z, -y).

import * as THREE from 'three/webgpu';
import { pass, mrt, normalView, screenUV, sample, packNormalToRGB, unpackRGBToNormal,
         builtinAOContext, vertexColor } from 'three/tsl';
import { ssao } from 'three/addons/tsl/display/SSAONode.js';
import { MapControls } from 'three/addons/controls/MapControls.js';
import { Crowd } from './people.js';
import { Effects } from './effects.js';
import { FlowParticles, VortexParticles } from './flow.js';

// ---------------------------------------------------------------------------
// Streamlit-Protokoll (Komponenten-API v1, ohne Zusatzbibliothek)
// ---------------------------------------------------------------------------
const send = (type, data = {}) =>
  window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, '*');

const view = document.getElementById('view');
const msg = document.getElementById('msg');
const tip = document.getElementById('tip');
const badge = document.getElementById('badge');
const needle = document.getElementById('needle');

// ---------------------------------------------------------------------------
// Renderer, Licht, Kamera
// ---------------------------------------------------------------------------
const renderer = new THREE.WebGPURenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.toneMapping = THREE.NeutralToneMapping;
view.appendChild(renderer.domElement);
await renderer.init();
const backendName = renderer.backend && renderer.backend.isWebGPUBackend ? 'WebGPU' : 'WebGL 2';

const scene = new THREE.Scene();
const HORIZON = new THREE.Color(0xe9eeee);
scene.background = skyTexture();
scene.fog = new THREE.Fog(HORIZON, 4000, 12000);

const hemi = new THREE.HemisphereLight(0xeaf1f6, 0xb3aa98, 1.5);
const fill = new THREE.DirectionalLight(0xdfe9f2, 0.55);   // Gegenlicht, hellt Schattenseiten auf
const sun = new THREE.DirectionalLight(0xfff2de, 3.0);
scene.add(fill);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
sun.shadow.bias = -0.0003;
sun.shadow.normalBias = 0.5;
sun.shadow.radius = 2.5;
scene.add(hemi, sun, sun.target);

const camera = new THREE.PerspectiveCamera(36, 1, 0.5, 30000);
const controls = new MapControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.maxPolarAngle = Math.PI * 0.47;
controls.zoomToCursor = true;

const world = new THREE.Group();          // Gelände, Sockel, Gebäude
const dynamic = new THREE.Group();        // Wasser, Fassaden, Pfeile …
world.add(dynamic);                       // (so wackelt beim Erdbeben alles mit)
scene.add(world);
const crowd = new Crowd(THREE, world, (x, y) => groundAt(x, y));
const fx = new Effects(THREE, world, (x, y) => groundAt(x, y), crowd);
const flow = new FlowParticles(THREE, world, (x, y) => groundAt(x, y));
const vortex = new VortexParticles(THREE, world, (x, y) => groundAt(x, y));
crowd.flow = flow;
fx.buildings = { lift: (i) => liftBuilding(i), restore: (list) => restoreBuildings(list) };
const counter = document.getElementById('counter');

function skyTexture() {
  const c = document.createElement('canvas');
  c.width = 4; c.height = 256;
  const g = c.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, '#a9c8de');
  grad.addColorStop(0.55, '#dce7ec');
  grad.addColorStop(1, '#eef1ef');
  g.fillStyle = grad; g.fillRect(0, 0, 4, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ---------------------------------------------------------------------------
// Nachbearbeitung: Umgebungsverdeckung (SSAO) – macht Ecken und Gassen plastisch
// ---------------------------------------------------------------------------
let pipeline = null;
let effects = true;
try {
  pipeline = new THREE.RenderPipeline(renderer);
  const prePass = pass(scene, camera, { samples: 0 });
  prePass.transparent = false;
  prePass.setMRT(mrt({ output: packNormalToRGB(normalView) }));
  prePass.getTexture('output').type = THREE.UnsignedByteType;
  const prePassNormal = sample((uv) => unpackRGBToNormal(prePass.getTextureNode().sample(uv)));
  const prePassDepth = prePass.getTextureNode('depth');
  const scenePass = pass(scene, camera);
  const aoPass = ssao(prePassDepth, prePassNormal, camera);
  aoPass.radius.value = 4.0;
  aoPass.intensity.value = 1.1;
  aoPass.samples.value = 16;
  scenePass.contextNode = builtinAOContext(aoPass.getTextureNode().sample(screenUV).r);
  pipeline.outputNode = scenePass;
} catch (err) {
  console.warn('SSAO nicht verfügbar:', err);
  pipeline = null;
}

// ---------------------------------------------------------------------------
// Zeichnen nur bei Bedarf (schont Akku und Lüfter)
// ---------------------------------------------------------------------------
let dirty = 2;
const invalidate = (frames = 2) => { dirty = Math.max(dirty, frames); };
controls.addEventListener('change', () => { invalidate(2); saveCamera(); });

let lastFrame = performance.now();
renderer.setAnimationLoop(() => {
  const now = performance.now();
  const dt = Math.min(0.1, (now - lastFrame) / 1000), t = now / 1000;
  lastFrame = now;
  controls.update();
  // Bewegte Dinge: Tornado, Monster, Menschen, Erdbeben
  const ctx = animateMovers(t);
  const shaking = shakeWorld(t);
  if (crowd.active || state.movers.length || shaking || fx.active || flow.active || vortex.active) {
    flow.update(dt);
    vortex.update(dt, ctx.funnel);
    fx.update(dt, t, ctx);
    if (state.heightsDirty) { state.heightsDirty = false; applyHeights(); }
    crowd.update(dt, t, ctx);
    followNik();
    if (fx.ufos.length) counter.textContent = `👽 Entführt: ${crowd.abducted}`;
    dirty = Math.max(dirty, 1);
  }
  if (dirty <= 0) return;
  dirty -= 1;
  if (pipeline && effects) pipeline.render();
  else renderer.render(scene, camera);
  needle.setAttribute('transform', `rotate(${THREE.MathUtils.radToDeg(controls.getAzimuthalAngle())})`);
});

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  invalidate(2);
}
new ResizeObserver(resize).observe(view);

// ---------------------------------------------------------------------------
// Hilfen
// ---------------------------------------------------------------------------
async function decode(b64) {
  const response = await fetch('data:application/octet-stream;base64,' + b64);
  return response.arrayBuffer();
}

function srgb(r, g, b) {
  return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
}

function dispose(object) {
  object.traverse((o) => {
    if (o.geometry && !o.userData.sharedGeometry) o.geometry.dispose();
    if (o.material) {
      if (o.material.map && o.material.map !== state.mapTexture) o.material.map.dispose();
      o.material.dispose();
    }
  });
}

function clearGroup(group) {
  for (const child of [...group.children]) { group.remove(child); dispose(child); }
}

// Tornado und Monster ziehen in einer Schleife über ihre Bahn
function animateMovers(t) {
  const ctx = {};
  for (const m of state.movers) {
    const u = ((t * m.speed) % m.travel) - m.travel / 2;
    const x = m.x + m.fx * u, y = m.y + m.fy * u;
    m.obj.position.set(x, groundAt(x, y), -y);
    if (m.kind === 'funnel') {
      m.obj.children[0].rotation.y = -t * 2.5;            // Wirbel dreht sich
      m.obj.children[1].rotation.z = t * 1.5;
      ctx.funnel = { x, y, core: m.size };
    } else {
      const phase = t * m.speed / (0.45 * m.size) * Math.PI;   // ein Schritt alle 0,45 Körperhöhen
      m.obj.userData.legs.forEach((leg, k) => { leg.rotation.x = Math.sin(phase + k * Math.PI) * 0.45; });
      m.obj.position.y += Math.abs(Math.sin(phase)) * 0.02 * m.size;
      ctx.monster = { x, y, height: m.size, u, obj: m.obj };
    }
  }
  return ctx;
}

// Erdbeben: alle 12 s eine Bebenphase von 5 s, das Modell wackelt wie auf einem Rütteltisch
function shakeWorld(t) {
  const h = state.hazard;
  if (!h || h.type !== 'quake' || h.intensity < 3) {
    if (world.position.lengthSq()) { world.position.set(0, 0, 0); invalidate(2); }
    return false;
  }
  const phase = t % 12;
  const shaking = phase < 5 ? Math.sin(Math.PI * phase / 5) : 0;
  h.shaking = shaking;
  const amp = 0.04 * Math.pow(Math.max(0, h.intensity - 4), 1.5) * shaking;
  world.position.set(Math.sin(t * 31) * amp, Math.sin(t * 23) * amp * 0.3, Math.cos(t * 27) * amp);
  return true;
}

const state = {
  movers: [], hazard: null,
  height: 0, terrainId: null, buildingsId: null, textureUrl: null, overlayKey: null,
  radius: 500, top: 50, plinth: 8, mapTexture: null,
  terrainGeometry: null, terrainMesh: null, overlayMesh: null,
  buildingMesh: null, start: null, nBuildings: 0, baseColors: null, tips: [],
  facadeMesh: null, facadeTips: [], hover: -1,
};

// ---------------------------------------------------------------------------
// Gelände mit Sockel und Kartengrundlage
// ---------------------------------------------------------------------------
async function buildTerrain(t) {
  for (const obj of [state.terrainMesh, state.plinthMesh, state.tableMesh]) {
    if (obj) { world.remove(obj); dispose(obj); }
  }
  const { nx, ny, cell, x0, y0 } = t;
  const z = new Float32Array(await decode(t.z));
  const cols = nx + 1, rows = ny + 1;
  const pos = new Float32Array(cols * rows * 3);
  const uv = new Float32Array(cols * rows * 2);
  let zMin = Infinity, zMax = -Infinity;
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      const k = j * cols + i;
      pos[k * 3] = x0 + i * cell;
      pos[k * 3 + 1] = z[k];
      pos[k * 3 + 2] = -(y0 + j * cell);
      uv[k * 2] = i / nx;
      uv[k * 2 + 1] = j / ny;
      zMin = Math.min(zMin, z[k]); zMax = Math.max(zMax, z[k]);
    }
  }
  const index = [];
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const a = j * cols + i, b = a + 1, c = a + cols, d = c + 1;
      index.push(a, b, d, a, d, c);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setIndex(index);
  geo.computeVertexNormals();
  state.terrainGeometry = geo;
  state.grid = { z, nx, ny, cell, x0, y0 };

  const width = nx * cell, depth = ny * cell;
  state.radius = 0.5 * Math.hypot(width, depth);
  state.plinth = Math.max(6, 0.035 * Math.max(width, depth) + (zMax - zMin) * 0.1);
  state.ground = (zMin + zMax) / 2;

  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.96, metalness: 0 });
  if (state.mapTexture) material.map = state.mapTexture;
  const mesh = new THREE.Mesh(geo, material);
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  state.terrainMesh = mesh;

  // Sockel: senkrechte Seitenwände bis unter das Gelände, wie ein Arbeitsmodell
  const ring = [];
  for (let i = 0; i <= nx; i++) ring.push(i);                       // Süden, nach Osten
  for (let j = 1; j <= ny; j++) ring.push(j * cols + nx);           // Osten, nach Norden
  for (let i = nx - 1; i >= 0; i--) ring.push(ny * cols + i);       // Norden, nach Westen
  for (let j = ny - 1; j >= 0; j--) ring.push(j * cols);            // Westen, nach Süden
  const bottom = zMin - state.plinth;
  const wall = [];
  for (let n = 0; n < ring.length - 1; n++) {
    const p = ring[n], q = ring[n + 1];
    const px = pos[p * 3], py = pos[p * 3 + 1], pz = pos[p * 3 + 2];
    const qx = pos[q * 3], qy = pos[q * 3 + 1], qz = pos[q * 3 + 2];
    wall.push(px, bottom, pz, qx, bottom, qz, qx, qy, qz,
              px, bottom, pz, qx, qy, qz, px, py, pz);
  }
  const wallGeo = new THREE.BufferGeometry();
  wallGeo.setAttribute('position', new THREE.Float32BufferAttribute(wall, 3));
  wallGeo.computeVertexNormals();
  const plinth = new THREE.Mesh(wallGeo, new THREE.MeshStandardMaterial({ color: 0xd9d1c3, roughness: 1 }));
  plinth.castShadow = true;
  state.plinthMesh = plinth;

  // "Tisch", auf dem das Modell steht – fängt den Schatten des Sockels auf
  const table = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
                               new THREE.MeshStandardMaterial({ color: 0xe4e8e5, roughness: 1 }));
  table.rotation.x = -Math.PI / 2;
  table.scale.set(state.radius * 14, state.radius * 14, 1);
  table.position.y = bottom - 0.05;
  table.receiveShadow = true;
  state.tableMesh = table;
  world.add(mesh, plinth, table);

  // Sonne aus Südosten, 38° hoch: Schatten fallen in der Ausgangsansicht seitlich
  // und sind gut zu sehen. Die Schattenkamera deckt das ganze Gebiet ab.
  const az = THREE.MathUtils.degToRad(135), el = THREE.MathUtils.degToRad(38);
  const r = state.radius;
  const dir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
  sun.target.position.set(0, state.ground, 0);
  sun.position.copy(dir.clone().multiplyScalar(r * 3)).add(sun.target.position);
  fill.position.set(-dir.x, 0.6, -dir.z);
  const sc = sun.shadow.camera;
  sc.left = -r * 1.1; sc.right = r * 1.1; sc.top = r * 1.1; sc.bottom = -r * 1.1;
  sc.near = r * 0.5; sc.far = r * 6;
  sc.updateProjectionMatrix();
  sun.shadow.normalBias = Math.max(0.3, r / 1500);

  scene.fog.near = r * 4; scene.fog.far = r * 11;
  camera.far = r * 30; camera.near = Math.max(0.5, r / 2000);
  camera.updateProjectionMatrix();
  controls.maxDistance = r * 6;
  controls.minDistance = 5;
}

// Geländehöhe an einem Punkt (Python-Koordinaten x = Osten, y = Norden)
function groundAt(x, y) {
  const g = state.grid;
  if (!g) return state.ground || 0;
  const fi = Math.min(Math.max((x - g.x0) / g.cell, 0), g.nx - 1e-6);
  const fj = Math.min(Math.max((y - g.y0) / g.cell, 0), g.ny - 1e-6);
  const i = Math.floor(fi), j = Math.floor(fj), ti = fi - i, tj = fj - j;
  const k = (jj, ii) => g.z[jj * (g.nx + 1) + ii];
  const a = k(j, i) * (1 - ti) + k(j, i + 1) * ti;
  const b = k(j + 1, i) * (1 - ti) + k(j + 1, i + 1) * ti;
  return a * (1 - tj) + b * tj;
}

async function setTexture(url) {
  const texture = await new THREE.TextureLoader().loadAsync(url);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  if (state.mapTexture) state.mapTexture.dispose();
  state.mapTexture = texture;
  if (state.terrainMesh) {
    state.terrainMesh.material.map = texture;
    state.terrainMesh.material.needsUpdate = true;
  }
}

async function setOverlay(o) {
  const key = o ? o.rgba : null;
  if (key === state.overlayKey && state.overlayMesh) return;
  if (state.overlayMesh) { world.remove(state.overlayMesh); dispose(state.overlayMesh); state.overlayMesh = null; }
  state.overlayKey = key;
  if (!o || !state.terrainGeometry) return;
  const data = new Uint8Array(await decode(o.rgba));
  const tex = new THREE.DataTexture(data, o.nx, o.ny, THREE.RGBAFormat);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  const mat = new THREE.MeshStandardMaterial({
    map: tex, transparent: true, depthWrite: false, roughness: 0.9,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
  });
  state.overlayMesh = new THREE.Mesh(state.terrainGeometry, mat);
  state.overlayMesh.receiveShadow = true;
  state.overlayMesh.renderOrder = 1;
  state.overlayMesh.userData.sharedGeometry = true;
  world.add(state.overlayMesh);
}

// ---------------------------------------------------------------------------
// Gebäude
// ---------------------------------------------------------------------------
async function buildBuildings(b) {
  for (const obj of [state.buildingMesh, state.edgeLines]) {
    if (obj) { world.remove(obj); dispose(obj); }
  }
  state.buildingMesh = state.edgeLines = null;
  state.nBuildings = 0;
  if (!b || !b.n) return;

  const raw = new Int16Array(await decode(b.pos));
  const start = new Uint32Array(await decode(b.start));
  const s = b.scale;
  const nVert = raw.length / 3;
  const pos = new Float32Array(raw.length);
  for (let v = 0; v < nVert; v++) {
    pos[v * 3] = raw[v * 3] * s;
    pos[v * 3 + 1] = raw[v * 3 + 2] * s;
    pos[v * 3 + 2] = -raw[v * 3 + 1] * s;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(raw.length).fill(0.8), 3));
  geo.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  state.buildingMesh = mesh;
  state.start = start;
  state.nBuildings = b.n;
  state.nTriangles = nVert / 3;
  state.baseColors = new Float32Array(b.n * 3).fill(0.8);
  state.posOriginal = pos.slice();
  state.scaleKey = null;
  state.scaleArr = new Float32Array(b.n).fill(1);
  state.hidden = new Uint8Array(b.n);
  // Fußpunkt je Gebäude (für das "Zusammensacken" bei Schäden)
  state.baseY = new Float32Array(b.n).fill(Infinity);
  for (let i = 0; i < b.n; i++) {
    const [first, last] = buildingRange(i);
    for (let v = first; v < last; v++) state.baseY[i] = Math.min(state.baseY[i], pos[v * 3 + 1]);
  }

  // Feine Kanten: lassen die Baukörper wie ein Architekturmodell wirken
  state.edgeLines = makeEdges(geo);
  world.add(mesh, state.edgeLines);

  let top = state.ground;
  for (let v = 1; v < pos.length; v += 3) top = Math.max(top, pos[v]);
  state.top = top;
}

function makeEdges(geo) {
  return new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25),
    new THREE.LineBasicMaterial({ color: 0x33403f, transparent: true, opacity: 0.32 }));
}

// Höhenfaktor je Gebäude: 1 = unverändert, < 1 = (teilweise) eingestürzt
async function setBuildingScale(b64) {
  if (!state.buildingMesh || (b64 || null) === state.scaleKey) return;
  state.scaleKey = b64 || null;
  const scale = b64 ? new Float32Array(await decode(b64)) : null;
  state.scaleArr = new Float32Array(state.nBuildings).fill(1);
  if (scale) state.scaleArr.set(scale.subarray(0, state.nBuildings));
  applyHeights();
}

// Höhen aller Gebäude neu setzen (Einsturz-Faktor; eingesaugte Gebäude verschwinden nach unten)
function applyHeights() {
  if (!state.buildingMesh) return;
  const attr = state.buildingMesh.geometry.attributes.position;
  const src = state.posOriginal;
  for (let i = 0; i < state.nBuildings; i++) {
    const s = state.scaleArr ? state.scaleArr[i] : 1;
    const base = state.baseY[i];
    const [first, last] = buildingRange(i);
    for (let v = first; v < last; v++) {
      attr.array[v * 3 + 1] = state.hidden && state.hidden[i] ? -5000 : base + (src[v * 3 + 1] - base) * s;
    }
  }
  attr.needsUpdate = true;
  state.buildingMesh.geometry.computeVertexNormals();
  state.buildingMesh.geometry.computeBoundingSphere();
  world.remove(state.edgeLines);
  dispose(state.edgeLines);
  state.edgeLines = makeEdges(state.buildingMesh.geometry);
  world.add(state.edgeLines);
}

// Ein Gebäude als eigenes Objekt herauslösen (z. B. zum Einsaugen durch das Mutterschiff)
function liftBuilding(i) {
  if (!state.buildingMesh || i >= state.nBuildings || state.hidden[i]) return null;
  const [first, last] = buildingRange(i);
  const src = state.buildingMesh.geometry.attributes.position.array;
  const count = last - first;
  let cx = 0, cz = 0;
  for (let v = first; v < last; v++) { cx += src[v * 3]; cz += src[v * 3 + 2]; }
  cx /= count; cz /= count;
  const base = state.baseY[i];
  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
  for (let v = 0; v < count; v++) {
    pos[v * 3] = src[(first + v) * 3] - cx;
    pos[v * 3 + 1] = src[(first + v) * 3 + 1] - base;
    pos[v * 3 + 2] = src[(first + v) * 3 + 2] - cz;
    col[v * 3] = state.baseColors[i * 3]; col[v * 3 + 1] = state.baseColors[i * 3 + 1];
    col[v * 3 + 2] = state.baseColors[i * 3 + 2];
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  geo.computeVertexNormals();
  const piece = new THREE.Mesh(geo, state.buildingMesh.material);
  piece.castShadow = true;
  piece.add(makeEdges(geo));
  piece.position.set(cx, base, cz);
  world.add(piece);
  state.hidden[i] = 1;
  state.heightsDirty = true;
  return piece;
}

function restoreBuildings(indices) {
  if (!state.hidden) return;
  if (indices) for (const i of indices) state.hidden[i] = 0;
  else state.hidden.fill(0);
  state.heightsDirty = true;
}

function buildingRange(i) {
  const first = state.start[i];
  const last = i + 1 < state.nBuildings ? state.start[i + 1] : state.nTriangles;
  return [first * 3, last * 3];          // Eckpunkte
}

function paintBuilding(i, color) {
  const attr = state.buildingMesh.geometry.attributes.color;
  const [a, b] = buildingRange(i);
  for (let v = a; v < b; v++) attr.setXYZ(v, color.r, color.g, color.b);
}

async function setBuildingColors(b64) {
  if (!state.buildingMesh) return;
  const rgb = b64 ? new Uint8Array(await decode(b64)) : null;
  const c = new THREE.Color();
  for (let i = 0; i < state.nBuildings; i++) {
    if (rgb && rgb.length >= (i + 1) * 3) c.copy(srgb(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]));
    else c.copy(srgb(222, 218, 210));
    state.baseColors[i * 3] = c.r; state.baseColors[i * 3 + 1] = c.g; state.baseColors[i * 3 + 2] = c.b;
    paintBuilding(i, c);
  }
  state.hover = -1;
  state.buildingMesh.geometry.attributes.color.needsUpdate = true;
}

function ownerOf(triangle) {
  let lo = 0, hi = state.nBuildings - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (state.start[mid] <= triangle) lo = mid; else hi = mid - 1;
  }
  return lo;
}

// ---------------------------------------------------------------------------
// Analyse-Ebenen: Wasser, Fassaden, Düsen, Windpfeil
// ---------------------------------------------------------------------------
async function buildDynamic(s) {
  clearGroup(dynamic);
  state.facadeMesh = null;
  state.facadeTips = [];
  if (!state.terrainGeometry) return;
  const box = new THREE.Box3().setFromBufferAttribute(state.terrainGeometry.attributes.position);
  const width = box.max.x - box.min.x, depth = box.max.z - box.min.z;
  const bottom = box.min.y - state.plinth;

  if (s.water && Number.isFinite(s.water.level) && s.water.level > bottom) {
    const h = s.water.level - bottom;
    const geo = new THREE.BoxGeometry(width + 0.02, h, depth + 0.02);
    const water = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      color: 0x2c7fd0, transparent: true, opacity: 0.55, roughness: 0.08, metalness: 0,
      depthWrite: false,
    }));
    water.position.set((box.max.x + box.min.x) / 2, bottom + h / 2, (box.max.z + box.min.z) / 2);
    water.renderOrder = 2;
    const rim = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x1b5ea5, transparent: true, opacity: 0.5 }));
    rim.position.copy(water.position);
    dynamic.add(water, rim);
  }

  if (s.facades) {
    const raw = new Float32Array(await decode(s.facades.pos));
    const rgb = new Uint8Array(await decode(s.facades.colors));
    const n = raw.length / 18;                       // 2 Dreiecke je Fassade
    const pos = new Float32Array(raw.length);
    const col = new Float32Array(raw.length);
    for (let v = 0; v < raw.length / 3; v++) {
      pos[v * 3] = raw[v * 3]; pos[v * 3 + 1] = raw[v * 3 + 2]; pos[v * 3 + 2] = -raw[v * 3 + 1];
      const f = Math.floor(v / 6);
      const c = srgb(rgb[f * 3], rgb[f * 3 + 1], rgb[f * 3 + 2]);
      col[v * 3] = c.r; col[v * 3 + 1] = c.g; col[v * 3 + 2] = c.b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardNodeMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: 0.6 });
    mat.emissiveNode = vertexColor().mul(0.55);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.count = n;
    state.facadeMesh = mesh;
    state.facadeTips = s.facades.tips || [];
    dynamic.add(mesh);
  }

  if (s.paths) {
    const [r, g, b] = s.paths.color;
    const color = srgb(r, g, b);
    s.paths.lines.forEach((line, k) => {
      const pts = line.map(([x, y, z]) => new THREE.Vector3(x, z, -y));
      if (pts.length < 2) return;
      const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0);
      const geo = new THREE.TubeGeometry(curve, Math.max(2, pts.length * 4), s.paths.radius, 10, false);
      const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6, roughness: 0.4 });
      const tube = new THREE.Mesh(geo, mat);
      tube.userData.tip = (s.paths.tips || [])[k] || '';
      tube.castShadow = true;
      dynamic.add(tube);
    });
  }

  state.movers = [];
  for (const [kind, spec, make] of [['funnel', s.funnel, makeFunnel], ['monster', s.monster, makeMonster]]) {
    if (!spec) continue;
    const obj = make(spec);
    dynamic.add(obj);
    const a = THREE.MathUtils.degToRad(spec.heading || 0);
    state.movers.push({ kind, obj, x: spec.x, y: spec.y, fx: Math.sin(a), fy: Math.cos(a),
                        travel: spec.travel || 600, speed: spec.speed || 10,
                        size: kind === 'funnel' ? spec.core : spec.height });
  }

  if (s.arrow) {
    const d = THREE.MathUtils.degToRad(s.arrow.from_deg);
    const upwind = new THREE.Vector3(Math.sin(d), 0, -Math.cos(d));   // woher der Wind kommt
    const R = state.radius;
    const tail = upwind.clone().multiplyScalar(R * 1.25);
    const tip = upwind.clone().multiplyScalar(R * 0.62);
    const y = Math.max(s.arrow.z, state.top + R * 0.05);
    const color = srgb(30, 100, 200);
    const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35, roughness: 0.5 });
    const shaftLen = tail.distanceTo(tip);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.016, R * 0.016, shaftLen, 16), mat);
    const head = new THREE.Mesh(new THREE.ConeGeometry(R * 0.05, R * 0.13, 24), mat);
    const down = upwind.clone().negate();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), down);
    shaft.quaternion.copy(q);
    head.quaternion.copy(q);
    shaft.position.copy(tail.clone().add(tip).multiplyScalar(0.5)).setY(y);
    head.position.copy(tip.clone().add(down.clone().multiplyScalar(R * 0.065))).setY(y);
    shaft.castShadow = head.castShadow = true;
    dynamic.add(shaft, head);
  }
}

// Tornado: trichterförmiger Wirbel aus Wolkenbändern, unten eine Trümmerwolke
function makeFunnel(f) {
  const group = new THREE.Group();
  const h = f.height, r0 = f.core;
  const profile = [];
  for (let k = 0; k <= 24; k++) {
    const t = k / 24;
    profile.push(new THREE.Vector2(r0 * (0.35 + 1.6 * Math.pow(t, 2.2)), t * h));
  }
  const geo = new THREE.LatheGeometry(profile, 64);
  // gedrehte Streifen über Vertex-Farben: wirkt wie ein rotierender Wirbel
  const pos = geo.attributes.position, colors = new Float32Array(pos.count * 3);
  for (let v = 0; v < pos.count; v++) {
    const x = pos.getX(v), y = pos.getY(v), z = pos.getZ(v);
    const stripe = 0.5 + 0.5 * Math.sin(Math.atan2(z, x) * 5 + (y / h) * 14);
    const c = 0.42 + 0.22 * stripe;
    colors[v * 3] = c; colors[v * 3 + 1] = c * 1.02; colors[v * 3 + 2] = c * 1.06;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const cloud = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    vertexColors: true, transparent: true, opacity: 0.62, side: THREE.DoubleSide, depthWrite: false, roughness: 1 }));
  cloud.renderOrder = 3;
  const debris = new THREE.Mesh(new THREE.TorusGeometry(r0 * 1.3, r0 * 0.45, 12, 48),
    new THREE.MeshStandardMaterial({ color: 0x7b6f61, transparent: true, opacity: 0.55, depthWrite: false, roughness: 1 }));
  debris.rotation.x = Math.PI / 2;
  debris.position.y = r0 * 0.25;
  // Wolkendecke oben
  const top = new THREE.Mesh(new THREE.CylinderGeometry(r0 * 3.2, r0 * 2.2, h * 0.05, 48),
    new THREE.MeshStandardMaterial({ color: 0x5d6670, transparent: true, opacity: 0.4, depthWrite: false, roughness: 1 }));
  top.position.y = h;
  group.add(cloud, debris, top);
  group.position.set(f.x, groundAt(f.x, f.y), -f.y);
  return group;
}

// Kaiju: eigenes Riesenmonster aus Grundkörpern (Einheit = Körperhöhe)
function makeMonster(m) {
  const group = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0x433b63, roughness: 0.65, metalness: 0.05 });
  const belly = new THREE.MeshStandardMaterial({ color: 0x7a6aa8, roughness: 0.7 });
  const glow = new THREE.MeshStandardMaterial({ color: 0x9ff7e6, emissive: 0x6ff2d8, emissiveIntensity: 1.4 });
  const crystal = new THREE.MeshStandardMaterial({ color: 0xd8b4fe, emissive: 0xb07cf0,
                                                   emissiveIntensity: 0.9, roughness: 0.25 });
  const add = (geo, mat, x, y, z, rx = 0, ry = 0, rz = 0) => {
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    mesh.rotation.set(rx, ry, rz);
    mesh.castShadow = true;
    group.add(mesh);
    return mesh;
  };
  // Beine mit Drehpunkt in der Hüfte (für die Laufbewegung)
  const legs = [];
  for (const s of [-1, 1]) {
    const hip = new THREE.Group();
    hip.position.set(s * 0.1, 0.32, 0);
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.09, 0.32, 16), skin);
    leg.position.y = -0.16;
    const foot = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 10), skin);
    foot.position.set(0, -0.29, 0.04);
    foot.scale.set(1, 0.45, 1.5);
    leg.castShadow = foot.castShadow = true;
    hip.add(leg, foot);
    group.add(hip);
    legs.push(hip);
  }
  group.userData.legs = legs;
  // Rumpf, leicht nach vorn geneigt, mit hellerem Bauch
  add(new THREE.CapsuleGeometry(0.17, 0.3, 8, 20), skin, 0, 0.52, 0, 0.25);
  add(new THREE.CapsuleGeometry(0.12, 0.24, 8, 16), belly, 0, 0.5, 0.07, 0.25);
  // Kopf mit leuchtenden Augen und Kristallhörnern
  const head = add(new THREE.SphereGeometry(0.12, 24, 16), skin, 0, 0.86, 0.1);
  head.scale.set(1, 0.85, 1.15);
  add(new THREE.BoxGeometry(0.14, 0.06, 0.12), skin, 0, 0.81, 0.2);                      // Schnauze
  group.userData.eyes = [];
  for (const s of [-1, 1]) {
    group.userData.eyes.push(add(new THREE.SphereGeometry(0.022, 12, 8), glow, s * 0.05, 0.89, 0.205));
    add(new THREE.ConeGeometry(0.025, 0.16, 6), crystal, s * 0.07, 1.0, 0.06, -0.4, 0, -s * 0.45);
    // Arme und leuchtende Schulterkristalle
    add(new THREE.CapsuleGeometry(0.045, 0.22, 6, 12), skin, s * 0.2, 0.58, 0.1, -0.9, 0, s * 0.25);
    add(new THREE.OctahedronGeometry(0.06), crystal, s * 0.17, 0.72, -0.04, 0.3, 0.4, 0);
  }
  // Kristallreihe auf dem Rücken und Schwanz
  for (let k = 0; k < 4; k++) add(new THREE.OctahedronGeometry(0.045 - k * 0.006), crystal,
                                    0, 0.74 - k * 0.12, -0.15 - k * 0.03);
  add(new THREE.ConeGeometry(0.1, 0.6, 16), skin, 0, 0.26, -0.42, -Math.PI / 2 - 0.25, 0, 0);
  group.scale.setScalar(m.height);
  const h = THREE.MathUtils.degToRad(m.heading);
  group.rotation.y = Math.PI - h;                   // Blick in Laufrichtung
  group.position.set(m.x, groundAt(m.x, m.y), -m.y);
  return group;
}

// ---------------------------------------------------------------------------
// Kamera
// ---------------------------------------------------------------------------
function resetView(top = false) {
  // Modell-Quader: Gelände + Sockel + Gebäude
  const box = new THREE.Box3().setFromBufferAttribute(state.terrainGeometry.attributes.position);
  box.min.y -= state.plinth;
  box.max.y = Math.max(box.max.y, state.top);
  const target = box.getCenter(new THREE.Vector3());
  const el = THREE.MathUtils.degToRad(top ? 89.9 : 36), b = THREE.MathUtils.degToRad(top ? 0 : -18);
  const dir = new THREE.Vector3(Math.cos(el) * Math.sin(b), Math.sin(el), Math.cos(el) * Math.cos(b));
  camera.position.copy(target).addScaledVector(dir, fitDistance(box, target, dir));
  controls.target.copy(target);
  controls.update();
  invalidate(3);
}

// Kleinster Abstand, bei dem alle acht Ecken des Modells ins Bild passen
function fitDistance(box, target, dir, margin = 0.9) {
  const corners = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y])
    for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
  const p = new THREE.Vector3();
  const fits = (dist) => {
    camera.position.copy(target).addScaledVector(dir, dist);
    camera.lookAt(target);
    camera.updateMatrixWorld();
    return corners.every((c) => {
      p.copy(c).project(camera);
      return Math.abs(p.x) <= margin && Math.abs(p.y) <= margin && p.z < 1;
    });
  };
  let lo = state.radius * 0.1, hi = state.radius * 10;
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2;
    if (fits(mid)) hi = mid; else lo = mid;
  }
  return hi;
}

function cameraKey() { return 'terra-cam-' + state.terrainId; }

function saveCamera() {
  if (!state.cameraReady) return;          // erst speichern, wenn die Ansicht eingerichtet ist
  try {
    sessionStorage.setItem(cameraKey(), JSON.stringify({
      p: camera.position.toArray(), t: controls.target.toArray() }));
  } catch (e) { /* Speicher nicht verfügbar – egal */ }
}

function restoreCamera() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(cameraKey()) || 'null');
    if (!saved) return false;
    camera.position.fromArray(saved.p);
    controls.target.fromArray(saved.t);
    controls.update();
    invalidate(3);
    return true;
  } catch (e) { return false; }
}

document.getElementById('btn-reset').onclick = () => { setFollow(false); resetView(false); };
document.getElementById('btn-top').onclick = () => { setFollow(false); resetView(true); };

// Nik folgen: Kamera fliegt zu Nik und bleibt an ihm dran (drehen und zoomen geht weiter)
const nikButton = document.getElementById('btn-nik');
const nikPos = new THREE.Vector3();
function setFollow(on) {
  state.follow = on && crowd.mesh.count > 0;
  nikButton.classList.toggle('on', state.follow);
  if (!state.follow) return;
  crowd.nikPosition(nikPos);
  const offset = camera.position.clone().sub(controls.target).normalize();
  offset.y = Math.max(offset.y, 0.45);
  camera.position.copy(nikPos).addScaledVector(offset.normalize(), 26);
  controls.target.copy(nikPos);
  controls.update();
  invalidate(3);
}
function followNik() {
  if (!state.follow) return;
  crowd.nikPosition(nikPos);
  const delta = nikPos.clone().sub(controls.target);
  controls.target.add(delta);
  camera.position.add(delta);
}
nikButton.onclick = () => setFollow(!state.follow);
document.getElementById('compass').onclick = () => {
  // nach Norden drehen, Abstand und Neigung behalten
  const offset = camera.position.clone().sub(controls.target);
  const sph = new THREE.Spherical().setFromVector3(offset);
  sph.theta = 0;
  camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(sph));
  controls.update();
  invalidate(3);
};
const peopleButton = document.getElementById('btn-people');
peopleButton.onclick = () => {
  crowd.setEnabled(!crowd.enabled);
  peopleButton.classList.toggle('on', crowd.enabled);
  invalidate(2);
};
const shadowButton = document.getElementById('btn-shadow');
shadowButton.onclick = () => {
  effects = !effects;
  sun.castShadow = effects;
  shadowButton.classList.toggle('on', effects);
  invalidate(3);
};

// ---------------------------------------------------------------------------
// Infos beim Überfahren / Antippen
// ---------------------------------------------------------------------------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let pending = null;
let dragging = false;

renderer.domElement.addEventListener('pointerdown', () => { dragging = true; hideTip(); });
window.addEventListener('pointerup', () => { dragging = false; });
renderer.domElement.addEventListener('pointerleave', () => { hideTip(); setHover(-1); });
renderer.domElement.addEventListener('pointermove', (ev) => {
  if (dragging) return;
  if (!pending) requestAnimationFrame(pick);
  pending = ev;
});
renderer.domElement.addEventListener('click', (ev) => { pending = ev; pick(); });

function hideTip() { tip.style.display = 'none'; }

function setHover(i) {
  if (!state.buildingMesh || i === state.hover) return;
  const attr = state.buildingMesh.geometry.attributes.color;
  const c = new THREE.Color();
  if (state.hover >= 0) {
    const h = state.hover;
    paintBuilding(h, c.setRGB(state.baseColors[h * 3], state.baseColors[h * 3 + 1], state.baseColors[h * 3 + 2]));
  }
  if (i >= 0) {
    c.setRGB(state.baseColors[i * 3], state.baseColors[i * 3 + 1], state.baseColors[i * 3 + 2]);
    paintBuilding(i, c.lerp(srgb(11, 110, 116), 0.35));
  }
  state.hover = i;
  attr.needsUpdate = true;
  invalidate(2);
}

function pick() {
  const ev = pending;
  pending = null;
  if (!ev) return;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const targets = [];
  if (state.buildingMesh) targets.push(state.buildingMesh);
  for (const child of dynamic.children) if (child.isMesh && (child === state.facadeMesh || child.userData.tip)) targets.push(child);
  const hit = raycaster.intersectObjects(targets, false)[0];
  let html = '', building = -1;
  if (hit) {
    if (hit.object === state.buildingMesh) {
      building = ownerOf(hit.faceIndex);
      html = state.tips[building] || '';
    } else if (hit.object === state.facadeMesh) {
      html = state.facadeTips[Math.floor(hit.faceIndex / 2)] || '';
    } else {
      html = hit.object.userData.tip || '';
    }
  }
  setHover(building);
  if (!html) { hideTip(); return; }
  tip.innerHTML = html;
  tip.style.display = 'block';
  const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x + 14, rect.width - w - 6) + 'px';
  tip.style.top = (y + 16 + h > rect.height ? y - h - 10 : y + 16) + 'px';
}

// ---------------------------------------------------------------------------
// Neue Daten von Python
// ---------------------------------------------------------------------------
async function update(args) {
  const s = args.scene || {};
  const height = args.height || 600;
  if (height !== state.height) {
    state.height = height;
    view.style.height = height + 'px';
    send('streamlit:setFrameHeight', { height });
  }

  let newModel = false;
  if (s.texture && s.texture !== state.textureUrl) {
    state.textureUrl = s.texture;
    await setTexture(s.texture);
  }
  if (s.terrain && s.terrain.id !== state.terrainId) {
    state.cameraReady = false;
    await buildTerrain(s.terrain);
    state.terrainId = s.terrain.id;
    state.overlayKey = null;
    newModel = true;
  }
  const buildingsId = s.buildings ? s.buildings.id : null;
  if (buildingsId !== state.buildingsId) {
    await buildBuildings(s.buildings);
    state.buildingsId = buildingsId;
  }
  await setBuildingScale(s.building_scale);
  await setBuildingColors(s.building_colors);
  state.tips = s.building_tips || [];
  await setOverlay(s.overlay);
  await buildDynamic(s);
  const wanted = s.people ? s.people.count : 300;
  if (newModel) crowd.setWalkways(s.walkways, wanted);
  else if (wanted !== crowd.wanted) crowd.setCount(wanted);
  peopleButton.disabled = nikButton.disabled = crowd.mesh.count === 0;
  if (crowd.mesh.count === 0) setFollow(false);
  fx.configure(s.monster, s.ufos);
  await flow.set(s.flow || null);
  vortex.set(s.funnel || null);
  counter.style.display = s.ufos ? 'block' : 'none';
  state.hazard = s.hazard || null;
  crowd.setHazard(state.hazard, s.water ? s.water.level : null);

  if (newModel) {
    resize();
    if (!restoreCamera()) resetView(false);
    state.cameraReady = true;
  }
  badge.textContent = `three.js · ${backendName}`;
  msg.style.display = 'none';
  invalidate(3);
}

// Für die Fehlersuche in der Browser-Konsole: window.terra.camera usw.
window.terra = { THREE, renderer, scene, camera, controls, sun, state, invalidate, crowd, fx, flow, vortex };

let queue = Promise.resolve();
window.addEventListener('message', (ev) => {
  const data = ev.data;
  if (!data || data.type !== 'streamlit:render') return;
  queue = queue.then(() => update(data.args)).catch((err) => {
    console.error(err);
    msg.style.display = 'flex';
    msg.textContent = '3D-Ansicht: ' + (err && err.message ? err.message : err);
  });
});
send('streamlit:componentReady', { apiVersion: 1 });
