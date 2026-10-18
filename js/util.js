import * as THREE from '../vendor/three.module.min.js';

// ---------- случайность по зерну: один и тот же участок всегда одинаков, но участки не повторяются
export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function rngOf(...n) {
  let h = 2166136261 >>> 0;
  for (const x of n) { h = Math.imul(h ^ (x | 0), 16777619); h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995); h ^= h >>> 15; }
  return mulberry32(h >>> 0);
}
export const R = (r, a, b) => a + r() * (b - a);
export const RI = (r, a, b) => Math.floor(a + r() * (b - a + 1));
export const pick = (r, a) => a[Math.floor(r() * a.length)];
export function wpick(r, list) {
  let t = 0; for (const e of list) t += e[1];
  let x = r() * t;
  for (const e of list) { x -= e[1]; if (x <= 0) return e[0]; }
  return list[list.length - 1][0];
}
export const clamp = (x, a, b) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, t) => a + (b - a) * t;

// ---------- путь: колея идёт к −Z, плавные кривые по сумме синусов
export function trackX(s) { return 40 * Math.sin(s / 900) + 25 * Math.sin(s / 2300 + 1.3) + 10 * Math.sin(s / 400 + 0.5); }
export function trackDX(s) { return 40 / 900 * Math.cos(s / 900) + 25 / 2300 * Math.cos(s / 2300 + 1.3) + 10 / 400 * Math.cos(s / 400 + 0.5); }
// nx,nz — нормаль вправо по ходу; yaw — поворот объекта, у которого «перёд» смотрит в −Z
export function frameAt(s, o = {}) {
  const dx = trackDX(s), n = Math.hypot(1, dx);
  o.x = trackX(s); o.z = -s; o.nx = 1 / n; o.nz = dx / n; o.yaw = -Math.atan(dx);
  return o;
}
const _f = {};
export function worldPos(s, d, h = 0, v = new THREE.Vector3()) {
  frameAt(s, _f);
  return v.set(_f.x + _f.nx * d, h, _f.z + _f.nz * d);
}
// приблизительно обратное: мировая точка -> (s, d)
export function toTrack(x, z, o = {}) {
  const s = -z; frameAt(s, _f);
  o.s = s; o.d = (x - _f.x) * _f.nx; return o;
}

// ---------- текстуры и материалы
export const T = {};
const matCache = new Map();
export function M(tex, color = 0xffffff, opts) {
  const key = tex + '|' + color + (opts ? JSON.stringify(opts) : '');
  let m = matCache.get(key);
  if (!m) { m = new THREE.MeshLambertMaterial({ map: tex ? T[tex] : null, color, ...(opts || {}) }); matCache.set(key, m); }
  return m;
}
export const C = (color, opts) => M(null, color, opts);
const phongCache = new Map();
export function P(color, shin = 60) {
  const k = color + '|' + shin; let m = phongCache.get(k);
  if (!m) { m = new THREE.MeshPhongMaterial({ color, shininess: shin, specular: 0x555555 }); phongCache.set(k, m); }
  return m;
}
const basicCache = new Map();
export function B(color, opts) {
  const k = color + (opts ? JSON.stringify(opts) : ''); let m = basicCache.get(k);
  if (!m) { m = new THREE.MeshBasicMaterial({ color, ...(opts || {}) }); basicCache.set(k, m); }
  return m;
}
export const VCOL = new THREE.MeshBasicMaterial({ vertexColors: true });

