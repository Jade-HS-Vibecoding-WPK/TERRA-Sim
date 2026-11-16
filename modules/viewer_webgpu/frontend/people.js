// TERRA-Sim – Menschen, die sich durch das Gebiet bewegen
//
// Jede Person ist ein kleiner Zylinder mit runder Kuppel (1,75 m hoch). Alle
// Personen sind EIN InstancedMesh – so bleiben auch ein paar hundert flüssig.
// Sie laufen auf den Straßen und Wegen hin und her und reagieren auf die
// Gefahr der jeweiligen Analyse:
//
//   wind     ab Bft 8 kommen sie kaum voran, ab Bft 9 werden sie umgeweht/weggetragen
//   tornado  in der Nähe fliehen sie, im Kern werden sie hochgesaugt und weggeschleudert
//   kaiju    sie fliehen vor dem Monster, unter seinen Füßen fliegen sie davon
//   quake    sie wackeln, bei starken Beben stürzen sie hin
//   flood    wo das Wasser steht, schwimmen sie
//
// Koordinaten wie in scene.py: x = Osten, y = Norden (Meter); three.js: (x, Höhe, -y).

const WALK = 0, FLY = 1, DOWN = 2, VORTEX = 3, FLEE = 4;
const BODY_HEIGHT = 1.75;
const CLOTHES = [0x2f5d8a, 0xc0392b, 0x2e8b57, 0xe0a030, 0x6c4f9c, 0x34495e, 0xd35400, 0x16a085,
                 0x7f8c8d, 0xb03a6a, 0x1f3a5f, 0xf2f2f2];

const rand = (a, b) => a + Math.random() * (b - a);

export class Crowd {
  constructor(THREE, parent, groundAt) {
    this.T = THREE;
    this.groundAt = groundAt;
    // Profil: Boden, senkrechte Wand, oben eine Halbkugel als "Kopf"
    const r = 0.27, h = BODY_HEIGHT;
    const profile = [new THREE.Vector2(0, 0), new THREE.Vector2(r, 0), new THREE.Vector2(r, h - r)];
    for (let k = 1; k <= 6; k++) {
      const a = (k / 6) * Math.PI / 2;
      profile.push(new THREE.Vector2(Math.max(1e-4, r * Math.cos(a)), h - r + r * Math.sin(a)));
    }
    const geometry = new THREE.LatheGeometry(profile, 14);
    this.max = 500;
    this.mesh = new THREE.InstancedMesh(geometry, new THREE.MeshStandardMaterial({ roughness: 0.75 }), this.max);
    this.mesh.castShadow = true;
    this.mesh.frustumCulled = false;
    this.mesh.count = 0;
    // Farben gleich anlegen – sonst kennt das schon übersetzte Material sie nicht
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(this.max * 3).fill(1), 3);
    parent.add(this.mesh);

    const n = this.max;
    this.mode = new Uint8Array(n);
    this.line = new Int32Array(n);
    this.s = new Float32Array(n);            // Position entlang der Linie (m)
    this.dir = new Float32Array(n);          // +1 / −1
    this.speed = new Float32Array(n);
    this.x = new Float32Array(n); this.y = new Float32Array(n); this.z = new Float32Array(n);
    this.vx = new Float32Array(n); this.vy = new Float32Array(n); this.vz = new Float32Array(n);
    this.yaw = new Float32Array(n); this.tilt = new Float32Array(n); this.roll = new Float32Array(n);
    this.spin = new Float32Array(n);
    this.timer = new Float32Array(n);
    this.angle = new Float32Array(n); this.radius = new Float32Array(n);
    this.respawn = new Uint8Array(n);

