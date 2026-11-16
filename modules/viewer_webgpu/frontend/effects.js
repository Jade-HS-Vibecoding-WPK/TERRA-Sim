// TERRA-Sim – Effekte: Laser, Hubschrauber, Raketen, Explosionen und UFOs
//
// Die Ereignisse des Kaiju-Kampfes (Laser, Abstürze, Fehlschüsse) kommen aus
// Python (hazards.simulate_kaiju) – mit der Bahnstelle ``u``, an der das Monster
// gerade steht. Hier werden sie nur sichtbar gemacht: Läuft das Monster an
// ``u`` vorbei, wird das Ereignis ausgelöst. So passen Bild und Schadensbilanz.
//
// Koordinaten wie in scene.py: x = Osten, y = Norden; three.js: (x, Höhe, -y).

const rand = (a, b) => a + Math.random() * (b - a);

function seeded(seed) {           // kleiner Zufallsgenerator mit festem Startwert
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Effects {
  constructor(THREE, parent, groundAt, crowd) {
    this.T = THREE;
    this.groundAt = groundAt;
    this.crowd = crowd;
    this.group = new THREE.Group();
    parent.add(this.group);
    this.live = [];               // laufende Kurzeffekte (Strahlen, Explosionen, Raketen)
    this.helis = [];
    this.ufos = [];
    this.monsterKey = null;
    this.ufoKey = null;
    this.prevU = null;
    this._v = new THREE.Vector3();
    this.mat = {
      laser: new THREE.MeshBasicMaterial({ color: 0x8ffff0, transparent: true, depthWrite: false,
                                           blending: THREE.AdditiveBlending, toneMapped: false }),
      fire: new THREE.MeshBasicMaterial({ color: 0xffa13d, transparent: true, depthWrite: false,
                                          blending: THREE.AdditiveBlending, toneMapped: false }),
      smoke: new THREE.MeshStandardMaterial({ color: 0x3d3a38, transparent: true, depthWrite: false, roughness: 1 }),
      missile: new THREE.MeshBasicMaterial({ color: 0xfff2c0, toneMapped: false }),
      beam: new THREE.MeshBasicMaterial({ color: 0x7dff9a, transparent: true, opacity: 0.22, depthWrite: false,
                                          blending: THREE.AdditiveBlending, side: THREE.DoubleSide, toneMapped: false }),
    };
    this.geo = {
      unitCylinder: new THREE.CylinderGeometry(1, 1, 1, 8, 1, true),
      ball: new THREE.IcosahedronGeometry(1, 2),
      missile: new THREE.CylinderGeometry(0.25, 0.25, 2.2, 6),
    };
  }

  get active() { return this.helis.length > 0 || this.ufos.length > 0 || this.live.length > 0; }

  world(x, y, h = 0) { return new this.T.Vector3(x, this.groundAt(x, y) + h, -y); }

  // ---------------------------------------------------------------- Aufbau
  configure(monster, ufos) {
    const mKey = monster ? JSON.stringify([monster.helis, monster.height, monster.lasers.length]) : null;
    if (mKey !== this.monsterKey) {
      this.monsterKey = mKey;
      for (const h of this.helis) this.group.remove(h.obj);
      this.helis = [];
      for (let k = 0; k < (monster ? monster.helis : 0); k++) {
        const obj = makeHeli(this.T);
        this.group.add(obj);
        this.helis.push({ obj, k, alive: true, falling: null, nextShot: rand(1, 4) });
      }
    }
    this.monster = monster || null;
    const uKey = ufos ? JSON.stringify(ufos) : null;
    if (uKey !== this.ufoKey) {
      this.ufoKey = uKey;
      for (const u of this.ufos) this.group.remove(u.obj);
      this.ufos = [];
      if (ufos) {
        const rnd = seeded(ufos.seed || 7);
        for (let k = 0; k < ufos.count; k++) {
          const obj = makeUfo(this.T, ufos.size);
          this.group.add(obj);
          const beam = new this.T.Mesh(new this.T.ConeGeometry(1, 1, 32, 1, true), this.mat.beam.clone());
          beam.visible = false;
          this.group.add(beam);
          this.ufos.push({ obj, beam, s: rnd() * 100, phase: [rnd(), rnd(), rnd(), rnd()].map((p) => p * 6.28),
                           cycle: rnd() * 9, size: ufos.size, height: ufos.height,
                           reach: ufos.reach, speed: ufos.speed });
        }
      }
    }
  }

  // ---------------------------------------------------------------- Kurzeffekte
  explosion(pos, size) {
    const fire = new this.T.Mesh(this.geo.ball, this.mat.fire.clone());
    const smoke = new this.T.Mesh(this.geo.ball, this.mat.smoke.clone());
    fire.position.copy(pos); smoke.position.copy(pos);
    this.group.add(fire, smoke);
    this.live.push({ age: 0, life: 2.8, update: (e, dt) => {
      const a = e.age;
      fire.scale.setScalar(size * Math.min(1, 0.25 + a * 2));
      fire.material.opacity = Math.max(0, 1 - a / 0.7);
      smoke.scale.setScalar(size * (0.5 + a * 0.5));
      smoke.position.y += dt * size * 0.3;
      smoke.material.opacity = Math.max(0, 0.55 * (1 - a / e.life));
    }, dispose: () => { this.group.remove(fire, smoke); fire.material.dispose(); smoke.material.dispose(); } });
    this.crowd.blast(pos.x, -pos.z, size * 1.4);
  }

  beam(from, to, radius, life = 0.9) {
    const mesh = new this.T.Mesh(this.geo.unitCylinder, this.mat.laser.clone());
    const dir = to.clone().sub(from);
    mesh.position.copy(from).addScaledVector(dir, 0.5);
    mesh.quaternion.setFromUnitVectors(new this.T.Vector3(0, 1, 0), dir.clone().normalize());
    mesh.scale.set(radius, dir.length(), radius);
    this.group.add(mesh);
    this.live.push({ age: 0, life, update: (e) => {
      const f = Math.sin(Math.PI * Math.min(1, e.age / e.life));
      mesh.material.opacity = 0.35 + 0.65 * f;
      mesh.scale.x = mesh.scale.z = radius * (0.6 + 0.6 * f);
    }, dispose: () => { this.group.remove(mesh); mesh.material.dispose(); } });
  }

  missile(from, to, flight, onHit) {
    const mesh = new this.T.Mesh(this.geo.missile, this.mat.missile);
    this.group.add(mesh);
    const dir = to.clone().sub(from).normalize();
    mesh.quaternion.setFromUnitVectors(new this.T.Vector3(0, 1, 0), dir);
    this.live.push({ age: 0, life: flight, update: (e) => {
      mesh.position.lerpVectors(from, to, Math.min(1, e.age / e.life));
    }, dispose: () => { this.group.remove(mesh); onHit(); } });
  }

  // ---------------------------------------------------------------- Ablauf
  update(dt, t, ctx) {
    const m = this.monster, pos = ctx.monster;
    if (m && pos) {
      const H = m.height;
      // Ereignisse auslösen, wenn das Monster an ihrer Bahnstelle vorbeiläuft
      if (this.prevU !== null) {
        if (pos.u < this.prevU) {                       // Schleife neu: Hubschrauber kommen wieder
          for (const h of this.helis) { h.alive = true; h.falling = null; h.obj.visible = true; }
        } else {
          const crossed = (e) => this.prevU < e.u && e.u <= pos.u;
          for (const e of m.lasers) if (crossed(e)) this.fireLaser(pos, e, H);
          for (const e of m.crashes) if (crossed(e)) this.crashHeli(e, H);
          for (const e of m.misses) if (crossed(e)) this.missFire(e, H);
        }
      }
      this.prevU = pos.u;
      this.updateHelis(dt, t, pos, H);
    }
    this.updateUfos(dt, t, ctx);
    for (const e of this.live) { e.age += dt; e.update(e, dt); }
    this.live = this.live.filter((e) => { if (e.age < e.life) return true; e.dispose(); return false; });
  }

  fireLaser(pos, e, H) {
    const target = this.world(e.target[0], e.target[1]);
    const eyes = pos.obj.userData.eyes || [];
    pos.obj.updateMatrixWorld(true);
    for (const eye of eyes) this.beam(eye.getWorldPosition(new this.T.Vector3()), target, H * 0.012);
    this.live.push({ age: 0, life: 0.25, update: () => {}, dispose: () => this.explosion(target, H * 0.14) });
  }

  crashHeli(e, H) {
    const heli = this.helis.find((h) => h.alive && !h.falling);
    if (!heli) return;
    heli.falling = { from: heli.obj.position.clone(), to: this.world(e.point[0], e.point[1]), age: 0 };
    this.explosion(heli.obj.position.clone(), H * 0.05);          // vom Laser getroffen
  }

  missFire(e, H) {
    const heli = this.helis.find((h) => h.alive && !h.falling);
    if (!heli) return;
    const to = this.world(e.point[0], e.point[1]);
    this.missile(heli.obj.position.clone(), to, 0.9, () => this.explosion(to, 9));
  }

  updateHelis(dt, t, pos, H) {
    const n = this.helis.length;
    const center = new this.T.Vector3(pos.x, this.groundAt(pos.x, pos.y), -pos.y);
    for (const h of this.helis) {
      const rotor = h.obj.userData.rotor, tail = h.obj.userData.tailRotor;
      rotor.rotation.y += dt * 45;
      tail.rotation.x += dt * 60;
      if (!h.alive) continue;
      if (h.falling) {                                  // Absturz: trudelnd mit Rauchfahne
        const f = h.falling;
        f.age += dt;
        const k = Math.min(1, f.age / 2.6);
        h.obj.position.lerpVectors(f.from, f.to, k * k);
        h.obj.rotation.y += dt * 9;
        h.obj.rotation.z = 0.5;
        if (Math.random() < dt * 12) this.smokePuff(h.obj.position.clone(), 4);
        if (k >= 1) {
          this.explosion(f.to.clone().setY(f.to.y + 3), 26);
          h.alive = false; h.falling = null; h.obj.visible = false;
        }
        continue;
      }
      const a = t * 0.45 + (h.k * Math.PI * 2) / n;
      const r = H * (1.35 + 0.3 * (h.k % 2));
      const p = new this.T.Vector3(center.x + Math.cos(a) * r, center.y + H * (0.8 + 0.12 * Math.sin(t + h.k)),
                                   center.z + Math.sin(a) * r);
      h.obj.position.copy(p);
      h.obj.rotation.set(0.15, Math.atan2(-Math.sin(a), Math.cos(a)), 0);   // Nase in Flugrichtung, leicht geneigt
      h.obj.lookAt(center.x, p.y - H * 0.25, center.z);                       // … aber zum Monster schauend
      h.nextShot -= dt;
      if (h.nextShot <= 0) {                            // Rakete auf das Monster
        h.nextShot = rand(2.5, 5);
        const chest = center.clone().setY(center.y + H * 0.55 + rand(-0.1, 0.15) * H);
        this.missile(p.clone(), chest, 0.8, () => this.flash(chest, H * 0.06));
      }
    }
  }

  flash(pos, size) {                                     // kleiner Treffer am Monster (ohne Rauch)
    const fire = new this.T.Mesh(this.geo.ball, this.mat.fire.clone());
    fire.position.copy(pos);
    this.group.add(fire);
    this.live.push({ age: 0, life: 0.5, update: (e) => {
      fire.scale.setScalar(size * (0.3 + e.age * 2.5));
      fire.material.opacity = 1 - e.age / e.life;
    }, dispose: () => { this.group.remove(fire); fire.material.dispose(); } });
  }

  smokePuff(pos, size) {
    const s = new this.T.Mesh(this.geo.ball, this.mat.smoke.clone());
    s.position.copy(pos);
    this.group.add(s);
    this.live.push({ age: 0, life: 2, update: (e, dt) => {
      s.scale.setScalar(size * (0.4 + e.age));
      s.position.y += dt * 2;
      s.material.opacity = 0.5 * (1 - e.age / e.life);
    }, dispose: () => { this.group.remove(s); s.material.dispose(); } });
  }

  // UFOs: kreuzen über dem Gebiet, bleiben stehen und holen Menschen hoch
  updateUfos(dt, t, ctx) {
    ctx.ufos = [];
    for (const u of this.ufos) {
      u.cycle = (u.cycle + dt) % 9;
      const beaming = u.cycle > 5;                     // 5 s fliegen, 4 s Strahl
      u.s += dt * (beaming ? 0.02 : 1) * u.speed;
      const A = u.reach, p = u.phase;
      const x = A * (Math.sin(u.s * 0.11 + p[0]) * 0.8 + Math.sin(u.s * 0.27 + p[1]) * 0.2);
      const y = A * (Math.sin(u.s * 0.13 + p[2]) * 0.8 + Math.sin(u.s * 0.31 + p[3]) * 0.2);
      const ground = this.groundAt(x, y);
      const top = ground + u.height + Math.sin(t * 1.3 + p[0]) * 1.5;
      u.obj.position.set(x, top, -y);
      u.obj.rotation.y += dt * 0.8;
      u.obj.userData.lights.forEach((l, k) => {
        l.material.emissiveIntensity = 0.4 + 1.6 * (Math.sin(t * 6 + k * 1.3) > 0.3 ? 1 : 0);
      });
      const r = u.size * 0.45;
      u.beam.visible = beaming;
      if (beaming) {
        const fade = Math.min(1, (u.cycle - 5) * 3, (9 - u.cycle) * 3);
        u.beam.position.set(x, ground + (top - ground) / 2, -y);
        u.beam.scale.set(r, top - ground, r);
        u.beam.material.opacity = 0.25 * fade;
      }
      ctx.ufos.push({ x, y, top: top - u.size * 0.1, r, beaming });
    }
  }
}

// ------------------------------------------------------------------ Modelle

function makeHeli(T) {
  const g = new T.Group();
  const paint = new T.MeshStandardMaterial({ color: 0x55613f, roughness: 0.6, metalness: 0.2 });
  const dark = new T.MeshStandardMaterial({ color: 0x24282b, roughness: 0.5 });
  const glass = new T.MeshStandardMaterial({ color: 0x1b2a33, roughness: 0.15, metalness: 0.5 });
  const part = (geo, mat, x, y, z, rx = 0, ry = 0, rz = 0) => {
    const m = new T.Mesh(geo, mat);
    m.position.set(x, y, z); m.rotation.set(rx, ry, rz); m.castShadow = true;
    g.add(m);
    return m;
  };
  part(new T.CapsuleGeometry(1.1, 2.6, 6, 14), paint, 0, 0, 0, Math.PI / 2);
  part(new T.SphereGeometry(1.0, 16, 10), glass, 0, 0.15, 1.6).scale.set(0.9, 0.8, 1.0);
  part(new T.CylinderGeometry(0.25, 0.4, 5, 8), paint, 0, 0.3, -3.8, Math.PI / 2);
  part(new T.BoxGeometry(0.12, 1.5, 0.9), paint, 0, 0.9, -6.1);
  for (const s of [-1, 1]) part(new T.CylinderGeometry(0.08, 0.08, 3.6, 6), dark, s * 0.8, -1.35, 0.2, Math.PI / 2);
  const rotor = new T.Group();
  rotor.position.set(0, 1.45, 0);
  rotor.add(new T.Mesh(new T.BoxGeometry(11, 0.06, 0.35), dark), new T.Mesh(new T.BoxGeometry(0.35, 0.06, 11), dark));
  g.add(rotor);
  const tail = new T.Group();
  tail.position.set(0.3, 0.9, -6.2);
  tail.add(new T.Mesh(new T.BoxGeometry(0.06, 1.9, 0.22), dark));
  g.add(tail);
  g.userData.rotor = rotor;
  g.userData.tailRotor = tail;
  return g;
}

function makeUfo(T, size) {
  const g = new T.Group();
  const hull = new T.Mesh(new T.SphereGeometry(1, 48, 16),
    new T.MeshStandardMaterial({ color: 0xc9ced6, metalness: 0.55, roughness: 0.25 }));
  hull.scale.set(size / 2, size * 0.11, size / 2);
  hull.castShadow = true;
  const dome = new T.Mesh(new T.SphereGeometry(size * 0.18, 32, 12, 0, Math.PI * 2, 0, Math.PI / 2),
    new T.MeshStandardMaterial({ color: 0x9be8ff, emissive: 0x2fb7d9, emissiveIntensity: 0.6,
                                 transparent: true, opacity: 0.85, roughness: 0.1 }));
  dome.position.y = size * 0.07;
  const ring = new T.Mesh(new T.TorusGeometry(size * 0.3, size * 0.025, 8, 48),
    new T.MeshStandardMaterial({ color: 0x7dff9a, emissive: 0x4dff7a, emissiveIntensity: 1.2 }));
  ring.rotation.x = Math.PI / 2;
  ring.position.y = -size * 0.08;
  g.add(hull, dome, ring);
  const lights = [];
  const colors = [0xff4d4d, 0xffd84d, 0x4dd2ff];
  for (let k = 0; k < 12; k++) {
    const a = (k / 12) * Math.PI * 2;
    const l = new T.Mesh(new T.SphereGeometry(size * 0.025, 8, 6),
      new T.MeshStandardMaterial({ color: colors[k % 3], emissive: colors[k % 3], emissiveIntensity: 1 }));
    l.position.set(Math.cos(a) * size * 0.46, 0, Math.sin(a) * size * 0.46);
    g.add(l);
    lights.push(l);
  }
  g.userData.lights = lights;
  return g;
}
