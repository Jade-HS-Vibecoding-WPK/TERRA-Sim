// TERRA-Sim – animierte Luftströmung
//
// Python (simulator.wind_field) liefert das Strömungsfeld in 2 m Höhe: je
// Rasterzelle Wind nach Osten (u) und Norden (v). Hier fließen Teilchen durch
// dieses Feld – als kleine Striche, deren Länge und Farbe die Geschwindigkeit
// zeigen. Eine zweite Schicht zieht ungestört über die Dächer.
//
// Koordinaten wie in scene.py: x = Osten, y = Norden; three.js: (x, Höhe, -y).

const RAMP = [[116, 196, 118], [255, 217, 79], [244, 109, 67], [165, 0, 38]];   // wie viewer_3d "wind"
const rand = (a, b) => a + Math.random() * (b - a);

async function decode(b64) {
  const response = await fetch('data:application/octet-stream;base64,' + b64);
  return response.arrayBuffer();
}

export class FlowParticles {
  constructor(THREE, parent, groundAt) {
    this.T = THREE;
    this.groundAt = groundAt;
    this.max = 2400;
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    this.mesh = new THREE.InstancedMesh(geometry, new THREE.MeshBasicMaterial({ toneMapped: false }), this.max);
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(this.max * 3).fill(1), 3);
    this.mesh.frustumCulled = false;
    this.mesh.count = 0;
    parent.add(this.mesh);
    const n = this.max;
    this.x = new Float32Array(n); this.y = new Float32Array(n); this.h = new Float32Array(n);
    this.age = new Float32Array(n); this.life = new Float32Array(n); this.upper = new Uint8Array(n);
    this.spec = null;
    this.key = null;
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._p = new THREE.Vector3();
    this._s = new THREE.Vector3(); this._d = new THREE.Vector3(); this._z = new THREE.Vector3(0, 0, 1);
    this._c = new THREE.Color();
  }

  get active() { return this.mesh.count > 0; }

  async set(spec) {
    const key = spec ? spec.u + spec.v + spec.particles : null;
    if (key === this.key) return;
    this.key = key;
    if (!spec) { this.spec = null; this.mesh.count = 0; return; }
    const u = new Int8Array(await decode(spec.u));
    const v = new Int8Array(await decode(spec.v));
    const solid = new Uint8Array(await decode(spec.solid));
    this.spec = { ...spec, u, v, solid };
    const count = Math.min(this.max, spec.particles + Math.round(spec.particles / 3));
    this.mesh.count = count;
    for (let i = 0; i < count; i++) {
      this.upper[i] = i >= spec.particles ? 1 : 0;
      this.spawn(i, true);
    }
  }

  // Wind (m/s) an einem Punkt in 2 m Höhe – bilinear zwischen den Zellmitten
  sample(x, y) {
    const s = this.spec;
    if (!s) return null;
    const fx = (x - s.x0) / s.cell - 0.5, fy = (y - s.y0) / s.cell - 0.5;
    if (fx < 0 || fy < 0 || fx > s.nx - 1 || fy > s.ny - 1) return [0, 0];
    const i = Math.min(Math.floor(fx), s.nx - 2), j = Math.min(Math.floor(fy), s.ny - 2);
    const tx = fx - i, ty = fy - j;
    const at = (arr, jj, ii) => arr[jj * s.nx + ii];
    const lerp = (arr) => (at(arr, j, i) * (1 - tx) + at(arr, j, i + 1) * tx) * (1 - ty)
                        + (at(arr, j + 1, i) * (1 - tx) + at(arr, j + 1, i + 1) * tx) * ty;
    return [lerp(s.u) * s.scale, lerp(s.v) * s.scale];
  }

  isSolid(x, y) {
    const s = this.spec;
    const i = Math.floor((x - s.x0) / s.cell), j = Math.floor((y - s.y0) / s.cell);
    if (i < 0 || j < 0 || i >= s.nx || j >= s.ny) return true;
    return s.solid[j * s.nx + i] === 1;
  }

  spawn(i, anywhere = false) {
    const s = this.spec;
    const w = s.nx * s.cell, hgt = s.ny * s.cell;
    for (let tries = 0; tries < 12; tries++) {
      // meist irgendwo im Gebiet, sonst am Rand, von dem der Wind kommt
      let x = s.x0 + Math.random() * w, y = s.y0 + Math.random() * hgt;
      if (!anywhere && Math.random() < 0.35) {
        const [dx, dy] = s.upper_dir;
        if (Math.abs(dx) > Math.abs(dy)) x = dx > 0 ? s.x0 + 1 : s.x0 + w - 1;
        else y = dy > 0 ? s.y0 + 1 : s.y0 + hgt - 1;
      }
      if (this.upper[i] || !this.isSolid(x, y)) {
        this.x[i] = x; this.y[i] = y;
        break;
      }
    }
    this.h[i] = this.upper[i] ? s.top + rand(6, 35) : rand(1.2, 3.5);
    this.life[i] = rand(3, 7);
    this.age[i] = anywhere ? Math.random() * this.life[i] : 0;
  }

  update(dt) {
    const s = this.spec;
    if (!s) return;
    const n = this.mesh.count;
    for (let i = 0; i < n; i++) {
      let u, v;
      if (this.upper[i]) {
        u = s.upper_dir[0] * s.upper_speed; v = s.upper_dir[1] * s.upper_speed;
      } else {
        [u, v] = this.sample(this.x[i], this.y[i]);
      }
      const speed = Math.hypot(u, v);
      this.x[i] += u * dt; this.y[i] += v * dt;
      this.age[i] += dt * (speed < 0.5 && !this.upper[i] ? 3 : 1);   // in Flaute schneller erneuern
      const outside = this.x[i] < s.x0 || this.y[i] < s.y0 || this.x[i] > s.x0 + s.nx * s.cell
                   || this.y[i] > s.y0 + s.ny * s.cell;
      if (this.age[i] > this.life[i] || outside || (!this.upper[i] && this.isSolid(this.x[i], this.y[i]))) {
        this.spawn(i);
      }
      // Strich: Länge ~ Geschwindigkeit, dünner beim Erscheinen und Verschwinden
      const fade = Math.sin(Math.PI * Math.min(1, this.age[i] / this.life[i]));
      const len = Math.min(16, Math.max(1.2, speed * 0.55));
      const thick = (this.upper[i] ? 0.7 : 0.45) * (0.3 + 0.7 * fade);
      this._d.set(u, 0, -v);
      if (speed > 1e-3) this._q.setFromUnitVectors(this._z, this._d.normalize());
      // unten: Höhe über dem Gelände; oben: feste Höhe über den Dächern
      const base = this.upper[i] ? 0 : this.groundAt(this.x[i], this.y[i]);
      this._p.set(this.x[i], base + this.h[i], -this.y[i]);
      this._s.set(thick, thick, len * (0.4 + 0.6 * fade));
      this._m.compose(this._p, this._q, this._s);
      this.mesh.setMatrixAt(i, this._m);
      // Farbe nach Geschwindigkeit (0 … 20 m/s)
      const t = Math.min(1, speed / 20) * (RAMP.length - 1);
      const k = Math.min(RAMP.length - 2, Math.floor(t)), f = t - k;
      const a = RAMP[k], b = RAMP[k + 1];
      this._c.setRGB((a[0] + (b[0] - a[0]) * f) / 255, (a[1] + (b[1] - a[1]) * f) / 255,
                     (a[2] + (b[2] - a[2]) * f) / 255, this.T.SRGBColorSpace);
      this.mesh.setColorAt(i, this._c);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
    this.mesh.instanceColor.needsUpdate = true;
  }
}
