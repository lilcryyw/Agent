// Подвижной состав: пассажирский тепловоз (по мотивам ТЭП70) и плацкартный вагон с салоном.
// Ось вагона — Z, перёд в −Z, y = 0 — головка рельса, правый борт — +X.
import * as THREE from '../vendor/three.module.min.js';
import { M, P, B, boxAt, cylGeo, merge, shared } from './util.js';

const HP = Math.PI / 2;
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0, ...o });
export const RM = {
  inner: std(0xe4dccb, { roughness: 0.85 , envMapIntensity: 0.45 }),
  part: std(0xd6c7a4, { roughness: 0.7 , envMapIntensity: 0.45 }),
  seat: std(0x3a4c70, { roughness: 0.55 , envMapIntensity: 0.45 }),
  wood: std(0xa9845a, { roughness: 0.55 , envMapIntensity: 0.45 }),
  floor: std(0x5a463a, { roughness: 0.9 }),
  dark: std(0x2a2c2e, { roughness: 0.75, metalness: 0.25 }),
  metal: std(0x9a9ea2, { roughness: 0.35, metalness: 0.7 }),
  roof: std(0x868a8e, { roughness: 0.55, metalness: 0.2 }),
  end: std(0xb9bdc1, { roughness: 0.6 }),
  rubber: std(0x161616, { roughness: 0.95 }),
  glass: new THREE.MeshStandardMaterial({ color: 0x1e2a32, roughness: 0.05, metalness: 0.3, transparent: true, opacity: 0.35, depthWrite: false }),
  lamp: new THREE.MeshBasicMaterial({ color: 0xfff1d0 }),
  body: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.45, metalness: 0.1 }),
  wheel: std(0x4a4440, { roughness: 0.5, metalness: 0.6 }),
  carpet: std(0x7a2a26, { roughness: 0.95 }),
};

// ---------- колёсная пара и тележка
const wheelGeo = shared(cylGeo(0.475, 0.475, 0.13, 20).rotateZ(HP));
const axleGeo = shared(cylGeo(0.075, 0.075, 1.62, 8).rotateZ(HP));
function wheelset() {
  const g = new THREE.Group();
  for (const x of [-0.76, 0.76]) { const w = new THREE.Mesh(wheelGeo, RM.wheel); w.position.x = x; g.add(w); }
  g.add(new THREE.Mesh(axleGeo, RM.dark));
  g.position.y = 0.475;
  return g;
}
function bogie(z, axles, wheels, base = 2.4) {
  const g = new THREE.Group(); g.position.z = z;
  const len = base * (axles - 1) + 1.4, parts = [];
  for (const x of [-1.0, 1.0]) {
    parts.push(boxAt(0.16, 0.34, len, x, 0.62, 0, 2));
    for (let i = 0; i < axles; i++) parts.push(boxAt(0.26, 0.3, 0.42, x, 0.5, (i - (axles - 1) / 2) * base, 1));
  }
  parts.push(boxAt(2.2, 0.22, 0.5, 0, 0.82, 0, 2));
  const fr = new THREE.Mesh(merge(parts), RM.dark); fr.castShadow = true; g.add(fr);
  const spr = [];
  for (const x of [-1.0, 1.0]) for (const dz of [-0.35, 0.35]) spr.push(cylGeo(0.09, 0.09, 0.22, 10).translate(x, 0.92, dz));
  g.add(new THREE.Mesh(merge(spr), RM.metal));
  for (let i = 0; i < axles; i++) { const w = wheelset(); w.position.z = (i - (axles - 1) / 2) * base; g.add(w); wheels.push(w); }
  return g;
}

