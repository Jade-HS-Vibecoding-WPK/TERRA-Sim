// TERRA-Sim – animierte Luftströmung
//
// Python (simulator.wind_field) liefert das Strömungsfeld in 2 m Höhe: je
// Rasterzelle Wind nach Osten (u) und Norden (v). Hier fließen Teilchen durch
// dieses Feld – als kleine Striche, deren Länge und Farbe die Geschwindigkeit
// zeigen. Eine zweite Schicht zieht ungestört über die Dächer.
//
// Koordinaten wie in scene.py: x = Osten, y = Norden; three.js: (x, Höhe, -y).
//
// VortexParticles: Staub und Trümmer, die um den Tornado-Trichter wirbeln.

const RAMP = [[98, 184, 120], [196, 160, 230], [140, 70, 196], [200, 32, 52]];   // wie viewer_3d "wind"
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

// ---------------------------------------------------------------------------
// Tornado: Wirbelteilchen
// ---------------------------------------------------------------------------
//
// Gleicher Wirbel wie in hazards.tornado_speed (Rankine): innerhalb des Kerns
// wächst die Drehgeschwindigkeit mit dem Abstand, außerhalb nimmt sie mit 1/r ab.
// Am Boden strömen die Teilchen spiralförmig nach innen, im Trichter steigen sie
// auf und weiten sich wie der Trichter. Drehsinn gegen den Uhrzeiger (Nordhalbkugel).

const DUST = [[176, 160, 138], [140, 126, 110], [205, 192, 172]];
const DEBRIS = [[92, 80, 70], [120, 98, 76], [70, 70, 74]];

export class VortexParticles {
  constructor(THREE, parent, groundAt) {
    this.T = THREE;
    this.groundAt = groundAt;
    this.max = 1800;
    this.mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({ roughness: 1 }), this.max);
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(this.max * 3).fill(1), 3);
    this.mesh.frustumCulled = false;
    this.mesh.castShadow = true;
    this.mesh.count = 0;
    parent.add(this.mesh);
    const n = this.max;
    this.r = new Float32Array(n); this.a = new Float32Array(n); this.h = new Float32Array(n);
    this.age = new Float32Array(n); this.life = new Float32Array(n); this.kind = new Uint8Array(n);
    this.size = new Float32Array(n); this.spin = new Float32Array(n);
    this.spec = null;
    this.key = null;
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._p = new THREE.Vector3();
    this._s = new THREE.Vector3(); this._d = new THREE.Vector3(); this._z = new THREE.Vector3(0, 0, 1);
    this._e = new THREE.Euler(); this._c = new THREE.Color();
  }

  get active() { return this.mesh.count > 0; }

  set(funnel) {
    const key = funnel ? JSON.stringify([funnel.core, funnel.height, funnel.vrot]) : null;
    if (key === this.key) return;
    this.key = key;
    this.spec = funnel || null;
    if (!funnel) { this.mesh.count = 0; return; }
    // mehr Teilchen bei stärkeren Tornados
    const count = Math.min(this.max, Math.round(500 + (funnel.vrot || 40) * 18));
    this.mesh.count = count;
    for (let i = 0; i < count; i++) {
      this.kind[i] = Math.random() < 0.22 ? 1 : 0;                  // 1 = Trümmer, 0 = Staub
      const palette = this.kind[i] ? DEBRIS : DUST;
      const c = palette[i % palette.length];
      this.mesh.setColorAt(i, this._c.setRGB(c[0] / 255, c[1] / 255, c[2] / 255, this.T.SRGBColorSpace));
      this.spawn(i, true);
    }
    this.mesh.instanceColor.needsUpdate = true;
  }

  // Radius des Trichters in einer Höhe – wie die Wolkenhülle in viewer.js
  funnelRadius(h) {
    const s = this.spec;
    return s.core * (0.35 + 1.6 * Math.pow(Math.min(1, Math.max(0, h / s.height)), 2.2));
  }

  spawn(i, anywhere = false) {
    const s = this.spec;
    const inColumn = anywhere ? Math.random() < 0.6 : Math.random() < 0.3;
    if (inColumn) {                                                 // schon im Trichter
      this.h[i] = Math.random() * s.height * (this.kind[i] ? 0.35 : 0.9);
      this.r[i] = this.funnelRadius(this.h[i]) * rand(0.6, 1.1);
    } else {                                                        // vom Boden angesaugt
      this.h[i] = rand(0.2, 6);
      this.r[i] = s.core * rand(1.2, 4);
    }
    this.a[i] = Math.random() * Math.PI * 2;
    this.age[i] = 0;
    this.life[i] = rand(6, 14);
    this.size[i] = this.kind[i] ? rand(0.8, 2.6) : rand(0.5, 1.4);
    this.spin[i] = rand(-6, 6);
  }

  update(dt, center) {
    const s = this.spec;
    if (!s || !center) return;
    const vrot = s.vrot || 40, core = s.core, H = s.height;
    const ground = this.groundAt(center.x, center.y);
    const n = this.mesh.count;
    for (let i = 0; i < n; i++) {
      const r = Math.max(1, this.r[i]);
      // Drehgeschwindigkeit (Rankine) – innen wie ein starrer Körper, außen ~1/r
      const vt = r < core ? vrot * r / core : vrot * core / r;
      this.a[i] += (vt / r) * dt;
      const nearGround = this.h[i] < 12;
      if (nearGround && r > core * 0.6) {
        this.r[i] -= vt * 0.35 * dt;                                // am Boden nach innen
        this.h[i] += dt * (r < core * 1.4 ? 6 : 0.6);
      } else {
        const lift = (this.kind[i] ? 0.18 : 0.32) * vrot;           // Trümmer steigen langsamer
        this.h[i] += lift * dt;
        this.r[i] += (this.funnelRadius(this.h[i]) * 0.9 - this.r[i]) * Math.min(1, dt * 0.8);
      }
      this.age[i] += dt;
      // Trümmer werden oben hinausgeschleudert, Staub löst sich im Wolkenkragen auf
      if (this.h[i] > H * (this.kind[i] ? 0.4 : 0.95) || this.age[i] > this.life[i]) {
        if (this.kind[i] && this.h[i] > H * 0.4) this.r[i] += vt * dt * 3;
        if (this.r[i] > core * 6 || this.h[i] > H * 0.95 || this.age[i] > this.life[i]) this.spawn(i);
      }
      const x = center.x + Math.cos(this.a[i]) * this.r[i];
      const y = center.y + Math.sin(this.a[i]) * this.r[i];
      this._p.set(x, ground + this.h[i], -y);
      if (this.kind[i]) {                                           // Trümmer: taumelnde Brocken
        this._e.set(this.age[i] * this.spin[i], this.age[i] * this.spin[i] * 0.7, this.age[i] * 0.5);
        this._q.setFromEuler(this._e);
        this._s.setScalar(this.size[i]);
      } else {                                                      // Staub: Strich in Drehrichtung
        this._d.set(-Math.sin(this.a[i]), 0.15, -Math.cos(this.a[i]));
        this._q.setFromUnitVectors(this._z, this._d.normalize());
        const fade = Math.sin(Math.PI * Math.min(1, this.age[i] / this.life[i]));
        const thick = this.size[i] * (0.4 + 0.6 * fade);
        this._s.set(thick, thick, Math.min(14, 1 + vt * 0.25));
      }
      this._m.compose(this._p, this._q, this._s);
      this.mesh.setMatrixAt(i, this._m);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }
}