    this.lines = [];
    this.hazard = null;
    this.waterLevel = null;
    this.enabled = true;
    this._m = new THREE.Matrix4();
    this._q = new THREE.Quaternion();
    this._e = new THREE.Euler(0, 0, 0, 'YXZ');
    this._p = new THREE.Vector3();
    this._s = new THREE.Vector3(1, 1, 1);
  }

  get active() { return this.enabled && this.mesh.count > 0; }

  setEnabled(on) {
    this.enabled = on;
    this.mesh.visible = on;
  }

  // Straßen und Wege: Liste von Linien [[x, y], ...]
  setWalkways(lines) {
    this.lines = [];
    let total = 0;
    for (const pts of lines || []) {
      if (pts.length < 2) continue;
      const cum = [0];
      for (let k = 1; k < pts.length; k++) {
        cum.push(cum[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]));
      }
      if (cum[cum.length - 1] < 3) continue;
      total += cum[cum.length - 1];
      this.lines.push({ pts, cum, length: cum[cum.length - 1], start: total - cum[cum.length - 1] });
    }
    this.total = total;
    const count = this.lines.length ? Math.round(Math.min(this.max, Math.max(40, total / 9))) : 0;
    this.mesh.count = count;
    const color = new this.T.Color();
    for (let i = 0; i < count; i++) {
      this.mesh.setColorAt(i, color.setHex(CLOTHES[i % CLOTHES.length]));
      this.spawn(i);
    }
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }

  setHazard(hazard, waterLevel) {
    this.hazard = hazard || null;
    this.waterLevel = Number.isFinite(waterLevel) ? waterLevel : null;
  }

  spawn(i) {
    // zufällige Stelle, gewichtet nach Weglänge
    const target = Math.random() * this.total;
    let lo = 0, hi = this.lines.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.lines[mid].start <= target) lo = mid; else hi = mid - 1;
    }
    this.line[i] = lo;
    this.s[i] = Math.random() * this.lines[lo].length;
    this.dir[i] = Math.random() < 0.5 ? -1 : 1;
    this.speed[i] = rand(1.0, 1.6);
    this.mode[i] = WALK;
    this.tilt[i] = this.roll[i] = 0;
    this.respawn[i] = 0;
    this.placeOnLine(i);
  }

  placeOnLine(i) {
    const L = this.lines[this.line[i]];
    const s = Math.min(Math.max(this.s[i], 0), L.length);
    let k = 1;
    while (k < L.cum.length - 1 && L.cum[k] < s) k++;
    const a = L.pts[k - 1], b = L.pts[k];
    const seg = Math.max(1e-6, L.cum[k] - L.cum[k - 1]);
    const t = (s - L.cum[k - 1]) / seg;
    this.x[i] = a[0] + (b[0] - a[0]) * t;
    this.z[i] = a[1] + (b[1] - a[1]) * t;
    const dx = (b[0] - a[0]) * this.dir[i], dy = (b[1] - a[1]) * this.dir[i];
    this.yaw[i] = Math.atan2(dx, -dy);
    this.y[i] = this.groundAt(this.x[i], this.z[i]);
  }

  launch(i, vx, vy, vz) {
    this.mode[i] = FLY;
    this.vx[i] = vx; this.vy[i] = vy; this.vz[i] = vz;
    this.spin[i] = rand(4, 12) * (Math.random() < 0.5 ? -1 : 1);
    this.respawn[i] = 1;
  }

  fallDown(i, seconds, respawn) {
    this.mode[i] = DOWN;
    this.timer[i] = seconds;
    this.tilt[i] = Math.PI / 2;
    this.respawn[i] = respawn ? 1 : 0;
  }

  flee(i, fromX, fromY) {
    const dx = this.x[i] - fromX, dy = this.z[i] - fromY, d = Math.hypot(dx, dy) || 1;
    this.mode[i] = FLEE;
    this.vx[i] = dx / d * rand(3.5, 5); this.vz[i] = dy / d * rand(3.5, 5);
    this.yaw[i] = Math.atan2(dx, -dy);
    this.timer[i] = rand(6, 10);
  }

  // ctx: aktuelle Position von Tornado / Monster (bewegen sich)
  update(dt, time, ctx = {}) {
    if (!this.active) return;
    dt = Math.min(dt, 0.1);
    const h = this.hazard;
    const n = this.mesh.count;
    for (let i = 0; i < n; i++) {
      const ground = this.groundAt(this.x[i], this.z[i]);
      switch (this.mode[i]) {
        case WALK: this.walk(i, dt, time, h, ctx, ground); break;
        case FLEE: {
          this.x[i] += this.vx[i] * dt; this.z[i] += this.vz[i] * dt;
          this.y[i] = this.groundAt(this.x[i], this.z[i]);
          this.tilt[i] = 0.25;   // nach vorn gebeugt rennen
          this.timer[i] -= dt;
          this.react(i, h, ctx);
          if (this.mode[i] === FLEE && this.timer[i] <= 0) this.spawn(i);
          break;
        }
        case FLY: {
          const wind = h && h.type === 'wind' ? this.windVector(h) : null;
          if (wind) {                                  // Luftwiderstand: Wind trägt weiter
            this.vx[i] += (wind[0] * 0.6 - this.vx[i]) * 0.6 * dt;
            this.vz[i] += (wind[1] * 0.6 - this.vz[i]) * 0.6 * dt;
          }
          this.vy[i] -= 9.81 * dt;
          this.x[i] += this.vx[i] * dt; this.y[i] += this.vy[i] * dt; this.z[i] += this.vz[i] * dt;
          this.tilt[i] += this.spin[i] * dt; this.roll[i] += this.spin[i] * 0.7 * dt;
          const g = this.groundAt(this.x[i], this.z[i]);
          if (this.y[i] <= g && this.vy[i] < 0) { this.y[i] = g; this.fallDown(i, rand(3, 6), true); }
          break;
        }
        case VORTEX: {
          const f = ctx.funnel;
          if (!f) { this.launch(i, 0, 0, 0); break; }
          this.angle[i] += (22 / Math.max(3, this.radius[i])) * dt;
          this.radius[i] += (f.core * 0.7 - this.radius[i]) * dt;
          this.y[i] += rand(5, 9) * dt;
          this.x[i] = f.x + Math.cos(this.angle[i]) * this.radius[i];
          this.z[i] = f.y + Math.sin(this.angle[i]) * this.radius[i];
          this.tilt[i] += 6 * dt; this.roll[i] += 4 * dt;
          if (this.y[i] - ground > this.timer[i]) {   // in der Höhe hinausgeschleudert
            const tx = -Math.sin(this.angle[i]), tz = Math.cos(this.angle[i]);
            this.launch(i, tx * 25 + Math.cos(this.angle[i]) * 10, rand(2, 8), tz * 25 + Math.sin(this.angle[i]) * 10);
          }
          break;
        }
        case DOWN: {
          this.y[i] = ground;
          this.timer[i] -= dt;
          if (this.timer[i] <= 0) {
            if (this.respawn[i]) this.spawn(i);
            else { this.mode[i] = WALK; this.tilt[i] = 0; this.roll[i] = 0; }
          }
          break;
        }
      }
      this.write(i, time);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  windVector(h) {
    // Windgeschwindigkeit aus Beaufort: v = 0,836 · B^1,5 (m/s), weht VON from_deg
    const v = 0.836 * Math.pow(h.bft, 1.5);
    const a = h.from_deg * Math.PI / 180;
    return [-Math.sin(a) * v, -Math.cos(a) * v];
  }

  // Gefahr in der Nähe? -> fliehen, wegfliegen …
  react(i, h, ctx) {
    if (!h) return;
    if (h.type === 'tornado' && ctx.funnel) {
      const f = ctx.funnel, d = Math.hypot(this.x[i] - f.x, this.z[i] - f.y);
      if (d < f.core * 1.3) {
        this.mode[i] = VORTEX;
        this.angle[i] = Math.atan2(this.z[i] - f.y, this.x[i] - f.x);
        this.radius[i] = d;
        this.timer[i] = rand(25, 90);                   // Höhe, in der er losgelassen wird
        this.respawn[i] = 1;
      } else if (d < f.core * 2.5 && this.mode[i] === WALK) {
        this.flee(i, f.x, f.y);
      }
    } else if (h.type === 'kaiju' && ctx.monster) {
      const m = ctx.monster, d = Math.hypot(this.x[i] - m.x, this.z[i] - m.y);
      if (d < m.height * 0.22) {
        const dx = (this.x[i] - m.x) / (d || 1), dz = (this.z[i] - m.y) / (d || 1);
        this.launch(i, dx * rand(8, 16), rand(10, 22), dz * rand(8, 16));
      } else if (d < m.height * 0.9 && this.mode[i] === WALK) {
        this.flee(i, m.x, m.y);
      }
    }
  }

  walk(i, dt, time, h, ctx, ground) {
    let factor = 1;
    this.tilt[i] = 0;
    this.roll[i] = 0;
    if (h && h.type === 'wind' && h.bft >= 7) {
      factor = Math.max(0.35, 1 - (h.bft - 7) * 0.13);
      this.tilt[i] = Math.min(0.5, (h.bft - 6) * 0.07);   // gegen den Wind lehnen
      const p = h.bft > 8 ? 0.06 * Math.pow((h.bft - 8) / 4, 2) : 0;
      if (Math.random() < p * dt) {
        const [wx, wz] = this.windVector(h);
        this.launch(i, wx * rand(0.3, 0.6), rand(3, 4 + h.bft), wz * rand(0.3, 0.6));
        return;
      }
      if (h.bft >= 9 && Math.random() < 0.03 * (h.bft - 8) * dt) { this.fallDown(i, rand(2, 4), false); return; }
    } else if (h && h.type === 'quake') {
      const shaking = h.shaking;
      if (shaking > 0) {
        const amp = Math.min(0.6, 0.06 * Math.max(0, h.intensity - 3)) * shaking;
        this.tilt[i] = Math.sin(time * 23 + i) * amp;
        this.roll[i] = Math.cos(time * 19 + i * 1.7) * amp;
        factor = Math.max(0, 1 - 0.15 * (h.intensity - 4));
        if (h.intensity >= 6.5 && Math.random() < 0.08 * (h.intensity - 6) * shaking * dt) {
          this.fallDown(i, rand(2, 4), false);
          return;
        }
      }
    } else {
      this.react(i, h, ctx);
      if (this.mode[i] !== WALK) return;
    }

    const L = this.lines[this.line[i]];
    this.s[i] += this.dir[i] * this.speed[i] * factor * dt;
    if (this.s[i] <= 0 || this.s[i] >= L.length) {
      this.dir[i] *= -1;
      this.s[i] = Math.min(Math.max(this.s[i], 0), L.length);
    }
    this.placeOnLine(i);
    // schwimmen, wo das Hochwasser steht
    if (this.waterLevel !== null && this.waterLevel > ground + 0.5) {
      this.y[i] = this.waterLevel - BODY_HEIGHT * 0.65 + Math.sin(time * 2 + i) * 0.08;
      this.tilt[i] = 0.35;
    }
  }

  write(i, time) {
    const bob = this.mode[i] === WALK ? Math.abs(Math.sin(time * 7 + i)) * 0.05 : 0;
    this._e.set(this.tilt[i], this.yaw[i], this.roll[i], 'YXZ');
    this._q.setFromEuler(this._e);
    this._p.set(this.x[i], this.y[i] + bob, -this.z[i]);
    this._m.compose(this._p, this._q, this._s);
    this.mesh.setMatrixAt(i, this._m);
  }
}
