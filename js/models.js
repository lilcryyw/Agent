import * as THREE from '../vendor/three.module.min.js';
import { M, C, P, B, boxGeo, boxAt, cylGeo, merge, shared, QuadBatch, sign, pick, R, RI, gableGeo, mulberry32 } from './util.js';

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

// ---------- окраска (рисуется на холсте, без фото-текстур)
function canvasTex(w, h, draw, flip) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  if (flip) { t.wrapS = THREE.RepeatWrapping; t.repeat.x = -1; t.offset.x = 1; }
  return t;
}
function grime(x, w, h, seed, k = 1) {
  const r = mulberry32(seed);
  const g = x.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, 'rgba(0,0,0,0.12)'); g.addColorStop(0.15, 'rgba(0,0,0,0)'); g.addColorStop(0.75, 'rgba(40,30,20,0.08)'); g.addColorStop(1, 'rgba(40,30,20,0.45)');
  x.fillStyle = g; x.fillRect(0, 0, w, h);
  for (let i = 0; i < 160 * k; i++) {
    const px = r() * w, py = r() * h, len = 10 + r() * h * 0.25;
    x.fillStyle = `rgba(30,25,15,${0.03 + r() * 0.06})`; x.fillRect(px, py, 1 + r() * 2, len);
  }
  for (let i = 0; i < 2500 * k; i++) { x.fillStyle = `rgba(0,0,0,${r() * 0.05})`; x.fillRect(r() * w, r() * h, 2, 2); }
}
const GREEN = '#2f6a49', GREEN_D = '#244f37', YEL = '#e8b730', RED = '#b8281c';
function locoSide(x, w, h) {
  // w — длина 17.6 м, h — высота кузова 2.95 м
  const m = w / 17.6, Y = (v) => h - v * (h / 2.95);
  const pg = x.createLinearGradient(0, 0, 0, h); pg.addColorStop(0, '#3b7d58'); pg.addColorStop(1, GREEN_D);
  x.fillStyle = pg; x.fillRect(0, 0, w, h);
  // полосы
  x.fillStyle = YEL; x.fillRect(0, Y(1.0), w, 0.26 * (h / 2.95));
  x.fillStyle = RED; x.fillRect(0, Y(1.06), w, 0.035 * (h / 2.95)); x.fillRect(0, Y(0.76), w, 0.035 * (h / 2.95));
  x.fillStyle = YEL; x.fillRect(0, Y(2.2), w, 0.06 * (h / 2.95));
  // швы панелей и заклёпки
  for (let z = 0.6; z < 17.6; z += 1.25) {
    const px = z * m;
    x.fillStyle = 'rgba(0,0,0,0.35)'; x.fillRect(px, 0, 2, h);
    x.fillStyle = 'rgba(255,255,255,0.08)'; x.fillRect(px + 2, 0, 1, h);
    x.fillStyle = 'rgba(0,0,0,0.3)';
    for (let y = 8; y < h; y += 14) { x.beginPath(); x.arc(px - 4, y, 1.6, 0, 7); x.fill(); }
  }
  // жалюзи машинного отделения (кабина справа: u→1 = перёд)
  for (let i = 0; i < 6; i++) {
    const x0 = (1.0 + i * 2.15) * m, ww = 1.8 * m, y0 = Y(2.75), hh = 0.55 * (h / 2.95);
    x.fillStyle = '#1b2a22'; x.fillRect(x0, y0, ww, hh);
    for (let k = 0; k < hh; k += 5) { x.fillStyle = 'rgba(120,160,130,0.35)'; x.fillRect(x0 + 2, y0 + k, ww - 4, 1.5); }
    x.strokeStyle = '#162019'; x.lineWidth = 3; x.strokeRect(x0, y0, ww, hh);
    // подтёки под жалюзи
    for (let k = 0; k < 6; k++) { x.fillStyle = 'rgba(20,20,15,0.12)'; x.fillRect(x0 + Math.random() * ww, y0 + hh, 2, 20 + Math.random() * 60); }
  }
  // боковые окошки машинного отделения
  for (const z of [4.2, 9.1]) { x.fillStyle = '#142026'; x.fillRect(z * m, Y(2.1), 0.5 * m, 0.45 * (h / 2.95)); x.strokeStyle = '#d8d0b0'; x.lineWidth = 2; x.strokeRect(z * m, Y(2.1), 0.5 * m, 0.45 * (h / 2.95)); }
  // кабина: дверь и окно
  const dz = 15.1 * m;
  x.strokeStyle = 'rgba(0,0,0,0.6)'; x.lineWidth = 3; x.strokeRect(dz, Y(2.75), 0.75 * m, 2.6 * (h / 2.95));
  x.fillStyle = '#121c22'; x.fillRect(dz + 0.12 * m, Y(2.6), 0.5 * m, 0.6 * (h / 2.95));
  x.fillStyle = '#121c22'; x.fillRect(16.1 * m, Y(2.6), 1.0 * m, 0.7 * (h / 2.95));
  x.strokeStyle = '#e0dcc8'; x.lineWidth = 3; x.strokeRect(16.1 * m, Y(2.6), 1.0 * m, 0.7 * (h / 2.95));
  x.fillStyle = 'rgba(200,220,230,0.15)'; x.fillRect(16.15 * m, Y(2.6), 0.4 * m, 0.25 * (h / 2.95));
  // поручни у двери
  x.fillStyle = '#d8d4c4'; x.fillRect(dz - 6, Y(2.5), 4, 2.1 * (h / 2.95)); x.fillRect(dz + 0.75 * m + 2, Y(2.5), 4, 2.1 * (h / 2.95));
  grime(x, w, h, 1347);
}
function locoFront(x, w, h) {
  const pg = x.createLinearGradient(0, 0, 0, h); pg.addColorStop(0, '#3b7d58'); pg.addColorStop(1, GREEN_D);
  x.fillStyle = pg; x.fillRect(0, 0, w, h);
  const sy = h / 2.95, sx = w / 3.04;
  // «усы»
  x.fillStyle = YEL;
  x.beginPath(); x.moveTo(0, h - 1.0 * sy); x.lineTo(w * 0.5, h - 0.55 * sy); x.lineTo(w, h - 1.0 * sy); x.lineTo(w, h - 0.74 * sy); x.lineTo(w * 0.5, h - 0.3 * sy); x.lineTo(0, h - 0.74 * sy); x.fill();
  x.fillStyle = RED; x.fillRect(0, h - 0.22 * sy, w, 0.22 * sy);
  // лобовые стёкла
  for (const cx of [0.78, 2.26]) {
    x.fillStyle = '#dcd6c2'; x.fillRect((cx - 0.66) * sx, 0.18 * sy, 1.32 * sx, 0.9 * sy);
    const g = x.createLinearGradient(0, 0.22 * sy, 0, 1.05 * sy); g.addColorStop(0, '#2c3f4a'); g.addColorStop(1, '#0e171c');
    x.fillStyle = g; x.fillRect((cx - 0.6) * sx, 0.24 * sy, 1.2 * sx, 0.78 * sy);
    x.strokeStyle = '#111'; x.lineWidth = 4; x.beginPath(); x.moveTo((cx - 0.3) * sx, 1.0 * sy); x.lineTo((cx + 0.25) * sx, 0.45 * sy); x.stroke();
  }
  // номер
  x.fillStyle = '#f0e6c0'; x.font = `bold ${0.22 * sy}px Arial`; x.textAlign = 'center'; x.fillText('1347', w / 2, 1.45 * sy);
  grime(x, w, h, 99, 0.4);
}
function locoRear(x, w, h) {
  const pg = x.createLinearGradient(0, 0, 0, h); pg.addColorStop(0, '#3b7d58'); pg.addColorStop(1, GREEN_D);
  x.fillStyle = pg; x.fillRect(0, 0, w, h);
  x.fillStyle = '#1e2a24'; x.fillRect(w * 0.38, h * 0.12, w * 0.24, h * 0.86);
  x.fillStyle = '#121c22'; x.fillRect(w * 0.42, h * 0.2, w * 0.16, h * 0.18);
  x.fillStyle = YEL; x.fillRect(0, h - 1.0 * h / 2.95, w * 0.36, 0.26 * h / 2.95); x.fillRect(w * 0.64, h - 1.0 * h / 2.95, w * 0.36, 0.26 * h / 2.95);
  grime(x, w, h, 7, 0.4);
}
function wagonSide(x, w, h, base) {
  const r = mulberry32(base);
  x.fillStyle = ['#7a3b2a', '#6e3a2c', '#80482f', '#5f3a2e'][base % 4]; x.fillRect(0, 0, w, h);
  for (let i = 0; i < 18; i++) { const px = (i + 0.5) * w / 18; x.fillStyle = 'rgba(0,0,0,0.3)'; x.fillRect(px - 5, 0, 10, h); x.fillStyle = 'rgba(255,255,255,0.07)'; x.fillRect(px - 5, 0, 3, h); }
  x.fillStyle = 'rgba(0,0,0,0.25)'; x.fillRect(0, h * 0.48, w, 6);
  x.fillStyle = '#4a2a20'; x.fillRect(w * 0.42, h * 0.08, w * 0.16, h * 0.9);
  x.strokeStyle = 'rgba(0,0,0,0.5)'; x.lineWidth = 4; x.strokeRect(w * 0.42, h * 0.08, w * 0.16, h * 0.9);
  x.fillStyle = '#e8e4d0'; x.font = `bold ${h * 0.09}px Arial`; x.textAlign = 'left';
  const n = String(2 + (base % 5)) + String(Math.floor(r() * 9000000) + 1000000);
  x.fillText(n.slice(0, 2) + '-' + n.slice(2, 5) + '-' + n.slice(5), w * 0.07, h * 0.18);
  x.font = `${h * 0.06}px Arial`; x.fillText('ГП 68 т  ТАРА 24,7 т', w * 0.07, h * 0.28);
  grime(x, w, h, base, 1.3);
}

