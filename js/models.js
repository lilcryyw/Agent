import * as THREE from '../vendor/three.module.min.js';
import { M, C, P, B, boxGeo, boxAt, cylGeo, merge, shared, QuadBatch, sign, pick, R, RI, gableGeo } from './util.js';

// ---------- колёсная пара
const wheelGeo = shared(new THREE.CylinderGeometry(0.525, 0.525, 0.14, 14).rotateZ(Math.PI / 2));
const axleGeo = shared(new THREE.CylinderGeometry(0.08, 0.08, 1.6, 6).rotateZ(Math.PI / 2));
function wheelset() {
  const g = new THREE.Group();
  const mw = C(0x3a3632), ma = C(0x222222);
  const a = new THREE.Mesh(wheelGeo, mw); a.position.x = -0.79; g.add(a);
  const b = new THREE.Mesh(wheelGeo, mw); b.position.x = 0.79; g.add(b);
  g.add(new THREE.Mesh(axleGeo, ma));
  g.position.y = 0.525;
  return g;
}
function bogie(z, axles, wheels, len = 4) {
  const g = new THREE.Group(); g.position.z = z;
  const f = new THREE.Mesh(boxAt(2.7, 0.55, len, 0, 0.75, 0, 2), M('rusty_metal_02', 0x555555)); g.add(f);
  const sp = axles === 3 ? 1.85 : 1.85;
  for (let i = 0; i < axles; i++) {
    const w = wheelset(); w.position.z = (i - (axles - 1) / 2) * sp; g.add(w); wheels.push(w);
  }
  return g;
}