// ---------- окраска борта вагона: светло-серый, красная полоса снизу, надписи
function sideTexture(L, flip, num) {
  const W = 2048, H = 256, c = document.createElement('canvas'); c.width = W; c.height = H;
  const x = c.getContext('2d');
  if (flip) { x.translate(W, 0); x.scale(-1, 1); }
  const Y = (y) => H - (y - 0.95) / 2.6 * H, Z = (z) => (z + L / 2) / L * W;   // z: −L/2 — перёд
  const g = x.createLinearGradient(0, 0, 0, H); g.addColorStop(0, '#d9dcdf'); g.addColorStop(1, '#c4c8cc');
  x.fillStyle = g; x.fillRect(0, 0, W, H);
  x.fillStyle = '#c8102e'; x.fillRect(0, Y(1.78), W, Y(0.95) - Y(1.78));
  x.fillStyle = '#ffffff'; x.fillRect(0, Y(1.86), W, Y(1.78) - Y(1.86));
  x.fillStyle = '#6d7378'; x.fillRect(0, Y(3.42), W, Y(3.3) - Y(3.42));
  // швы панелей
  for (let z = -L / 2 + 1; z < L / 2; z += 2) { x.fillStyle = 'rgba(0,0,0,0.06)'; x.fillRect(Z(z), 0, 2, H); }
  // надписи (на «нечитаемой» стороне — зеркально отразим ещё раз)
  const text = (t, z, y, size, col) => {
    x.save(); x.font = `bold ${size}px Arial, sans-serif`; x.fillStyle = col; x.textAlign = 'center';
    if (flip) { x.translate(Z(z), Y(y)); x.scale(-1, 1); x.fillText(t, 0, 0); } else x.fillText(t, Z(z), Y(y));
    x.restore();
  };
  text('РЖД', 0, 1.3, 64, '#ffffff');
  text(String(num).padStart(2, '0'), -L / 2 + 2.3, 2.45, 46, '#c8102e');
  text(String(num).padStart(2, '0'), L / 2 - 2.3, 2.45, 46, '#c8102e');
  text('ФПК', L / 2 - 4.0, 1.3, 40, '#ffffff');
  // лёгкая грязь снизу
  const d = x.createLinearGradient(0, Y(1.5), 0, H); d.addColorStop(0, 'rgba(60,45,30,0)'); d.addColorStop(1, 'rgba(60,45,30,0.35)');
  x.fillStyle = d; x.fillRect(0, Y(1.5), W, H - Y(1.5));
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  t.repeat.set(1 / L, 1 / 2.6); t.offset.set(0.5, -0.95 / 2.6);
  return t;
}
function rrect(path, x0, y0, x1, y1, r) {
  path.moveTo(x0 + r, y0); path.lineTo(x1 - r, y0); path.quadraticCurveTo(x1, y0, x1, y0 + r);
  path.lineTo(x1, y1 - r); path.quadraticCurveTo(x1, y1, x1 - r, y1); path.lineTo(x0 + r, y1);
  path.quadraticCurveTo(x0, y1, x0, y1 - r); path.lineTo(x0, y0 + r); path.quadraticCurveTo(x0, y0, x0 + r, y0);
}
// стенка с проёмами: shape в осях (z, y), толщина вдоль X
function wallGeo(L, y0, y1, holes, depth) {
  const s = new THREE.Shape(); s.moveTo(-L / 2, y0); s.lineTo(L / 2, y0); s.lineTo(L / 2, y1); s.lineTo(-L / 2, y1); s.lineTo(-L / 2, y0);
  for (const h of holes) { const p = new THREE.Path(); rrect(p, h[0], h[1], h[2], h[3], h[4] ?? 0.12); s.holes.push(p); }
  const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: false, curveSegments: 4 });
  g.rotateY(-HP);   // форма X -> вагон Z, выдавливание -> −X; грань «наружу» (+X) оказывается в x = 0
  return g;
}
// коробка со скруглёнными рёбрами (мягкие полки, столики, перегородки)
const rbCache = new Map();
function rbox(w, h, d, x, y, z, r = 0.04) {
  r = Math.min(r, w / 2 - 0.002, h / 2 - 0.002, d / 2 - 0.002);
  const key = [w, h, d, r].map((v) => v.toFixed(3)).join('|');
  let base = rbCache.get(key);
  if (!base) {
    const s = new THREE.Shape(), a = w / 2 - r, b = h / 2 - r, c = Math.min(a, b) * 0.5;
    rrect(s, -a, -b, a, b, Math.max(0.001, c));
    base = new THREE.ExtrudeGeometry(s, { depth: Math.max(0.001, d - 2 * r), bevelEnabled: true, bevelThickness: r, bevelSize: r, bevelSegments: 2, curveSegments: 3 });
    base.translate(0, 0, -(d - 2 * r) / 2);
    rbCache.set(key, base);
  }
  return base.clone().translate(x, y, z);
}
// отделка салона: панели пластика с тёмной полосой внизу
function innerTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 256; const x = c.getContext('2d');
  x.fillStyle = '#e9e1cf'; x.fillRect(0, 0, 256, 256);
  x.fillStyle = '#8b7d68'; x.fillRect(0, 256 * (1 - 0.75 / 2.6), 256, 256);   // низ до подоконника
  x.fillStyle = '#6f6352'; x.fillRect(0, 256 * (1 - 0.78 / 2.6), 256, 4);
  for (let i = 0; i < 2; i++) { x.fillStyle = 'rgba(0,0,0,0.12)'; x.fillRect(i * 128, 0, 2, 256); }
  for (let i = 0; i < 1500; i++) { x.fillStyle = `rgba(0,0,0,${Math.random() * 0.03})`; x.fillRect(Math.random() * 256, Math.random() * 256, 2, 2); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / 2, 1 / 2.6); t.offset.set(0, -1.22 / 2.6); return t;
}
// материалы бортов кэшируются по номеру вагона (иначе на станциях копились бы текстуры)
const MATS = new Map();
let INNER = null;
function carMats(L, num) {
  let m = MATS.get(num);
  if (!m) {
    if (!INNER) INNER = new THREE.MeshStandardMaterial({ map: innerTexture(), roughness: 0.8, envMapIntensity: 0.5 });
    m = { R: new THREE.MeshStandardMaterial({ map: sideTexture(L, true, num), roughness: 0.45, metalness: 0.1 }),
      L: new THREE.MeshStandardMaterial({ map: sideTexture(L, false, num), roughness: 0.45, metalness: 0.1 }), inner: INNER };
    MATS.set(num, m);
  }
  return m;
}
// сечение кузова (для торцевых стен)
function bodyOutline(path, hw, y0, eave, peak) {
  path.moveTo(-hw, y0); path.lineTo(hw, y0); path.lineTo(hw, eave);
  path.quadraticCurveTo(0, 2 * peak - eave, -hw, eave); path.lineTo(-hw, y0);
}
function crescent(hw, eave, peak, th) {
  const s = new THREE.Shape();
  s.moveTo(-hw, eave); s.quadraticCurveTo(0, 2 * peak - eave, hw, eave);
  s.lineTo(hw - th, eave - 0.02); s.quadraticCurveTo(0, 2 * (peak - th) - (eave - 0.02), -(hw - th), eave - 0.02); s.lineTo(-hw, eave);
  return s;
}