// ---------- тепловоз 2ТЭ116 (одна секция)
export const LOCO_LEN = 18.2;
let LOCO_MATS = null;
function locoMats() {
  if (LOCO_MATS) return LOCO_MATS;
  const side = canvasTex(2048, 344, locoSide), sideL = canvasTex(2048, 344, locoSide, true);
  const front = canvasTex(512, 496, locoFront), rear = canvasTex(512, 496, locoRear);
  const ph = (map) => new THREE.MeshPhongMaterial({ map, shininess: 28, specular: 0x2a2a2a });
  const roof = new THREE.MeshPhongMaterial({ color: 0x6a6f72, shininess: 15, specular: 0x222222 });
  // грани коробки: +x, −x, верх, низ, +z (зад), −z (перёд)
  LOCO_MATS = [ph(side), ph(sideL), roof, roof, ph(rear), ph(front)];
  return LOCO_MATS;
}
export function makeLoco(num = '1347') {
  const g = new THREE.Group(), wheels = [];
  const metal = C(0x2b2d2e), grey = P(0x6a6f72, 15), rail = P(0xd8d4c4, 40);
  g.add(new THREE.Mesh(boxAt(3.0, 0.5, 17.6, 0, 1.35, 0, 2), metal));                                   // рама
  g.add(new THREE.Mesh(merge([boxAt(3.1, 0.6, 0.22, 0, 1.2, -8.92, 2), boxAt(3.1, 0.6, 0.22, 0, 1.2, 8.92, 2)]), P(0xb02a20, 20)));
  const body = new THREE.Mesh(new THREE.BoxGeometry(3.04, 2.95, 17.6), locoMats());
  body.position.y = 3.08; g.add(body);
  // крыша и оборудование
  g.add(new THREE.Mesh(merge([boxAt(2.8, 0.3, 17.2, 0, 4.7, 0, 3), boxAt(2.2, 0.35, 11, 0, 4.98, 1.6, 3)]), grey));
  const fans = merge([0, 1, 2].map((i) => cylGeo(0.66, 0.66, 0.12, 16).translate(0, 5.2, -1.6 + i * 1.75)));
  g.add(new THREE.Mesh(fans, C(0x2a2d30)));
  const grill = merge([0, 1, 2].map((i) => boxAt(1.2, 0.02, 0.06, 0, 5.27, -1.6 + i * 1.75, 1)).concat([0, 1, 2].map((i) => boxAt(0.06, 0.02, 1.2, 0, 5.27, -1.6 + i * 1.75, 1))));
  g.add(new THREE.Mesh(grill, metal));
  g.add(new THREE.Mesh(merge([cylGeo(0.22, 0.26, 0.7, 10).translate(0.5, 5.4, 5.6), cylGeo(0.22, 0.26, 0.7, 10).translate(-0.5, 5.4, 5.6)]), C(0x1c1c1c)));  // выхлоп
  g.add(new THREE.Mesh(merge([cylGeo(0.07, 0.16, 0.5, 8).rotateX(Math.PI / 2).translate(0.35, 5.0, -7.9), cylGeo(0.07, 0.16, 0.5, 8).rotateX(Math.PI / 2).translate(-0.35, 5.0, -7.9)]), P(0xbfbfbf, 80))); // тифоны
  // козырёк кабины
  g.add(new THREE.Mesh(boxAt(3.04, 0.12, 0.45, 0, 4.55, -8.95, 1), P(0x244f37, 20)));
  // поручни вдоль кузова и у дверей
  const rails = [];
  for (const f of [1, -1]) {
    rails.push(cylGeo(0.025, 0.025, 13.2, 6).rotateX(Math.PI / 2).translate(f * 1.6, 2.35, 1.5));
    for (const z of [-6.0, -6.9]) rails.push(cylGeo(0.025, 0.025, 1.9, 6).translate(f * 1.6, 2.6, z));
    for (const z of [8.3, 8.85]) rails.push(cylGeo(0.025, 0.025, 2.6, 6).translate(f * 1.6, 2.9, z));
    for (let k = 0; k < 7; k++) rails.push(cylGeo(0.02, 0.02, 0.5, 4).rotateX(Math.PI / 2).translate(f * 1.6, 1.9 + k * 0.42, 8.57));
  }
  g.add(new THREE.Mesh(merge(rails), rail));
  // ступени у двери кабины и сзади
  const steps = [];
  for (const f of [1, -1]) for (const z of [-6.45, 8.55]) for (let k = 0; k < 3; k++) steps.push(boxAt(0.35, 0.05, 0.6, f * 1.48, 0.55 + k * 0.4, z, 1));
  g.add(new THREE.Mesh(merge(steps), C(0x3a3a3a)));
  g.add(new THREE.Mesh(boxAt(2.6, 1.0, 5, 0, 0.85, 0, 2), M('rusty_metal_02', 0x555555)));              // топливный бак
  g.add(new THREE.Mesh(merge([boxAt(0.4, 0.35, 0.5, 0, 1.0, -9.2, 1), boxAt(0.4, 0.35, 0.5, 0, 1.0, 9.2, 1)]), C(0x2a2a2a))); // автосцепка СА-3
  // номер на борту
  for (const f of [1, -1]) {
    const s = sign('2ТЭ116-' + num, 1.7, 0.32, '#2f6a49', '#f0e6c0', false);
    s.position.set(f * 1.525, 3.55, -6.0); s.rotation.y = f * Math.PI / 2; g.add(s);
  }
  // прожектор и буферные фонари
  const lamp = new THREE.Mesh(shared(new THREE.CylinderGeometry(0.22, 0.22, 0.14, 14).rotateX(Math.PI / 2)), B(0xfff1c2));
  lamp.position.set(0, 4.28, -8.86); g.add(lamp);
  const small = shared(new THREE.CylinderGeometry(0.1, 0.1, 0.1, 10).rotateX(Math.PI / 2));
  for (const x of [-1.15, 1.15]) {
    const l = new THREE.Mesh(small, B(0xfff6d8)); l.position.set(x, 1.85, -8.85); g.add(l);
    const r = new THREE.Mesh(small, B(0xc02020)); r.position.set(x, 1.85, 8.85); g.add(r);
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
  const armor = new THREE.Mesh(merge([boxAt(0.08, 1.4, 12.5, -1.6, 3.1, 1.8, 1.5), boxAt(0.08, 1.4, 12.5, 1.6, 3.1, 1.8, 1.5)]), M('rusty_metal_02', 0x8a8a8a));
  g.add(armor); up.armor = armor;
  const sl = new THREE.Group();
  sl.add(new THREE.Mesh(shared(new THREE.CylinderGeometry(0.32, 0.36, 0.5, 10).rotateX(Math.PI / 2)), C(0x444444)));
  const slGlass = new THREE.Mesh(shared(new THREE.CircleGeometry(0.3, 12)), B(0xfffbe0)); slGlass.position.z = -0.26; slGlass.rotation.y = Math.PI; sl.add(slGlass);
  sl.position.set(0.9, 5.15, -7.6); g.add(sl); up.light = sl;
  const tur = makeTurret(); tur.position.set(0, 5.15, 6.8); g.add(tur); up.turret = tur;
  return { g, wheels, up, lampPos: new THREE.Vector3(0, 4.28, -9.0) };
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
const BOX_BODY = shared(new THREE.BoxGeometry(3.2, 3.4, 13.8));
const WMATS = {};
function wagonMats(v) {
  if (WMATS[v]) return WMATS[v];
  const seed = 1000 + v * 7919;
  const ph = (map) => new THREE.MeshPhongMaterial({ map, shininess: 12, specular: 0x111111 });
  const endT = M('rusty_metal_02', 0xb0705a);
  return (WMATS[v] = [ph(canvasTex(1024, 256, (x, w, h) => wagonSide(x, w, h, seed))), ph(canvasTex(1024, 256, (x, w, h) => wagonSide(x, w, h, seed), true)), C(0x6b6b66), C(0x333333), endT, endT]);
}
export function makeBoxcar(r, tint) {
  const g = new THREE.Group(), wheels = [];
  tint = tint ?? pick(r, [0xb0705a, 0xa06050, 0x8a6a58, 0xb8846a, 0x7a6a5a]);
  g.add(new THREE.Mesh(boxAt(2.9, 0.4, 13.9, 0, 1.25, 0, 2), C(0x2a2a2a)));
  const bodyM = new THREE.Mesh(BOX_BODY, wagonMats(Math.floor(r() * 8)));
  bodyM.position.y = 3.15; g.add(bodyM);
  const lad = [];
  for (const f of [1, -1]) { lad.push(cylGeo(0.025, 0.025, 3.6, 4).translate(f * 1.63, 3.2, 6.55), cylGeo(0.025, 0.025, 3.6, 4).translate(f * 1.63, 3.2, 6.95));
    for (let k = 0; k < 9; k++) lad.push(cylGeo(0.02, 0.02, 0.42, 4).rotateX(Math.PI / 2).translate(f * 1.63, 1.6 + k * 0.4, 6.75)); }
  g.add(new THREE.Mesh(merge(lad), P(0x9a9a90, 30)));
  g.add(new THREE.Mesh(boxAt(3.05, 0.3, 13.8, 0, 5.0, 0, 3), C(0x6b6b66)));
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