// ---------- тепловоз
export const LOCO_LEN = 18.2;
export function makeLoco(num = '1347') {
  const g = new THREE.Group(), wheels = [];
  const body = M('green_metal_rust', 0xc8dcc4);
  g.add(new THREE.Mesh(boxAt(3.0, 0.5, 17.6, 0, 1.35, 0, 2), C(0x2b2b2b)));                // рама
  g.add(new THREE.Mesh(merge([boxAt(3.1, 0.55, 0.25, 0, 1.2, -8.95, 2), boxAt(3.1, 0.55, 0.25, 0, 1.2, 8.95, 2)]), C(0xb02a20))); // брусья
  g.add(new THREE.Mesh(boxAt(3.04, 2.95, 17.6, 0, 3.08, 0, 3), body));                      // кузов
  g.add(new THREE.Mesh(boxAt(3.08, 0.26, 17.66, 0, 2.15, 0, 3), C(0xe2b62a)));              // жёлтая полоса
  g.add(new THREE.Mesh(boxAt(3.08, 0.12, 17.66, 0, 3.0, 0, 3), C(0xe2b62a)));
  const roof = [boxAt(2.75, 0.35, 16.8, 0, 4.7, 0, 3), boxAt(0.5, 0.9, 0.5, 0.6, 5.2, 3.2, 1)];
  g.add(new THREE.Mesh(merge(roof), C(0x5c6166)));
  const fanG = merge([0, 1, 2].map((i) => { const c = cylGeo(0.62, 0.62, 0.18, 12); c.translate(0, 4.95, 1.2 + i * 1.7); return c; }));
  g.add(new THREE.Mesh(fanG, C(0x2a2d30)));
  g.add(new THREE.Mesh(boxAt(2.4, 1.0, 5, 0, 0.85, 0, 2), C(0x3d3f42)));                    // топливный бак
  g.add(new THREE.Mesh(boxAt(0.4, 0.35, 0.5, 0, 1.0, -9.2, 1), C(0x333333)));               // автосцепка СА-3
  g.add(new THREE.Mesh(boxAt(0.4, 0.35, 0.5, 0, 1.0, 9.2, 1), C(0x333333)));
  // окна и решётки
  const qb = new QuadBatch();
  qb.front(-0.72, 3.75, -8.83, 0.6, 0.42, -1, 0x1a252d);
  qb.front(0.72, 3.75, -8.83, 0.6, 0.42, -1, 0x1a252d);
  qb.front(0, 3.75, 8.83, 0.5, 0.4, 1, 0x1a252d);
  for (const f of [1, -1]) {
    qb.side(f * 1.535, 3.7, -7.9, 0.45, 0.42, f, 0x1a252d);
    qb.side(f * 1.535, 3.6, -6.9, 0.32, 0.6, f, 0x2a2a2a);  // дверь
    for (let i = 0; i < 6; i++) qb.side(f * 1.535, 3.65, -4.6 + i * 2.25, 0.85, 0.42, f, 0x2e3b33);
  }
  g.add(qb.mesh());
  // номер на борту
  for (const f of [1, -1]) {
    const s = sign('2ТЭ116-' + num, 1.9, 0.38, '#2e5a3a', '#f0e6c0', false);
    s.position.set(f * 1.54, 2.6, -7.5); s.rotation.y = f * Math.PI / 2; g.add(s);
  }
  // прожектор и буферные фонари
  const lamp = new THREE.Mesh(shared(new THREE.CylinderGeometry(0.24, 0.24, 0.2, 12).rotateX(Math.PI / 2)), B(0xfff1c2));
  lamp.position.set(0, 4.42, -8.9); g.add(lamp);
  const small = shared(new THREE.CylinderGeometry(0.11, 0.11, 0.12, 8).rotateX(Math.PI / 2));
  for (const x of [-1.15, 1.15]) {
    const l = new THREE.Mesh(small, B(0xfff6d8)); l.position.set(x, 1.75, -8.92); g.add(l);
    const r = new THREE.Mesh(small, B(0xc02020)); r.position.set(x, 1.75, 8.92); g.add(r);
  }
  g.add(bogie(-5.4, 3, wheels, 5.2));
  g.add(bogie(5.4, 3, wheels, 5.2));
  // улучшения (видимость переключается)
  const up = {};
  const plowM = M('rusty_metal_02', 0x9a9a9a);
  const plow = new THREE.Group();
  const p1 = new THREE.Mesh(boxGeo(2.1, 1.2, 0.12, 1.5), plowM); p1.position.set(-0.78, 0.75, -9.9); p1.rotation.y = -0.62; plow.add(p1);
  const p2 = new THREE.Mesh(boxGeo(2.1, 1.2, 0.12, 1.5), plowM); p2.position.set(0.78, 0.75, -9.9); p2.rotation.y = 0.62; plow.add(p2);
  g.add(plow); up.plow = plow;
  const armor = new THREE.Mesh(merge([boxAt(0.08, 1.5, 13.5, -1.6, 3.0, 1.5, 1.5), boxAt(0.08, 1.5, 13.5, 1.6, 3.0, 1.5, 1.5),
    boxAt(1.4, 0.9, 0.08, -0.72, 3.75, -8.95, 1), boxAt(1.4, 0.9, 0.08, 0.72, 3.75, -8.95, 1)]), M('rusty_metal_02', 0x8a8a8a));
  // решётки на лобовых окнах — тонкие полосы
  g.add(armor); up.armor = armor;
  const sl = new THREE.Group();
  const slBody = new THREE.Mesh(shared(new THREE.CylinderGeometry(0.32, 0.36, 0.5, 10).rotateX(Math.PI / 2)), C(0x444444));
  const slGlass = new THREE.Mesh(shared(new THREE.CircleGeometry(0.3, 12)), B(0xfffbe0));
  slGlass.position.z = -0.26; slGlass.rotation.y = Math.PI;
  sl.add(slBody); sl.add(slGlass); sl.position.set(0.9, 5.15, -7.8);
  g.add(sl); up.light = sl;
  const tur = makeTurret(); tur.position.set(0, 4.88, 6.5); g.add(tur); up.turret = tur;
  return { g, wheels, up, lampPos: new THREE.Vector3(0, 4.42, -9.1), cabPos: new THREE.Vector3(0, 3.75, -8.0) };
}
function makeTurret() {
  const t = new THREE.Group();
  const bags = new THREE.Mesh(shared(new THREE.CylinderGeometry(1.0, 1.1, 0.7, 10)), C(0x8a7a55));
  bags.position.y = 0.35; t.add(bags);
  const gun = new THREE.Group(); gun.position.y = 0.95;
  gun.add(new THREE.Mesh(boxAt(0.18, 0.2, 0.7, 0, 0, 0, 1), C(0x1e1e1e)));
  gun.add(new THREE.Mesh(shared(new THREE.CylinderGeometry(0.035, 0.035, 1.0, 6).rotateX(Math.PI / 2).translate(0, 0.02, -0.8)), C(0x111111)));
  t.add(gun); t.userData.gun = gun;
  return t;
}