// ---------- плацкартный вагон
export const CAR = { L: 24, HW: 1.56, FLOOR: 1.3, EAVE: 3.55, PEAK: 4.3, TAMB: 1.6 };
export function makePassCar(num = 1, opts = {}) {
  const { L, HW, FLOOR, EAVE, PEAK, TAMB } = CAR;
  const g = new THREE.Group(), wheels = [];
  const add = (geo, mat, cast = true) => { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = true; g.add(m); return m; };
  const NS = 8, SEC = 2.0, a0 = -L / 2 + TAMB + 2.0;        // секции плацкарта
  const winY0 = FLOOR + 0.9, winY1 = FLOOR + 1.78;
  const holesL = [], holesR = [], glass = [];
  for (let i = 0; i < NS; i++) {
    const zc = a0 + i * SEC + SEC / 2;
    holesL.push([zc - 0.52, winY0, zc + 0.52, winY1]); holesR.push([zc - 0.52, winY0, zc + 0.52, winY1]);
  }
  holesL.push([-L / 2 + TAMB + 0.5, winY0, -L / 2 + TAMB + 1.5, winY1]);            // служебное купе
  holesR.push([-L / 2 + TAMB + 0.5, winY0, -L / 2 + TAMB + 1.5, winY1]);
  holesL.push([L / 2 - TAMB - 1.0, winY0 + 0.3, L / 2 - TAMB - 0.4, winY1]);       // туалет — маленькое окно
  for (const sg of [-1, 1]) for (const hs of [holesL, holesR]) hs.push([sg * (L / 2 - 0.8) - 0.43, FLOOR, sg * (L / 2 - 0.8) + 0.43, FLOOR + 1.98, 0.08]);   // двери тамбура
  // наружные стенки (текстура), внутренние (пластик)
  const mats = carMats(L, num);
  const outR = wallGeo(L, 0.95, EAVE, holesR, 0.04); outR.translate(HW, 0, 0);
  const outL = wallGeo(L, 0.95, EAVE, holesL, 0.04); outL.translate(-HW + 0.04, 0, 0);
  add(outR, mats.R); add(outL, mats.L);
  const inR = wallGeo(L, FLOOR - 0.08, EAVE - 0.05, holesR, 0.03); inR.translate(HW - 0.1, 0, 0);
  const inL = wallGeo(L, FLOOR - 0.08, EAVE - 0.05, holesL, 0.03); inL.translate(-HW + 0.13, 0, 0);
  add(merge([inR, inL]), mats.inner, false);
  // стёкла
  for (const [hs, x] of [[holesR, HW - 0.05], [holesL, -HW + 0.05]]) for (const h of hs) if (h[1] > FLOOR + 0.01) glass.push(boxAt(0.01, h[3] - h[1], h[2] - h[0], x, (h[1] + h[3]) / 2, (h[0] + h[2]) / 2, 1));
  add(merge(glass), RM.glass, false).renderOrder = 2;
  // крыша и потолок
  const roof = new THREE.ExtrudeGeometry(crescent(HW + 0.03, EAVE, PEAK, 0.05), { depth: L, bevelEnabled: false, curveSegments: 14 }); roof.translate(0, 0, -L / 2);
  add(roof, RM.roof);
  const ceil = new THREE.ExtrudeGeometry(crescent(HW - 0.1, EAVE - 0.06, PEAK - 0.08, 0.03), { depth: L - 0.1, bevelEnabled: false, curveSegments: 12 }); ceil.translate(0, 0, -L / 2 + 0.05);
  add(ceil, RM.inner, false);
  // торцы с дверью перехода
  const endS = new THREE.Shape(); bodyOutline(endS, HW, 0.95, EAVE, PEAK);
  const dh = new THREE.Path(); rrect(dh, -0.42, FLOOR, 0.42, FLOOR + 1.95, 0.08); endS.holes.push(dh);
  const ends = [];
  for (const sg of [-1, 1]) { const e = new THREE.ExtrudeGeometry(endS, { depth: 0.06, bevelEnabled: false, curveSegments: 12 }); e.translate(0, 0, sg * L / 2 - 0.03); ends.push(e); }
  add(merge(ends), RM.end);
  // переходные гармошки и сцепки
  const rub = [];
  for (const sg of [-1, 1]) { rub.push(boxAt(1.3, 2.3, 0.32, 0, FLOOR + 1.1, sg * (L / 2 + 0.14), 1)); }
  add(merge(rub), RM.rubber);
  // пол, рама, оборудование
  add(boxAt(2 * HW - 0.08, 0.1, L - 0.06, 0, FLOOR - 0.05, 0, 1.5), M('rough_wood', 0x6b5242, { roughness: 0.85 }), false);
  add(boxAt(0.62, 0.012, L - 3.4, 0.7, FLOOR + 0.006, 0, 2), RM.carpet, false);
  const under = [boxAt(2.7, 0.3, L - 0.3, 0, 1.05, 0, 3)];
  for (const z of [-4.5, -1.2, 2.5, 5.5]) under.push(boxAt(1.6, 0.42, 1.6 + (z > 0 ? 0.6 : 0), 0, 0.72, z, 2));
  for (const sg of [-1, 1]) under.push(boxAt(0.36, 0.3, 0.5, 0, 1.0, sg * (L / 2 + 0.2), 1));
  add(merge(under), RM.dark);
  g.add(bogie(-(L / 2 - 3.0), 2, wheels)); g.add(bogie(L / 2 - 3.0, 2, wheels));
  // подножки у дверей
  const steps = [];
  for (const sg of [-1, 1]) for (const sx of [-1, 1]) for (let k = 0; k < 3; k++) steps.push(boxAt(0.32, 0.04, 0.8, sx * (HW - 0.1 - k * 0.0), 0.42 + k * 0.3, sg * (L / 2 - 0.8), 1));
  add(merge(steps), RM.metal);
  // ---- салон
  const part = [], seat = [], wood = [], inner = [], lamps = [], base = [];
  const rects = [];   // препятствия для ходьбы внутри: [x0, x1, z0, z1]
  const R = (x0, x1, z0, z1) => rects.push([x0, x1, z0, z1]);
  const xi = -HW + 0.12, AIS0 = 0.42, SIDE0 = 1.0, xo = HW - 0.1;
  for (let i = 0; i <= NS; i++) {
    const a = a0 + i * SEC;
    part.push(rbox(AIS0 - xi, 2.1, 0.05, (xi + AIS0) / 2, FLOOR + 1.05, a, 0.02)); R(xi, AIS0, a - 0.04, a + 0.04);
    if (i === NS) break;
    for (const [z0, z1, bz] of [[a + 0.05, a + 0.6, a + 0.08], [a + 1.4, a + 1.95, a + 1.92]]) {
      base.push(boxAt(0.3 - xi - 0.06, 0.3, z1 - z0 - 0.06, (xi + 0.3) / 2, FLOOR + 0.15, (z0 + z1) / 2, 1));
      seat.push(rbox(0.3 - xi, 0.14, z1 - z0, (xi + 0.3) / 2, FLOOR + 0.36, (z0 + z1) / 2, 0.05));        // нижняя полка
      seat.push(rbox(0.3 - xi - 0.04, 0.6, 0.1, (xi + 0.3) / 2, FLOOR + 0.76, bz, 0.045));                // спинка
      seat.push(rbox(0.3 - xi, 0.09, z1 - z0, (xi + 0.3) / 2, FLOOR + 1.55, (z0 + z1) / 2, 0.035));       // верхняя полка
      base.push(boxAt(0.03, 0.03, z1 - z0 - 0.1, 0.27, FLOOR + 1.66, (z0 + z1) / 2, 1));                 // поручень
      R(xi, 0.32, z0, z1);
    }
    wood.push(rbox(0.6, 0.04, 0.55, xi + 0.3, FLOOR + 0.75, a + 1.0, 0.018));                           // столик
    wood.push(boxAt(0.05, 0.72, 0.05, xi + 0.55, FLOOR + 0.37, a + 1.0, 1));
    R(xi, xi + 0.62, a + 0.72, a + 1.28);
    wood.push(rbox(0.3 - xi, 0.03, SEC - 0.08, (xi + 0.3) / 2, FLOOR + 2.1, a + 1.0, 0.012));           // третья полка
    // боковые места вдоль прохода
    base.push(boxAt(xo - SIDE0 - 0.06, 0.3, SEC - 0.22, (SIDE0 + xo) / 2, FLOOR + 0.15, a + 1.0, 1));
    seat.push(rbox(xo - SIDE0, 0.14, (SEC - 0.2) / 2, (SIDE0 + xo) / 2, FLOOR + 0.36, a + 0.55, 0.05));
    seat.push(rbox(xo - SIDE0, 0.14, (SEC - 0.2) / 2, (SIDE0 + xo) / 2, FLOOR + 0.36, a + 1.45, 0.05));
    seat.push(rbox(0.09, 0.5, SEC - 0.2, xo - 0.05, FLOOR + 0.72, a + 1.0, 0.04));
    seat.push(rbox(xo - SIDE0 + 0.05, 0.09, SEC - 0.16, (SIDE0 + xo) / 2, FLOOR + 1.6, a + 1.0, 0.035));
    R(SIDE0 - 0.02, xo, a + 0.08, a + SEC - 0.08);
    lamps.push(boxAt(0.5, 0.03, 0.9, 0.7, PEAK - 0.13, a + 1.0, 1));
  }
  // служебное купе (перёд) и туалет (зад) — закрытые выгородки
  const sz0 = -L / 2 + TAMB, sz1 = a0;
  part.push(boxAt(0.04, 2.1, sz1 - sz0, AIS0, FLOOR + 1.05, (sz0 + sz1) / 2, 2)); R(xi, AIS0 + 0.03, sz0, sz1);
  const tz0 = a0 + NS * SEC, tz1 = L / 2 - TAMB;
  part.push(boxAt(0.04, 2.1, tz1 - tz0, AIS0, FLOOR + 1.05, (tz0 + tz1) / 2, 2)); R(xi, AIS0 + 0.03, tz0, tz1);
  inner.push(rbox(0.32, 1.5, 0.6, xo - 0.16, FLOOR + 0.75, sz0 + 0.5, 0.05)); R(xo - 0.34, xo, sz0 + 0.18, sz0 + 0.82);   // титан
  lamps.push(boxAt(0.5, 0.03, 0.9, 0.7, PEAK - 0.13, sz0 + 1.0, 1), boxAt(0.5, 0.03, 0.9, 0.7, PEAK - 0.13, tz0 + 0.7, 1));
  // перегородки тамбуров с дверью в проход
  for (const zt of [-L / 2 + TAMB, L / 2 - TAMB]) {
    part.push(boxAt(0.5 - xi, 2.15, 0.05, (xi + 0.5) / 2, FLOOR + 1.07, zt, 2), boxAt(xo - 1.3, 2.15, 0.05, (1.3 + xo) / 2, FLOOR + 1.07, zt, 2), boxAt(0.8, 0.2, 0.05, 0.9, FLOOR + 2.05, zt, 1));
    R(xi, 0.5, zt - 0.04, zt + 0.04); R(1.3, xo, zt - 0.04, zt + 0.04);
    lamps.push(boxAt(0.4, 0.03, 0.4, 0, PEAK - 0.13, zt + Math.sign(zt) * 0.8, 1));
  }
  // торцевые стенки: проход только через дверь посередине
  for (const sg of [-1, 1]) { R(-HW, -0.4, sg > 0 ? L / 2 - 0.1 : -L / 2 - 0.5, sg > 0 ? L / 2 + 0.5 : -L / 2 + 0.1); R(0.4, HW, sg > 0 ? L / 2 - 0.1 : -L / 2 - 0.5, sg > 0 ? L / 2 + 0.5 : -L / 2 + 0.1); }
  add(merge(part), RM.part, false); add(merge(seat), RM.seat, false); add(merge(wood), RM.wood, false);
  add(merge(inner), RM.metal, false); add(merge(lamps), RM.lamp, false); add(merge(base), RM.dark, false);
  // места для обыска внутри брошенных вагонов: купе
  const spots = { doors: [-(L / 2 - 0.8), L / 2 - 0.8], ladder: L / 2 - 2.3, top: L / 2 - 3.2 };
  const roofY = (z, x = 0) => (Math.abs(z) < L / 2 ? PEAK - (PEAK - EAVE) * (x / HW) * (x / HW) : 0);
  return { g, wheels, len: L + 0.3, rects, spots, roofY, floor: FLOOR, halfW: HW, sections: Array.from({ length: NS }, (_, i) => a0 + i * SEC + SEC / 2) };
}

