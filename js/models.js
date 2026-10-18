import * as THREE from '../vendor/three.module.min.js';
import { packGeo, roofProfile, PACK_MAT } from './packs.js';
import { M, C, P, B, boxGeo, boxAt, cylGeo, merge, shared, QuadBatch, sign, pick, R, RI, gableGeo, mulberry32 } from './util.js';

// ---------- поезд из готовых моделей (Quaternius Train Pack, CC0), перекрашен под РЖД
export const TS = 1.62;            // масштаб моделей до габарита 1520
const HP = Math.PI / 2;
function carFrom(model, o) {
  const geo = packGeo(model, Object.assign({ rotY: -HP, scale: TS }, o));
  const g = new THREE.Group();
  const m = new THREE.Mesh(geo, PACK_MAT); m.castShadow = true; m.receiveShadow = true; g.add(m);
  const bb = geo.boundingBox, len = bb.max.z - bb.min.z;
  return { g, geo, len, H: bb.max.y, W: bb.max.x, roof: roofProfile(geo) };
}
const BOX_COL = [0x8a4632, 0x7a3e2c, 0x6e4a36, 0x93533a, 0x5e5048];
// брошенные вагоны на запасных путях — разные модели
const ABANDON = [
  ['Locomotive_Wagon', 'Брошенный крытый вагон', 4],
  ['Locomotive_PassengerWagon', 'Брошенный пассажирский вагон', 2],
  ['CargoTrain_Wagon', 'Брошенный пассажирский вагон', 2],
  ['CargoTrain_CoalContainer', 'Брошенный полувагон с углём', 2],
  ['CargoTrain_Container', 'Брошенная платформа с контейнером', 2],
  ['CargoTrain_WagonOpenContainer', 'Брошенный пустой полувагон', 1],
];
export function makeWreck(r) {
  let t = 0; for (const a of ABANDON) t += a[2];
  let x = r() * t, k = ABANDON[0]; for (const a of ABANDON) { x -= a[2]; if (x <= 0) { k = a; break; } }
  const o = {};
  if (k[0] === 'Locomotive_Wagon') o.colors = { LightWood: pick(r, BOX_COL), DarkWood: 0x3a2a22, Grey: 0x6f7377 };
  if (k[0] === 'CargoTrain_Wagon') o.colors = { Main: 0x3e7d56, DarkMain: 0xc8c8b8, Grey: 0x8a9096 };
  if (k[0] === 'Locomotive_PassengerWagon') o.colors = { Red: 0x6a6f72, Green: 0x3e6a4a, DarkGreen: 0x2c4a36 };
  if (k[0] === 'CargoTrain_Container') o.colors = { Container: pick(r, [0x3a6a8a, 0x9a3a2a, 0x4a7a4a, 0xa08040]) };
  const c = carFrom(k[0], o);
  return { g: c.g, len: c.len, label: k[1] };
}
// цистерна (улучшение «бак»): гладкая процедурная
export const TANK_LEN = 12.2;
export function makeTank(r) {
  const g = new THREE.Group();
  const mt = new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.55, metalness: 0.3 });
  const add = (geo, m, y = 0) => { const x = new THREE.Mesh(geo, m); x.position.y = y; x.castShadow = x.receiveShadow = true; g.add(x); return x; };
  add(boxAt(2.8, 0.4, 11.6, 0, 1.25, 0, 2), PACK_MAT_DARK);
  add(shared(new THREE.CapsuleGeometry(1.5, 9.2, 8, 28).rotateX(HP)), mt, 3.0);
  add(shared(new THREE.CylinderGeometry(0.5, 0.5, 0.5, 18).translate(0, 4.6, 0)), mt);
  for (const z of [-4.2, 4.2]) {
    const b = packGeo('CargoTrain_WagonEmpty', { rotY: -HP, scale: [TS, TS, 0.3] });
    const bm = new THREE.Mesh(b, PACK_MAT); bm.position.z = z; g.add(bm);
  }
  for (const f of [1, -1]) {
    const s = sign('ДИЗТОПЛИВО', 2.6, 0.45, '#232323', '#e8e8e0', false);
    s.position.set(f * 1.53, 3.0, 0); s.rotation.y = f * HP; g.add(s);
  }
  return { g, wheels: [], len: TANK_LEN, roofY: () => 4.5, spots: {} };
}
const PACK_MAT_DARK = new THREE.MeshStandardMaterial({ color: 0x262626, roughness: 0.8 });




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