// ---------- геометрия
export function shared(g) { g.userData.shared = true; return g; }
// коробка с UV в метрах (ts — сколько метров на один повтор текстуры)
export function boxGeo(w, h, d, ts = 3) {
  const g = new THREE.BoxGeometry(w, h, d);
  const uv = g.attributes.uv;
  const sc = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let i = 0; i < 4; i++) {
    const k = f * 4 + i; uv.setXY(k, uv.getX(k) * sc[f][0] / ts, uv.getY(k) * sc[f][1] / ts);
  }
  return g;
}
export function boxAt(w, h, d, x, y, z, ts = 3, ry = 0) {
  const g = boxGeo(w, h, d, ts); if (ry) g.rotateY(ry); g.translate(x, y, z); return g;
}
export function cylGeo(rt, rb, h, seg = 10, ts = 3) {
  const g = new THREE.CylinderGeometry(rt, rb, h, seg);
  const uv = g.attributes.uv, k = (2 * Math.PI * Math.max(rt, rb)) / ts;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * k, uv.getY(i) * h / ts);
  return g;
}
// объединить геометрии с индексами в одну (меньше вызовов отрисовки)
export function merge(geos) {
  geos = geos.map((g) => (g.index ? g : indexify(g)));
  let vc = 0, ic = 0;
  for (const g of geos) { vc += g.attributes.position.count; ic += g.index.count; }
  const pos = new Float32Array(vc * 3), nor = new Float32Array(vc * 3), uv = new Float32Array(vc * 2), idx = new Uint32Array(ic);
  let vo = 0, io = 0;
  for (const g of geos) {
    const n = g.attributes.position.count;
    pos.set(g.attributes.position.array, vo * 3);
    if (!g.attributes.normal) g.computeVertexNormals();
    nor.set(g.attributes.normal.array, vo * 3);
    if (g.attributes.uv) uv.set(g.attributes.uv.array, vo * 2);
    const ia = g.index.array;
    for (let i = 0; i < ia.length; i++) idx[io + i] = ia[i] + vo;
    vo += n; io += ia.length; g.dispose();
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  out.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  out.setIndex(new THREE.BufferAttribute(idx, 1));
  return out;
}
function indexify(g) {
  const n = g.attributes.position.count, a = new Uint32Array(n);
  for (let i = 0; i < n; i++) a[i] = i;
  g.setIndex(new THREE.BufferAttribute(a, 1)); return g;
}
// двускатная крыша: конёк вдоль X
export function gableGeo(w, d, rh, o = 0.4, ts = 2.5) {
  const W = w / 2 + o, D = d / 2 + o, sl = Math.hypot(D, rh);
  const p = [], u = [];
  const quad = (a, b, c, e, ua, ub, uc, ue) => { p.push(...a, ...b, ...c, ...a, ...c, ...e); u.push(...ua, ...ub, ...uc, ...ua, ...uc, ...ue); };
  quad([-W, 0, D], [W, 0, D], [W, rh, 0], [-W, rh, 0], [0, 0], [2 * W / ts, 0], [2 * W / ts, sl / ts], [0, sl / ts]);
  quad([W, 0, -D], [-W, 0, -D], [-W, rh, 0], [W, rh, 0], [0, 0], [2 * W / ts, 0], [2 * W / ts, sl / ts], [0, sl / ts]);
  p.push(-W, 0, -D, -W, 0, D, -W, rh, 0); u.push(0, 0, 2 * D / ts, 0, D / ts, rh / ts);
  p.push(W, 0, D, W, 0, -D, W, rh, 0); u.push(0, 0, 2 * D / ts, 0, D / ts, rh / ts);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(u, 2));
  g.computeVertexNormals();
  return g;
}
// пачка цветных прямоугольников (окна, двери) — одна геометрия, цвет в вершинах
export class QuadBatch {
  constructor() { this.p = []; this.c = []; this.i = []; }
  quad(cx, cy, cz, ax, ay, az, bx, by, bz, color) {
    const n = this.p.length / 3;
    this.p.push(cx - ax - bx, cy - ay - by, cz - az - bz, cx + ax - bx, cy + ay - by, cz + az - bz,
      cx + ax + bx, cy + ay + by, cz + az + bz, cx - ax + bx, cy - ay + by, cz - az + bz);
    _c.set(color);
    for (let k = 0; k < 4; k++) this.c.push(_c.r, _c.g, _c.b);
    this.i.push(n, n + 1, n + 2, n, n + 2, n + 3);
  }
  // окно на грани: f=+1 — передняя (+Z), f=-1 — задняя
  front(x, y, z, hw, hh, f, color) { this.quad(x, y, z, f * hw, 0, 0, 0, hh, 0, color); }
  side(x, y, z, hw, hh, f, color) { this.quad(x, y, z, 0, 0, -f * hw, 0, hh, 0, color); }
  mesh() {
    if (!this.p.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(this.c, 3));
    g.setIndex(this.i);
    return new THREE.Mesh(g, VCOL);
  }
}
const _c = new THREE.Color();

// лента вдоль пути: cross — профиль [[d,h],...] слева направо
const _f2 = {};
export function ribbon(sA, sB, step, cross, O, uScale = 3, vScale = 3, vOff = 0) {
  const n = Math.max(1, Math.ceil((sB - sA) / step)), m = cross.length;
  const pos = [], uv = [], idx = [];
  const cu = [0];
  for (let j = 1; j < m; j++) cu[j] = cu[j - 1] + Math.hypot(cross[j][0] - cross[j - 1][0], cross[j][1] - cross[j - 1][1]);
  for (let i = 0; i <= n; i++) {
    const s = sA + (sB - sA) * i / n; frameAt(s, _f2);
    for (let j = 0; j < m; j++) {
      const d = cross[j][0], h = cross[j][1];
      pos.push(_f2.x + _f2.nx * d - O.x, h, _f2.z + _f2.nz * d - O.z);
      uv.push(cu[j] / uScale, (s - sA + vOff) / vScale);
    }
  }
  for (let i = 0; i < n; i++) for (let j = 0; j < m - 1; j++) {
    const a = i * m + j, b = a + m;
    idx.push(a, a + 1, b, a + 1, b + 1, b);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}

// ---------- вывески (текст на холсте)
const signCache = new Map();
const unitPlane = shared(new THREE.PlaneGeometry(1, 1));
export function signMat(text, bg = '#1f4e8c', fg = '#ffffff', border = true) {
  const key = text + bg + fg + border;
  let m = signCache.get(key);
  if (m) return m;
  const c = document.createElement('canvas'); c.width = 512; c.height = 112;
  const x = c.getContext('2d');
  x.fillStyle = bg; x.fillRect(0, 0, 512, 112);
  if (border) { x.strokeStyle = fg; x.lineWidth = 6; x.strokeRect(8, 8, 496, 96); }
  x.fillStyle = fg;
  let fs = 68; x.font = `bold ${fs}px "Arial Narrow", Arial, sans-serif`;
  while (x.measureText(text).width > 470 && fs > 20) { fs -= 4; x.font = `bold ${fs}px "Arial Narrow", Arial, sans-serif`; }
  x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(text, 256, 58);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  m = new THREE.MeshLambertMaterial({ map: t });
  if (signCache.size > 120) { const k0 = signCache.keys().next().value; signCache.get(k0).map.dispose(); signCache.delete(k0); }
  signCache.set(key, m);
  return m;
}
export function sign(text, w, h, bg, fg, border) {
  const m = new THREE.Mesh(unitPlane, signMat(text, bg, fg, border));
  m.scale.set(w, h, 1); return m;
}

export function disposeTree(o) {
  o.traverse((c) => {
    if (c.geometry && !c.geometry.userData.shared) c.geometry.dispose();
    if (c.isInstancedMesh) c.dispose();
  });
}
