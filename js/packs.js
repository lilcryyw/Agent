// Готовые низкополигональные модели (Quaternius, CC0): поезда и природа.
// Формат: json с описанием частей + bin с вершинами. Части одной модели сливаются в одну геометрию с цветами вершин.
import * as THREE from '../vendor/three.module.min.js';

const RAW = {};
const cache = new Map();
export const PACK_MAT = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.82, metalness: 0 });

export async function loadPacks(names, prog) {
  let done = 0;
  await Promise.all(names.map(async (n) => {
    const [meta, bin] = await Promise.all([
      fetch(`assets/models/${n}.json`).then((r) => r.json()),
      fetch(`assets/models/${n}.bin`).then((r) => r.arrayBuffer()),
    ]);
    for (const [k, m] of Object.entries(meta)) RAW[k] = { m, bin };
    done++; prog && prog(done / names.length);
  }));
}
export const hasModel = (name) => !!RAW[name];
export function modelBox(name) { return RAW[name].m.box; }

const _c = new THREE.Color();
// name — модель; o.scale, o.rotY, o.colors {материал: 0xRRGGBB (sRGB)}, o.tint — домножить цвет всех частей
export function packGeo(name, o = {}) {
  const key = name + JSON.stringify(o);
  let g = cache.get(key);
  if (g) return g;
  const R = RAW[name];
  if (!R) throw new Error('нет модели ' + name);
  const parts = R.m.parts;
  let vc = 0, ic = 0;
  for (const p of parts) { vc += p.v; ic += p.ic; }
  const pos = new Float32Array(vc * 3), nor = new Float32Array(vc * 3), col = new Float32Array(vc * 3);
  const idx = vc < 65536 ? new Uint16Array(ic) : new Uint32Array(ic);
  let vo = 0, io = 0;
  for (const p of parts) {
    pos.set(new Float32Array(R.bin, p.p, p.v * 3), vo * 3);
    const n8 = new Int8Array(R.bin, p.n, p.v * 3);
    for (let i = 0; i < n8.length; i++) nor[vo * 3 + i] = n8[i] / 127;
    const base = p.m.replace(/\.\d+$/, '');
    if (o.colors && o.colors[base] != null) _c.setHex(o.colors[base]);
    else _c.setHex(p.c, THREE.LinearSRGBColorSpace);
    if (o.tint) _c.multiply(new THREE.Color(o.tint));
    for (let i = 0; i < p.v; i++) col.set([_c.r, _c.g, _c.b], (vo + i) * 3);
    const ia = p.i32 ? new Uint32Array(R.bin, p.i, p.ic) : new Uint16Array(R.bin, p.i, p.ic);
    for (let i = 0; i < ia.length; i++) idx[io + i] = ia[i] + vo;
    vo += p.v; io += p.ic;
  }
  g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  if (o.rotY) g.rotateY(o.rotY);
  if (o.scale) { const s = o.scale; if (Array.isArray(s)) g.scale(s[0], s[1], s[2]); else g.scale(s, s, s); }
  g.computeBoundingBox(); g.computeBoundingSphere();
  g.userData.shared = true;
  cache.set(key, g);
  return g;
}

// профиль крыши вдоль длины (по Z): луч сверху вниз по оси вагона — для ходьбы по крыше
const _rc = new THREE.Raycaster(), _o = new THREE.Vector3(), _dn = new THREE.Vector3(0, -1, 0);
export function roofProfile(geo, step = 0.25) {
  if (geo.userData.roof) return geo.userData.roof;
  const bb = geo.boundingBox, z0 = bb.min.z, n = Math.ceil((bb.max.z - z0) / step) + 1, h = new Float32Array(n);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
  for (let k = 0; k < n; k++) {
    let best = 0;
    for (const x of [-0.4, 0, 0.4]) {
      _rc.set(_o.set(x, bb.max.y + 2, z0 + k * step), _dn);
      const hit = _rc.intersectObject(mesh, false)[0];
      if (hit && hit.point.y > best) best = hit.point.y;
    }
    h[k] = best;
  }
  const r = { z0, step, h, at(z) { const k = Math.round((z - z0) / step); return h[Math.max(0, Math.min(n - 1, k))]; } };
  geo.userData.roof = r;
  return r;
}