// ---------- тепловоз: кузов «лофтом» по сечениям, окраска цветами вершин
function loft(stations, ring, color) {
  const n = ring(stations[0]).length, pos = [], col = [], idx = [];
  const c = new THREE.Color();
  stations.forEach((st) => {
    for (const [x, y] of ring(st)) { pos.push(x, y, st.z); color(x, y, st, c); col.push(c.r, c.g, c.b); }
  });
  for (let i = 0; i < stations.length - 1; i++) for (let j = 0; j < n; j++) {
    const a = i * n + j, b = i * n + (j + 1) % n, a2 = a + n, b2 = b + n;
    idx.push(a, b, a2, b, b2, a2);
  }
  // торцы — веером из центра
  for (const [i, flip] of [[0, true], [stations.length - 1, false]]) {
    const st = stations[i], ctr = pos.length / 3; let cy = 0; for (const [, y] of ring(st)) cy += y; cy /= n;
    pos.push(0, cy, st.z); color(0, cy, st, c); col.push(c.r, c.g, c.b);
    for (let j = 0; j < n; j++) { const a = i * n + j, b = i * n + (j + 1) % n; if (flip) idx.push(ctr, b, a); else idx.push(ctr, a, b); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}
const LOCO_L = 20.4;
export function makePassLoco() {
  const L = LOCO_L, F = -L / 2, Bk = L / 2, Y0 = 1.0;
  const g = new THREE.Group(), wheels = [];
  const add = (geo, mat, cast = true) => { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = true; g.add(m); return m; };
  // профиль носа: [отступ от торца, полуширина, верх]
  const NOSE = [[0, 1.28, 2.3], [0.18, 1.4, 2.55], [0.45, 1.48, 2.85], [0.8, 1.53, 3.2], [1.25, 1.555, 3.62], [1.75, 1.56, 3.98], [2.25, 1.56, 4.22], [2.695, 1.56, 4.3], [2.705, 1.56, 4.3], [3.395, 1.56, 4.3], [3.405, 1.56, 4.3]];
  const st = [];
  for (const [o, hw, top] of NOSE) st.push({ z: F + o, o, hw, top });
  for (let z = F + 3.8; z < Bk - 3.8; z += 2.2) st.push({ z, o: 9, hw: 1.56, top: 4.3 });
  for (const [o, hw, top] of NOSE.slice().reverse()) st.push({ z: Bk - o, o, hw, top });
  const LV = [1.25, 1.695, 1.705, 2.05, 2.06, 2.27, 2.28, 2.89, 2.9, 3.5, 3.51, 3.7];
  const ring = (s) => {
    const eave = Math.min(s.top - 0.32, 3.72), half = [[0, Y0 - 0.02], [s.hw - 0.12, Y0], [s.hw, Y0 + 0.12]];
    for (const y of LV) half.push([s.hw, Math.min(y, eave)]);
    half.push([s.hw, eave]);
    for (let k = 1; k <= 6; k++) { const f = k / 6, a = f * HP; half.push([s.hw * Math.cos(a) * (1 - 0.05 * f), eave + (s.top - eave) * Math.sin(a)]); }
    const full = half.slice();
    for (let k = half.length - 2; k >= 1; k--) full.push([-half[k][0], half[k][1]]);
    return full;
  };
  const RED = new THREE.Color(0xb7232a), CREAM = new THREE.Color(0xf1e3bf), GREY = new THREE.Color(0x8b9094), DARK = new THREE.Color(0x34383b), GLASS = new THREE.Color(0x141c22), YEL = new THREE.Color(0xe7b62e);
  const color = (x, y, s, c) => {
    const o = s.o;
    if (y < 1.7) c.copy(o < 0.3 ? YEL : DARK);
    else if (y > 2.05 && y < 2.28) c.copy(CREAM);
    else if (o < 2.3 && y > 2.89 && y < 4.0 && Math.abs(x) < s.hw - 0.12) c.copy(GLASS);             // лобовое стекло
    else if (o > 2.7 && o < 3.4 && y > 2.89 && y < 3.51) c.copy(GLASS);                               // боковое окно кабины
    else if (y > 3.75 && o > 2.3) c.copy(GREY);
    else c.copy(RED);
  };
  add(loft(st, ring, color), RM.body);
  // рама, бак, тележки, сцепки
  const fr = [boxAt(2.9, 0.32, L - 0.6, 0, 1.05, 0, 3), boxAt(2.4, 0.8, 5.5, 0, 0.75, 0, 2)];
  for (const sg of [-1, 1]) fr.push(boxAt(0.36, 0.3, 0.5, 0, 1.0, sg * (L / 2 + 0.15), 1), boxAt(2.6, 0.5, 0.25, 0, 0.85, sg * (L / 2 - 0.05), 1));
  add(merge(fr), RM.dark);
  g.add(bogie(-(L / 2 - 4.3), 3, wheels, 1.9)); g.add(bogie(L / 2 - 4.3, 3, wheels, 1.9));
  // окна машинного отделения и жалюзи (тёмные вставки чуть над поверхностью)
  const win = [], grille = [];
  for (const sx of [-1, 1]) {
    for (let k = 0; k < 5; k++) { const z = F + 5.0 + k * 2.4; win.push(boxAt(0.02, 0.42, 0.9, sx * 1.567, 3.15, z, 1)); grille.push(boxAt(0.02, 0.5, 1.6, sx * 1.567, 2.6, z + 0.2, 1)); }
    win.push(boxAt(0.02, 1.85, 0.75, sx * 1.567, 2.05, F + 3.05, 1));   // дверь кабины
  }
  add(merge(win), RM.glass, false); add(merge(grille), RM.dark, false);
  // крышевое оборудование
  const roofEq = [];
  for (const z of [-2.6, -0.4, 1.8]) roofEq.push(cylGeo(0.62, 0.62, 0.12, 20).translate(0, 4.32, z));
  roofEq.push(boxAt(1.6, 0.18, 6.8, 0, 4.28, -0.4, 2));
  add(merge(roofEq), RM.dark);
  add(merge([cylGeo(0.2, 0.24, 0.5, 12).translate(0, 4.45, 3.8), cylGeo(0.2, 0.24, 0.5, 12).translate(0, 4.45, 4.5)]), RM.rubber);
  // фары и буферные огни
  const head = new THREE.Mesh(shared(cylGeo(0.2, 0.2, 0.12, 16).rotateX(HP)), B(0xfff1c2));
  head.position.set(0, 4.02, F + 1.62); head.rotation.x = -0.6; g.add(head);
  const small = shared(cylGeo(0.09, 0.09, 0.08, 12).rotateX(HP));
  for (const x of [-0.85, 0.85]) {
    const l = new THREE.Mesh(small, B(0xfff6d8)); l.position.set(x, 1.95, F + 0.1); g.add(l);
    const r = new THREE.Mesh(small, B(0xc02020)); r.position.set(x, 1.95, Bk - 0.1); g.add(r);
  }
  // поручни и лестница сзади
  const rails = [];
  for (const sx of [-1, 1]) {
    for (const z of [F + 2.62, F + 3.48]) rails.push(cylGeo(0.022, 0.022, 1.8, 6).translate(sx * 1.6, 2.1, z));
    for (let k = 0; k < 3; k++) rails.push(boxAt(0.3, 0.04, 0.7, sx * 1.48, 0.45 + k * 0.3, F + 3.05, 1));
    for (const dz of [-0.22, 0.22]) rails.push(cylGeo(0.022, 0.022, 3.6, 6).translate(sx * 1.6, 2.4, Bk - 2.3 + dz));
    for (let y = 0.8; y < 4.2; y += 0.38) rails.push(cylGeo(0.018, 0.018, 0.44, 5).rotateX(HP).translate(sx * 1.6, y, Bk - 2.3));
  }
  add(merge(rails), RM.metal);
  // номер на борту
  // улучшения (видимость переключается)
  const up = {};
  const plowM = M('rusty_metal_02', 0x9a9a9a), plow = new THREE.Group();
  const p1 = new THREE.Mesh(boxAt(2.1, 1.1, 0.12, 0, 0, 0, 1.5), plowM); p1.position.set(-0.78, 0.6, F - 0.75); p1.rotation.y = -0.62; plow.add(p1);
  const p2 = new THREE.Mesh(boxAt(2.1, 1.1, 0.12, 0, 0, 0, 1.5), plowM); p2.position.set(0.78, 0.6, F - 0.75); p2.rotation.y = 0.62; plow.add(p2);
  g.add(plow); up.plow = plow;
  const armor = new THREE.Mesh(merge([boxAt(0.08, 1.1, 12, -1.63, 2.6, 0.6, 1.5), boxAt(0.08, 1.1, 12, 1.63, 2.6, 0.6, 1.5)]), M('rusty_metal_02', 0x8a8a8a));
  g.add(armor); up.armor = armor;
  const sl = new THREE.Group();
  sl.add(new THREE.Mesh(shared(new THREE.CylinderGeometry(0.32, 0.36, 0.5, 14).rotateX(HP)), P(0x444444, 30)));
  const slGlass = new THREE.Mesh(shared(new THREE.CircleGeometry(0.3, 16)), B(0xfffbe0)); slGlass.position.z = -0.26; slGlass.rotation.y = Math.PI; sl.add(slGlass);
  sl.position.set(0.7, 4.6, F + 3.4); g.add(sl); up.light = sl;
  const tur = makeTurret(); tur.position.set(0, 4.32, Bk - 4.0); g.add(tur); up.turret = tur;
  const topAt = (z) => { const o = Math.min(z - F, Bk - z); if (o >= 2.7) return 4.3; for (let i = 1; i < NOSE.length; i++) if (NOSE[i][0] >= o) { const [o0, , t0] = NOSE[i - 1], [o1, , t1] = NOSE[i]; return t0 + (t1 - t0) * (o - o0) / (o1 - o0); } return 2.3; };
  return { g, wheels, up, len: L, roofY: (z) => topAt(z), lampPos: new THREE.Vector3(0, 4.0, F - 0.1),
    cabCam: new THREE.Vector3(0.55, 3.45, F + 2.05), gunPos: new THREE.Vector3(1.1, 3.3, F + 2.4),
    spots: { door: F + 3.05, ladder: Bk - 2.3, top: Bk - 3.2 } };
}
function makeTurret() {
  const t = new THREE.Group();
  const bags = new THREE.Mesh(shared(new THREE.CylinderGeometry(1.0, 1.1, 0.7, 14)), std(0x8a7a55, { roughness: 0.95 }));
  bags.position.y = 0.35; t.add(bags);
  const gun = new THREE.Group(); gun.position.y = 0.95;
  gun.add(new THREE.Mesh(boxAt(0.18, 0.2, 0.7, 0, 0, 0, 1), RM.dark));
  gun.add(new THREE.Mesh(shared(cylGeo(0.035, 0.035, 1.0, 8).rotateX(HP).translate(0, 0.02, -0.8)), RM.dark));
  t.add(gun); t.userData.gun = gun;
  return t;
}