// ---------- вагоны
export const BOX_LEN = 14.7, TANK_LEN = 12.2;
export function makeBoxcar(r, tint) {
  const g = new THREE.Group(), wheels = [];
  tint = tint ?? pick(r, [0xb0705a, 0xa06050, 0x8a6a58, 0xb8846a, 0x7a6a5a]);
  g.add(new THREE.Mesh(boxAt(2.9, 0.4, 13.9, 0, 1.25, 0, 2), C(0x2a2a2a)));
  g.add(new THREE.Mesh(boxAt(3.2, 3.4, 13.8, 0, 3.15, 0, 3), M('rusty_metal_02', tint)));
  g.add(new THREE.Mesh(boxAt(3.05, 0.3, 13.8, 0, 5.0, 0, 3), C(0x6b6b66)));
  const qb = new QuadBatch();
  for (const f of [1, -1]) {
    qb.side(f * 1.61, 2.9, 0, 1.0, 1.2, f, 0x4a2c22);
    for (let i = -3; i <= 3; i++) if (i) qb.side(f * 1.605, 3.15, i * 1.9, 0.04, 1.65, f, 0x5a3a2c);
  }
  g.add(qb.mesh());
  const n = String(RI(r, 2, 6)) + RI(r, 1000000, 9999999);
  for (const f of [1, -1]) {
    const s = sign(n.slice(0, 2) + '-' + n.slice(2, 5) + '-' + n.slice(5), 1.6, 0.3, '#5a3428', '#f2efe0', false);
    s.position.set(f * 1.62, 4.3, -4.8); s.rotation.y = f * Math.PI / 2; g.add(s);
  }
  g.add(new THREE.Mesh(boxAt(0.4, 0.35, 0.6, 0, 1.0, -7.2, 1), C(0x333333)));
  g.add(new THREE.Mesh(boxAt(0.4, 0.35, 0.6, 0, 1.0, 7.2, 1), C(0x333333)));
  g.add(bogie(-4.4, 2, wheels, 3)); g.add(bogie(4.4, 2, wheels, 3));
  return { g, wheels };
}
export function makeTank(r) {
  const g = new THREE.Group(), wheels = [];
  g.add(new THREE.Mesh(boxAt(2.8, 0.4, 11.6, 0, 1.25, 0, 2), C(0x262626)));
  const cyl = new THREE.Mesh(shared(new THREE.CylinderGeometry(1.5, 1.5, 11, 18).rotateX(Math.PI / 2)), P(0x232323, 30));
  cyl.position.y = 3.0; g.add(cyl);
  const capG = shared(new THREE.SphereGeometry(1.5, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2));
  const c1 = new THREE.Mesh(capG, P(0x232323, 30)); c1.scale.y = 0.25; c1.rotation.x = Math.PI / 2; c1.position.set(0, 3.0, 5.5); g.add(c1);
  const c2 = new THREE.Mesh(capG, P(0x232323, 30)); c2.scale.y = 0.25; c2.rotation.x = -Math.PI / 2; c2.position.set(0, 3.0, -5.5); g.add(c2);
  g.add(new THREE.Mesh(shared(new THREE.CylinderGeometry(0.5, 0.5, 0.5, 10).translate(0, 4.6, 0)), C(0x2a2a2a)));
  for (const f of [1, -1]) {
    const s = sign('ДИЗТОПЛИВО', 2.6, 0.45, '#232323', '#e8e8e0', false);
    s.position.set(f * 1.52, 3.0, 0); s.rotation.y = f * Math.PI / 2; g.add(s);
  }
  g.add(bogie(-3.9, 2, wheels, 3)); g.add(bogie(3.9, 2, wheels, 3));
  return { g, wheels };
}

// ---------- человекоподобные фигуры (зомби, выжившие, игрок)
const HG = {
  head: shared(new THREE.BoxGeometry(0.28, 0.3, 0.28)),
  torso: shared(new THREE.BoxGeometry(0.48, 0.62, 0.27)),
  arm: shared(new THREE.BoxGeometry(0.13, 0.62, 0.13).translate(0, -0.29, 0)),
  leg: shared(new THREE.BoxGeometry(0.17, 0.84, 0.17).translate(0, -0.42, 0)),
  eye: shared(new THREE.BoxGeometry(0.06, 0.04, 0.02)),
  helmet: shared(new THREE.SphereGeometry(0.2, 8, 5, 0, Math.PI * 2, 0, Math.PI / 2)),
  stripe: shared(new THREE.BoxGeometry(0.5, 0.08, 0.29)),
  hat: shared(new THREE.BoxGeometry(0.34, 0.12, 0.34)),
};
export function makeHuman(o) {
  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);
  const skin = C(o.skin), shirt = C(o.shirt), pants = C(o.pants);
  const torso = new THREE.Mesh(HG.torso, shirt); torso.position.y = 1.16; body.add(torso);
  const head = new THREE.Mesh(HG.head, skin); head.position.y = 1.63; body.add(head);
  const lA = new THREE.Mesh(HG.arm, o.sleeve === false ? skin : shirt); lA.position.set(-0.31, 1.44, 0); body.add(lA);
  const rA = new THREE.Mesh(HG.arm, o.sleeve === false ? skin : shirt); rA.position.set(0.31, 1.44, 0); body.add(rA);
  const lL = new THREE.Mesh(HG.leg, pants); lL.position.set(-0.12, 0.85, 0); body.add(lL);
  const rL = new THREE.Mesh(HG.leg, pants); rL.position.set(0.12, 0.85, 0); body.add(rL);
  if (o.eyes) {
    const em = B(o.eyes);
    const e1 = new THREE.Mesh(HG.eye, em); e1.position.set(-0.07, 1.66, -0.145); body.add(e1);
    const e2 = new THREE.Mesh(HG.eye, em); e2.position.set(0.07, 1.66, -0.145); body.add(e2);
  }
  if (o.helmet) { const h = new THREE.Mesh(HG.helmet, C(0x4a5a32)); h.position.y = 1.76; body.add(h); }
  if (o.hat) { const h = new THREE.Mesh(HG.hat, C(o.hat)); h.position.y = 1.82; body.add(h); }
  if (o.stripes) for (let i = 0; i < 3; i++) { const s = new THREE.Mesh(HG.stripe, C(o.stripes)); s.position.y = 0.95 + i * 0.2; body.add(s); }
  if (o.scale) body.scale.set(o.scale[0], o.scale[1], o.scale[2]);
  return { root, body, lA, rA, lL, rL, head };
}

// ---------- брошенные машины
const CAR_TYPES = [
  { n: 'Брошенные «Жигули»', L: 4.1, W: 1.62, H: 0.75, cl: 2.0, ch: 0.6, cz: 0.1, cols: [0xe8e4d8, 0x9c2a24, 0x2f5a8a, 0xd8b048, 0x3f6a3a, 0x7a2a4a] },
  { n: 'Брошенная «Нива»', L: 3.7, W: 1.68, H: 0.85, cl: 2.1, ch: 0.68, cz: 0.3, cols: [0x3f6a3a, 0xc8c8b8, 0x8a2020, 0x4a6a8a] },
  { n: 'Брошенный УАЗ', L: 4.0, W: 1.8, H: 0.95, cl: 2.6, ch: 0.85, cz: 0.4, cols: [0x5b6a3a, 0x4a5a6a, 0xd8d0b0] },
  { n: 'Брошенный автобус ПАЗ', L: 7.0, W: 2.4, H: 1.0, cl: 6.6, ch: 1.3, cz: 0.15, cols: [0xd88a2a, 0xe0c040, 0x3a7ab0] },
];
export function makeCar(r, burnt) {
  const t = pick(r, CAR_TYPES);
  const col = burnt ? 0x2e2a28 : pick(r, t.cols);
  const g = new THREE.Group(), inner = new THREE.Group(); g.add(inner);
  const mat = burnt ? M('rusty_metal_02', 0x5a4a44) : P(col, 25);
  inner.add(new THREE.Mesh(merge([boxAt(t.W, t.H, t.L, 0, 0.35 + t.H / 2, 0, 2), boxAt(t.W - 0.12, t.ch, t.cl, 0, 0.35 + t.H + t.ch / 2, t.cz, 2)]), mat));
  const qb = new QuadBatch(), gl = burnt ? 0x0a0a0a : 0x22303a, y = 0.35 + t.H + t.ch / 2;
  qb.side(t.W / 2 - 0.05, y, t.cz, t.cl / 2 - 0.12, t.ch / 2 - 0.08, 1, gl);
  qb.side(-t.W / 2 + 0.05, y, t.cz, t.cl / 2 - 0.12, t.ch / 2 - 0.08, -1, gl);
  qb.front(0, y, t.cz - t.cl / 2 - 0.01, t.W / 2 - 0.15, t.ch / 2 - 0.08, -1, gl);
  inner.add(qb.mesh());
  const wg = shared(new THREE.CylinderGeometry(0.33, 0.33, 0.22, 10).rotateZ(Math.PI / 2));
  const wm = C(0x1a1a1a);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const w = new THREE.Mesh(wg, wm); w.position.set(sx * (t.W / 2 - 0.05), 0.33, sz * (t.L / 2 - 0.75)); inner.add(w);
  }
  inner.rotation.y = Math.PI / 2 + R(r, -0.4, 0.4);
  if (r() < 0.15) { inner.rotation.z = Math.PI / 2 * (r() < 0.5 ? 1 : -1); inner.position.y = t.W / 2 - 0.3; }
  return { g, w: t.L + 0.5, d: t.W + 1, loot: 'car', label: t.n };
}

export { gableGeo };
