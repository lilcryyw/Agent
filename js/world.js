import * as THREE from '../vendor/three.module.min.js';
import {
  rngOf, R, RI, pick, wpick, trackX, frameAt, worldPos, M, C, P, B, boxGeo, boxAt, cylGeo, merge, shared,
  gableGeo, QuadBatch, ribbon, sign, disposeTree,
} from './util.js';
import { NAMES_F, NAMES_N, NAMES_PL, NAMES_M, MOD, SETTLEMENT_NAMES, FACTORIES } from './data.js';
import { makeWreck, makeTank, makeCar } from './models.js';
import { packGeo, PACK_MAT } from './packs.js';
import { Char } from './chars.js';

export const CHUNK = 100;
const AHEAD = 6, BEHIND = 2;
const HALF_PI = Math.PI / 2;

// плотность зомби по типу местности
export const ZONE_DENSITY = { forest: 0.25, field: 0.18, village: 0.6, dacha: 0.5, town: 1.0, industrial: 0.75, swamp: 0.35, settlement: 0 };
export const ZONE_NAMES = { forest: 'Лес', field: 'Поля', village: 'Деревня', dacha: 'Дачи', town: 'Город', industrial: 'Промзона', swamp: 'Болота', settlement: 'Поселение' };

const WIN = [[0x1d2a33, 6], [0x0b0f12, 3], [0x2c3c46, 3], [0x5a4630, 1.2], [0x6e7f86, 1], [0xffc864, 0.22]];
const ROOF_T = [0x9a4a3a, 0x4f7a5a, 0x8a8f96, 0xffffff, 0x3f5f8f, 0x6a6a6a];

// ---------- общие геометрии
const G = {
  trunk: shared(new THREE.CylinderGeometry(0.6, 1, 1, 6).translate(0, 0.5, 0)),
  ico: shared(new THREE.IcosahedronGeometry(1, 2)),
  cone: shared(new THREE.ConeGeometry(1, 1, 12).translate(0, 0.5, 0)),
  sleeper: shared(new THREE.BoxGeometry(2.75, 0.16, 0.26)),
  pole: null, pylon: null,
};
G.pole = shared(merge([cylGeo(0.12, 0.15, 7.5, 6).translate(0, 3.75, 0), boxAt(1.7, 0.12, 0.12, 0, 7.1, 0, 1)]));
G.pylon = shared(merge([boxAt(0.5, 24, 0.5, 0, 12, 0, 3), boxAt(9, 0.35, 0.35, 0, 20, 0, 3), boxAt(6, 0.35, 0.35, 0, 23, 0, 3),
  boxAt(0.3, 9, 0.3, -1.2, 4.5, 0, 3, 0), boxAt(0.3, 9, 0.3, 1.2, 4.5, 0, 3, 0)]));
const trunkMat = new THREE.MeshLambertMaterial({ color: 0xffffff });
const crownMat = new THREE.MeshLambertMaterial({ color: 0xffffff });
const wireMat = new THREE.LineBasicMaterial({ color: 0x1e1e1e });
const _m4 = new THREE.Matrix4(), _q = new THREE.Quaternion(), _v = new THREE.Vector3(), _s = new THREE.Vector3(), _col = new THREE.Color(), _up = new THREE.Vector3(0, 1, 0);
const _fr = {};

export class World {
  constructor(scene, seed) {
    this.scene = scene; this.seed = seed;
    this.stations = []; this.regions = []; this.seasons = []; this._lastSettle = 0;
    this.chunks = new Map(); this.loot = new Map(); this.obstacles = new Map();
    this.nameCount = new Map(); this.looted = new Set(); this.cleared = new Set();
    this.buildB();
  }

  // ---------- последовательности: станции, участки, сезоны
  ensure(upTo) {
    while (!this.stations.length || this.stations[this.stations.length - 1].s < upTo) this._genStation();
    while (!this.regions.length || this.regions[this.regions.length - 1].s1 < upTo) this._genRegion();
    while (!this.seasons.length || this.seasons[this.seasons.length - 1].s1 < upTo) this._genSeason();
  }
  _genStation() {
    const k = this.stations.length, r = rngOf(this.seed, 101, k);
    let s, kind;
    if (k === 0) { s = 60; kind = 'depot'; }
    else {
      const p = this.stations[k - 1];
      s = p.s + (k === 1 ? 1500 + r() * 800 : 1900 + r() * 3300);
      const since = k - this._lastSettle;
      if (k === 1) kind = 'station';
      else if (k === 2 || since >= 4 || (since >= 2 && r() < 0.3)) kind = 'settlement';
      else kind = wpick(r, [['halt', 3], ['station', 3], ['town', 2]]);
    }
    if (kind === 'settlement' || kind === 'depot') this._lastSettle = k;
    let name;
    if (kind === 'halt') name = r() < 0.6 ? `Платформа ${Math.round(s / 1000) + 117} км` : `Разъезд ${RI(r, 3, 79)}`;
    else if (kind === 'depot') name = 'Узловая';
    else name = this._townName(r, kind);
    const c = this.nameCount.get(name) || 0; this.nameCount.set(name, c + 1);
    if (c > 0) name += '-' + (c + 1);
    const st = { k, s, kind, side: r() < 0.5 ? 1 : -1, name, len: kind === 'halt' ? 90 : kind === 'town' ? 240 : 190 };
    if (kind === 'settlement') st.settle = pick(r, SETTLEMENT_NAMES);
    if (kind === 'depot') st.settle = 'Депо';
    if (kind !== 'halt') {
      st.wagons = []; const n = RI(r, 1, 5); let ws = st.s - 170;
      for (let i = 0; i < n && ws < st.s + 160; i++) { ws += R(r, 16, 70); st.wagons.push({ s: ws, tank: r() < 0.3, id: `w${k}.${i}`, tint: r() }); }
    }
    this.stations.push(st);
  }
  _townName(r, kind) {
    const g = kind === 'town' ? 'm' : wpick(r, [['f', 3], ['n', 3], ['pl', 2], ['m', 1]]);
    let base = g === 'm' ? pick(r, NAMES_M) : g === 'f' ? pick(r, NAMES_F) : g === 'n' ? pick(r, NAMES_N) : pick(r, NAMES_PL);
    if (g !== 'm' && r() < 0.3 && !base.includes(' ')) base = pick(r, MOD[g]) + ' ' + base;
    if (g === 'm' && r() < 0.35) base += pick(r, ['-Сортировочный', '-Пассажирский', '-Товарный', '-Северный', '-Южный']);
    return base;
  }
  _genRegion() {
    const j = this.regions.length, r = rngOf(this.seed, 202, j);
    const s0 = j ? this.regions[j - 1].s1 : 0, prev = j ? this.regions[j - 1].type : 'village';
    let type;
    do type = wpick(r, [['forest', 3.2], ['field', 2.4], ['village', 2], ['dacha', 1], ['industrial', 0.8], ['swamp', 0.6], ['town', 0.5]]);
    while (type === prev);
    this.regions.push({ j, s0, s1: s0 + R(r, 600, 2400), type, birch: r(), conif: r() });
  }
  _genSeason() {
    const j = this.seasons.length, r = rngOf(this.seed, 303, j);
    const s0 = j ? this.seasons[j - 1].s1 : 0, prev = j ? this.seasons[j - 1].season : null;
    let season = j === 0 ? 'summer' : pick(r, ['summer', 'autumn', 'winter'].filter((x) => x !== prev));
    this.seasons.push({ s0, s1: s0 + R(r, 12000, 24000), season });
  }
  _seg(arr, s) {
    let lo = 0, hi = arr.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (arr[mid].s0 <= s) lo = mid; else hi = mid - 1; }
    return arr[lo];
  }
  regionAt(s) { this.ensure(s + 6000); return this._seg(this.regions, Math.max(0, s)); }
  seasonAt(s) { this.ensure(s + 6000); return this._seg(this.seasons, Math.max(0, s)).season; }
  nearestStation(s) {
    this.ensure(s + 6000);
    const a = this.stations; let lo = 0, hi = a.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (a[mid].s <= s) lo = mid; else hi = mid - 1; }
    const b = a[Math.min(lo + 1, a.length - 1)];
    return Math.abs(a[lo].s - s) < Math.abs(b.s - s) ? a[lo] : b;
  }
  nextStations(s, n) {
    this.ensure(s + 30000);
    return this.stations.filter((st) => st.s > s - 40).slice(0, n);
  }
  zoneAt(s) {
    const st = this.nearestStation(s), dd = Math.abs(st.s - s);
    if ((st.kind === 'settlement' || st.kind === 'depot') && dd < 230) return 'settlement';
    if (st.kind === 'town' && dd < 600) return 'town';
    if (st.kind === 'station' && dd < 330) return st.k % 2 ? 'village' : 'town';
    if (st.kind === 'halt' && dd < 120) { const t = this.regionAt(s).type; return t === 'town' || t === 'industrial' ? t : 'village'; }
    return this.regionAt(s).type;
  }

  // ---------- подгрузка участков вокруг поезда
  update(s) {
    const c = Math.floor(s / CHUNK);
    for (let i = c - BEHIND; i <= c + AHEAD; i++) if (i >= -1 && !this.chunks.has(i)) { this._build(i); break; }
    for (const [i, ch] of this.chunks) if (i < c - BEHIND - 1 || i > c + AHEAD + 1) this._drop(i, ch);
  }
  prime(s) { const c = Math.floor(s / CHUNK); for (let i = c - BEHIND; i <= c + AHEAD; i++) if (i >= -1 && !this.chunks.has(i)) this._build(i); }
  clear() { for (const [i, ch] of this.chunks) this._drop(i, ch); }
  _drop(i, ch) {
    this.scene.remove(ch.g); disposeTree(ch.g);
    for (const L of ch.loot) this.loot.delete(L.id);
    for (const o of ch.obs) this.obstacles.delete(o.id);
    this.chunks.delete(i);
  }
  // вытолкнуть точку из построек (в координатах пути)
  collide(s, d, rad = 0.4) {
    const ch = this.chunks.get(Math.floor(s / CHUNK)), out = { s, d, hit: false };
    for (const c of [ch, this.chunks.get(Math.floor(s / CHUNK) - 1), this.chunks.get(Math.floor(s / CHUNK) + 1)]) {
      if (!c) continue;
      for (const b of c.solids) {
        if (out.s > b[0] - rad && out.s < b[1] + rad && out.d > b[2] - rad && out.d < b[3] + rad) {
          const e = [out.s - (b[0] - rad), b[1] + rad - out.s, out.d - (b[2] - rad), b[3] + rad - out.d];
          const m = Math.min(...e), i = e.indexOf(m);
          if (i === 0) out.s = b[0] - rad; else if (i === 1) out.s = b[1] + rad; else if (i === 2) out.d = b[2] - rad; else out.d = b[3] + rad;
          out.hit = true;
        }
      }
    }
    return out;
  }
  removeObstacle(o) { this.cleared.add(o.id); this.obstacles.delete(o.id); o.mesh.parent && o.mesh.parent.remove(o.mesh); disposeTree(o.mesh); }

  _build(ci) {
    const s0 = ci * CHUNK, s1 = s0 + CHUNK, r = rngOf(this.seed, 404, ci);
    this.ensure(s1 + 6000);
    const O = new THREE.Vector3(trackX(s0), 0, -s0);
    const g = new THREE.Group(); g.position.copy(O);
    const ctx = { ci, s0, s1, r, O, g, zone: this.zoneAt(s0 + 50), season: this.seasonAt(s0 + 50), region: this.regionAt(s0 + 50),
      occ: [], bands: [], li: 0, loot: [], obs: [], solids: [] };
    ctx.bands.push([-8, 8]);
    this._ground(ctx);
    this._trackAt(ctx, 0, s0, s1);
    this._poles(ctx);
    const sts = this.stations.filter((st) => st.s > s0 - 400 && st.s < s1 + 400);
    ctx.st = sts.find((st) => Math.abs(st.s - (s0 + 50)) < st.len / 2 + 80) || null;
    for (const st of sts) this._station(ctx, st);
    this._layout(ctx);
    this._extras(ctx);
    this._trees(ctx);
    g.traverse((o) => { if (o.isMesh && !o.isInstancedMesh) { o.receiveShadow = true; o.castShadow = !o.userData.flat; } });
    this.scene.add(g);
    this.chunks.set(ci, { g, loot: ctx.loot, obs: ctx.obs, solids: ctx.solids });
  }

  // ---------- размещение
  place(ctx, obj, s, d, yawOff = 0, h = 0) {
    frameAt(s, _fr);
    obj.position.set(_fr.x + _fr.nx * d - ctx.O.x, h, _fr.z + _fr.nz * d - ctx.O.z);
    obj.rotation.y = _fr.yaw + yawOff; ctx.g.add(obj);
  }
  occupy(ctx, s, d, w, dep) { ctx.occ.push([s - w / 2 - 1, s + w / 2 + 1, d - dep / 2 - 1, d + dep / 2 + 1]); }
  regLoot(ctx, b, s, d, sgn) {
    const id = `${ctx.ci}.${ctx.li++}`;
    const fp = worldPos(s, d - sgn * (b.d / 2 + 1.2));
    const L = { id, type: b.loot, label: b.label, s, d, x: fp.x, z: fp.z };
    ctx.loot.push(L); this.loot.set(id, L);
  }
  // ряд построек вдоль пути
  row(ctx, sgn, dNear, types, gapMin, gapMax, sFrom = ctx.s0, sTo = ctx.s1) {
    const r = ctx.r; let s = sFrom + R(r, 0, gapMax);
    while (s < sTo) {
      const key = wpick(r, types);
      const b = this.B[key](r, ctx);
      const sc = s + b.w / 2;
      if (sc >= sTo) { disposeTree(b.g); break; }
      this.put(ctx, b, sc, sgn * (dNear + b.d / 2), sgn);
      s += b.w + R(r, gapMin, gapMax);
    }
  }
  put(ctx, b, s, d, sgn) {
    this.place(ctx, b.g, s, d, -sgn * HALF_PI);
    this.occupy(ctx, s, d, b.w, b.d);
    if (b.d > 1.5 && b.w > 1.5) ctx.solids.push([s - b.w / 2, s + b.w / 2, d - b.d / 2, d + b.d / 2]);
    if (b.loot) this.regLoot(ctx, b, s, d, sgn);
  }
  one(ctx, sgn, dNear, key) {
    const b = this.B[key](ctx.r, ctx);
    this.put(ctx, b, R(ctx.r, ctx.s0 + b.w / 2, ctx.s1 - b.w / 2), sgn * (dNear + b.d / 2), sgn);
  }

  // ---------- земля, путь, столбы
  _ground(ctx) {
    const se = ctx.season;
    const tex = se === 'winter' ? 'snow_02' : se === 'autumn' ? 'withered_grass' : 'sparse_grass';
    let tint = se === 'winter' ? 0xf4f8ff : 0xffffff;
    if (ctx.zone === 'swamp' && se !== 'winter') tint = 0xa8b498;
    const geo = ribbon(ctx.s0, ctx.s1, 10, [[-280, 0], [-12, 0], [12, 0], [280, 0]], ctx.O, 7, 7, ctx.s0 % 700);
    const gm = new THREE.Mesh(geo, M(tex, tint)); gm.userData.flat = true; ctx.g.add(gm);
  }
  _trackAt(ctx, off, sA, sB) {
    if (sB <= sA) return;
    const win = ctx.season === 'winter';
    const bal = ribbon(sA, sB, 5, [[off - 3.4, 0.03], [off - 1.9, 0.4], [off + 1.9, 0.4], [off + 3.4, 0.03]], ctx.O, 2.5, 2.5, sA % 250);
    const bm = new THREE.Mesh(bal, M('gravel_floor_02', win ? 0xdadfe4 : 0xa8a49c)); bm.userData.flat = true; ctx.g.add(bm);
    const n = Math.floor((sB - sA) / 0.55);
    const im = new THREE.InstancedMesh(G.sleeper, M('rough_wood', 0x6a5a4a), n);
    for (let i = 0; i < n; i++) {
      frameAt(sA + i * 0.55 + 0.27, _fr);
      _v.set(_fr.x + _fr.nx * off - ctx.O.x, 0.44, _fr.z + _fr.nz * off - ctx.O.z);
      _q.setFromAxisAngle(_up, _fr.yaw); _m4.compose(_v, _q, _s.set(1, 1, 1)); im.setMatrixAt(i, _m4);
    }
    im.receiveShadow = true; ctx.g.add(im);
    const rm = P(0x8d9298, 90);
    for (const c of [-0.795, 0.795]) {
      const rg = ribbon(sA, sB, 4, [[off + c - 0.036, 0.5], [off + c - 0.036, 0.64], [off + c + 0.036, 0.64], [off + c + 0.036, 0.5]], ctx.O);
      ctx.g.add(new THREE.Mesh(rg, rm));
    }
  }
  _poles(ctx) {
    const side = -1, mat = C(0x4a3a2c);
    const pts = [];
    for (let s = ctx.s0; s < ctx.s1; s += 50) {
      const m = new THREE.Mesh(G.pole, mat); this.place(ctx, m, s, side * 7.5, 0); ctx.occ.push([s - 1, s + 1, side * 7.5 - 1, side * 7.5 + 1]);
      const a = worldPos(s, side * 7.5).sub(ctx.O), b = worldPos(s + 50, side * 7.5).sub(ctx.O);
      for (const k of [-0.7, 0, 0.7]) {
        frameAt(s, _fr);
        for (let i = 0; i < 8; i++) {
          const t0 = i / 8, t1 = (i + 1) / 8;
          const y0 = 7.15 - Math.sin(t0 * Math.PI) * 0.7, y1 = 7.15 - Math.sin(t1 * Math.PI) * 0.7;
          pts.push(a.x + (b.x - a.x) * t0 + _fr.nx * k, y0, a.z + (b.z - a.z) * t0 + _fr.nz * k,
            a.x + (b.x - a.x) * t1 + _fr.nx * k, y1, a.z + (b.z - a.z) * t1 + _fr.nz * k);
        }
      }
    }
    const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    ctx.g.add(new THREE.LineSegments(lg, wireMat));
    // километровый столбик
    const km = Math.ceil(ctx.s0 / 1000) * 1000;
    if (km < ctx.s1) {
      const post = new THREE.Group();
      post.add(new THREE.Mesh(boxAt(0.18, 1.3, 0.18, 0, 0.65, 0, 1), C(0xf2f2f2)));
      const sg = sign(String(km / 1000 + 117), 0.5, 0.3, '#ffffff', '#111111', false); sg.position.set(0, 1.1, 0.1); post.add(sg);
      this.place(ctx, post, km, 4.2, 0);
    }
  }

  // ---------- станции
  _station(ctx, st) {
    const sgn = st.side, a = Math.max(ctx.s0, st.s - st.len / 2), b = Math.min(ctx.s1, st.s + st.len / 2);
    if (b > a) {
      const cross = sgn > 0 ? [[1.95, 0], [1.95, 1.1], [6.5, 1.1], [6.5, 0]] : [[-6.5, 0], [-6.5, 1.1], [-1.95, 1.1], [-1.95, 0]];
      ctx.g.add(new THREE.Mesh(ribbon(a, b, 5, cross, ctx.O, 3, 3, a % 300), M('grey_plaster', 0xb8b4ac)));
      const edge = sgn > 0 ? [[1.95, 1.106], [2.3, 1.106]] : [[-2.3, 1.106], [-1.95, 1.106]];
      ctx.g.add(new THREE.Mesh(ribbon(a, b, 5, edge, ctx.O), C(0xe8d34a)));
      ctx.occ.push([a, b, Math.min(sgn * 1.9, sgn * 7), Math.max(sgn * 1.9, sgn * 7)]);
      // фонари на платформе
      for (let s = Math.ceil(a / 30) * 30; s < b; s += 30) {
        const l = new THREE.Group();
        l.add(new THREE.Mesh(boxAt(0.12, 4.5, 0.12, 0, 3.35, 0, 1), C(0x555a5e)));
        l.add(new THREE.Mesh(boxAt(0.8, 0.12, 0.25, -0.35, 5.6, 0, 1), C(0x555a5e)));
        this.place(ctx, l, s, sgn * 5.8, 0);
      }
      // таблички с названием на концах
      for (const e of [st.s - st.len / 2 + 12, st.s + st.len / 2 - 12]) if (e >= ctx.s0 && e < ctx.s1) {
        const t = new THREE.Group();
        t.add(new THREE.Mesh(merge([boxAt(0.1, 2.6, 0.1, -1.5, 2.4, 0, 1), boxAt(0.1, 2.6, 0.1, 1.5, 2.4, 0, 1)]), C(0x666666)));
        const sg = sign(st.name, 3.4, 0.7, '#1f4e8c', '#ffffff'); sg.position.y = 3.4; t.add(sg);
        const sg2 = sign(st.name, 3.4, 0.7, '#1f4e8c', '#ffffff'); sg2.position.y = 3.4; sg2.rotation.y = Math.PI; t.add(sg2);
        this.place(ctx, t, e, sgn * 4.2, 0);
      }
    }
    // запасной путь с брошенными вагонами
    if (st.wagons) {
      const off = -sgn * 5.3;
      this._trackAt(ctx, off, Math.max(ctx.s0, st.s - 190), Math.min(ctx.s1, st.s + 190));
      if (st.s + 190 > ctx.s0 && st.s - 190 < ctx.s1) ctx.bands.push([Math.min(off - 3, off + 3), Math.max(off - 3, off + 3)]);
      for (const w of st.wagons) if (w.s >= ctx.s0 && w.s < ctx.s1) {
        const wr = rngOf(this.seed, 505, st.k, w.s | 0);
        const m = w.tank ? makeTank(wr) : makeWreck(wr);
        this.place(ctx, m.g, w.s, off, 0, 0.64);
        if (wr() < 0.15 && !w.tank) m.g.rotation.z = 0.05;
        const fp = worldPos(w.s, off + sgn * 2.2);
        const L = { id: w.id, type: w.tank ? 'wagon_tank' : 'wagon_box', label: w.tank ? 'Брошенная цистерна' : m.label, s: w.s, d: off, x: fp.x, z: fp.z };
        ctx.loot.push(L); this.loot.set(L.id, L);
      }
    }
    if (st.s < ctx.s0 || st.s >= ctx.s1) return;
    // вокзал или касса
    if (st.kind === 'halt') {
      const b = this.B.booth(ctx.r); this.put(ctx, b, st.s + 8, sgn * (8 + b.d / 2), sgn);
    } else {
      const b = this.B.stationHouse(ctx.r, ctx, st); this.put(ctx, b, st.s, sgn * (9 + b.d / 2), sgn);
    }
    if (st.kind === 'depot') {
      const h = this.B.depot(ctx.r); this.put(ctx, h, st.s - 40, sgn * (10 + h.d / 2), sgn);
      const wt = this.B.waterTower(ctx.r); this.put(ctx, wt, st.s + 32, sgn * (12 + wt.d / 2), sgn);
    }
  }

  // ---------- застройка по типу местности
  _layout(ctx) {
    const z = ctx.zone, r = ctx.r, st = ctx.st;
    for (const sgn of [-1, 1]) {
      let base = 11;
      if (st && st.side === sgn) base += 18;
      if (st && st.wagons && st.side === -sgn) base += 5;
      switch (z) {
        case 'village':
          this.road(ctx, sgn, base + 12, 4.5, 'gravel_floor_02', 0x9a8a70);
          this.row(ctx, sgn, base + 17, [['izba', 10], ['shop', 0.7], ['ruins', 1], ['church', 0.35], ['garages', 0.4], ['busStop', 0.5], ['kiosk', 0.3]], 3, 12);
          if (r() < 0.5) this.row(ctx, sgn, base + 52, [['izba', 6], ['dacha', 2], ['ruins', 1], ['farm', 0.3]], 4, 16);
          break;
        case 'dacha':
          this.row(ctx, sgn, base + 3, [['dacha', 10], ['greenhouse', 2]], 2, 6);
          this.road(ctx, sgn, base + 15, 3.5, 'gravel_floor_02', 0x9a8a70);
          this.row(ctx, sgn, base + 20, [['dacha', 10], ['izba', 1], ['greenhouse', 1]], 2, 6);
          break;
        case 'town':
          this.road(ctx, sgn, base + 10, 9, 'worn_asphalt', 0x9a9a9a);
          this.row(ctx, sgn, base + 21, [['shop', 4], ['kiosk', 1.5], ['khrush', 3], ['brick', 1.5], ['police', 0.5], ['hospital', 0.4],
            ['school', 0.5], ['azs', 0.4], ['busStop', 0.6], ['lenin', 0.25], ['church', 0.2], ['ruins', 0.4]], 4, 14);
          this.row(ctx, sgn, base + 58, [['khrush', 4], ['panel9', 3], ['garages', 1.5], ['brick', 1]], 8, 20);
          if (r() < 0.4) this.row(ctx, sgn, base + 115, [['panel9', 2], ['factory', 1], ['garages', 1]], 10, 30);
          break;
        case 'industrial':
          if (r() < 0.6) this.fence(ctx, sgn, base + 2);
          this.row(ctx, sgn, base + 7, [['factory', 3], ['garages', 2], ['silo', 1], ['warehouse', 2], ['transformer', 1], ['azs', 0.3]], 6, 20);
          this.row(ctx, sgn, base + 70, [['factory', 2], ['khrush', 1], ['silo', 1]], 10, 40);
          break;
        case 'field':
          if (r() < 0.07) this.one(ctx, sgn, base + R(r, 15, 70), 'farm');
          if (r() < 0.05) this.one(ctx, sgn, base + R(r, 15, 60), 'waterTower');
          if (r() < 0.025) this.one(ctx, sgn, base + R(r, 10, 40), 'military');
          if (r() < 0.04) this.one(ctx, sgn, base + R(r, 8, 30), 'car');
          if (r() < 0.5) this.hay(ctx, sgn, base);
          break;
        case 'forest':
          if (r() < 0.045) this.one(ctx, sgn, base + R(r, 8, 40), 'hut');
          if (r() < 0.025) this.one(ctx, sgn, base + R(r, 8, 30), 'military');
          if (r() < 0.03) this.one(ctx, sgn, base + R(r, 6, 30), 'car');
          break;
        case 'swamp':
          this.ponds(ctx, sgn, base);
          if (r() < 0.03) this.one(ctx, sgn, base + R(r, 10, 40), 'ruins');
          break;
        case 'settlement':
          this.settlement(ctx, sgn, base);
          break;
      }
    }
  }
  road(ctx, sgn, d, w, tex, tint) {
    const a = sgn * d, b = sgn * (d + w);
    const g = ribbon(ctx.s0, ctx.s1, 10, [[Math.min(a, b), 0.04], [Math.max(a, b), 0.04]], ctx.O, 6, 6, ctx.s0 % 600);
    ctx.g.add(new THREE.Mesh(g, M(tex, tint)));
    ctx.bands.push([Math.min(a, b) - 1, Math.max(a, b) + 1]);
    if (ctx.r() < 0.12) {
      const c = makeCar(ctx.r, ctx.r() < 0.4); this.put(ctx, c, R(ctx.r, ctx.s0 + 5, ctx.s1 - 5), sgn * (d + w / 2), sgn);
    }
  }
  fence(ctx, sgn, d) {
    const parts = [];
    for (let x = -50; x < 50; x += 3.1) if (ctx.r() > 0.06) parts.push(boxAt(3, 2.6, 0.22, x, 1.3, 0, 3));
    const m = new THREE.Mesh(merge(parts), M('concrete_panels', 0xc0bcb4));
    this.place(ctx, m, ctx.s0 + 50, sgn * d, HALF_PI);
  }
  hay(ctx, sgn, base) {
    const r = ctx.r, n = RI(r, 2, 8), win = ctx.season === 'winter';
    const gH = shared(merge([cylGeo(1.6, 1.7, 1.8, 10).translate(0, 0.9, 0), new THREE.SphereGeometry(1.6, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2).translate(0, 1.8, 0)]));
    gH.userData.shared = false;
    const pos = [];
    for (let i = 0; i < n; i++) pos.push([R(r, ctx.s0, ctx.s1), sgn * R(r, base + 10, 140)]);
    for (const [s, d] of pos) { const m = new THREE.Mesh(gH, C(win ? 0xe8ecef : 0xc8a858)); this.place(ctx, m, s, d, r() * 3); ctx.occ.push([s - 2, s + 2, d - 2, d + 2]); }
    if (sgn > 0 && r() < 0.35) {
      const pts = [];
      for (let s = Math.ceil(ctx.s0 / 80) * 80; s < ctx.s1; s += 80) {
        const m = new THREE.Mesh(G.pylon, C(0x6a6e72)); this.place(ctx, m, s, 75, 0);
        const a = worldPos(s, 75).sub(ctx.O), b = worldPos(s + 80, 75).sub(ctx.O);
        for (const [k, y] of [[-4.3, 19.8], [4.3, 19.8], [0, 22.8]]) for (let i = 0; i < 10; i++) {
          const t0 = i / 10, t1 = (i + 1) / 10;
          pts.push(a.x + (b.x - a.x) * t0 + k, y - Math.sin(t0 * Math.PI) * 2, a.z + (b.z - a.z) * t0,
            a.x + (b.x - a.x) * t1 + k, y - Math.sin(t1 * Math.PI) * 2, a.z + (b.z - a.z) * t1);
        }
      }
      const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      ctx.g.add(new THREE.LineSegments(lg, wireMat));
    }
  }
  ponds(ctx, sgn, base) {
    if (ctx.season === 'winter') return;
    const r = ctx.r, n = RI(r, 1, 3);
    for (let i = 0; i < n; i++) {
      const rad = R(r, 6, 22), s = R(r, ctx.s0, ctx.s1), d = sgn * R(r, base + rad, 120);
      const m = new THREE.Mesh(new THREE.CircleGeometry(rad, 14).rotateX(-HALF_PI), P(0x3a4a48, 100));
      m.scale.z = R(r, 0.5, 1); this.place(ctx, m, s, d, r() * 3, 0.06);
      ctx.occ.push([s - rad, s + rad, d - rad, d + rad]);
    }
  }
  settlement(ctx, sgn, base) {
    const r = ctx.r, wallD = base + 4;
    const parts = [];
    for (let x = -50; x < 50; x += 3.1) parts.push(boxAt(3, 3, 0.25, x, 1.5, 0, 3));
    this.place(ctx, new THREE.Mesh(merge(parts), M('concrete_panels', 0xb8b4aa)), ctx.s0 + 50, sgn * wallD, HALF_PI);
    // колючая проволока
    const wire = [];
    frameAt(ctx.s0, _fr);
    const a = worldPos(ctx.s0, sgn * wallD).sub(ctx.O), b = worldPos(ctx.s1, sgn * wallD).sub(ctx.O);
    for (let i = 0; i < 50; i++) {
      const t0 = i / 50, t1 = (i + 1) / 50;
      wire.push(a.x + (b.x - a.x) * t0, 3.2 + (i % 2) * 0.25, a.z + (b.z - a.z) * t0, a.x + (b.x - a.x) * t1, 3.2 + ((i + 1) % 2) * 0.25, a.z + (b.z - a.z) * t1);
    }
    const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(wire, 3));
    ctx.g.add(new THREE.LineSegments(lg, wireMat));
    // палатки, костры, люди
    const st = ctx.st;
    const inner0 = st && st.side === sgn ? 8 : 9;
    const tents = RI(r, 1, 3);
    for (let i = 0; i < tents; i++) {
      const t = this.B.tent(r); const s = R(r, ctx.s0 + 6, ctx.s1 - 6);
      if (st && st.side === sgn && Math.abs(s - st.s) < 25) continue;
      this.put(ctx, t, s, sgn * R(r, inner0 + 2, wallD - 4), sgn);
    }
    if (r() < 0.7) {
      const f = new THREE.Group();
      f.add(new THREE.Mesh(shared(new THREE.ConeGeometry(0.5, 1.1, 6).translate(0, 0.55, 0)), B(0xff8a2a)));
      f.add(new THREE.Mesh(boxAt(1.2, 0.18, 0.18, 0, 0.1, 0, 1), C(0x3a2a1a)));
      f.userData.fire = true;
      this.place(ctx, f, R(r, ctx.s0 + 10, ctx.s1 - 10), sgn * R(r, inner0 + 3, wallD - 3), 0);
      ctx.fires = (ctx.fires || 0) + 1;
    }
    const people = RI(r, 1, 4);
    for (let i = 0; i < people; i++) {
      const h = new Char(r() < 0.6 ? 'soldier' : 'woman', 'clean');
      h.mixer.setTime(r() * 3); h.mixer.update(0.01);
      this.place(ctx, h.root, R(r, ctx.s0 + 5, ctx.s1 - 5), sgn * R(r, 3, wallD - 2), R(r, -1, 1), st && st.side === sgn && Math.abs(st.s - ctx.s0 - 50) < st.len / 2 ? 1.1 : 0);
    }
    if (st && st.s >= ctx.s0 && st.s < ctx.s1 && st.side === sgn) {
      const banner = new THREE.Group();
      banner.add(new THREE.Mesh(merge([boxAt(0.2, 6, 0.2, -4, 3, 0, 1), boxAt(0.2, 6, 0.2, 4, 3, 0, 1)]), C(0x4a3a2a)));
      const sg = sign(`${st.settle === 'Депо' ? 'ДЕПО' : 'ПОСЕЛЕНИЕ'} «${st.settle === 'Депо' ? st.name.toUpperCase() : st.settle.toUpperCase()}»`, 8.2, 1.3, '#7a1f1a', '#f4e8c8');
      sg.position.y = 5.2; banner.add(sg);
      const sg2 = sign('ТОРГОВЛЯ · РЕМОНТ · НОЧЛЕГ', 8.2, 0.7, '#2a2a2a', '#f4d36a', false); sg2.position.y = 4.1; banner.add(sg2);
      this.place(ctx, banner, st.s + 20, sgn * 7.5, -sgn * HALF_PI);
      const tw = this.B.tower(r); this.place(ctx, tw, ctx.s0 + 8, sgn * (wallD - 2), 0);
    }
  }

  // ---------- переезды и завалы
  _extras(ctx) {
    const r = ctx.r, z = ctx.zone;
    const nearSt = this.stations.some((st) => Math.abs(st.s - (ctx.s0 + 50)) < st.len / 2 + 120);
    if (!nearSt && ['village', 'town', 'field', 'dacha', 'industrial'].includes(z) && r() < 0.13) {
      const sc = R(r, ctx.s0 + 20, ctx.s1 - 20);
      const road = new THREE.Group();
      road.add(new THREE.Mesh(boxAt(400, 0.06, 7, 0, 0.04, 0, 6), M('worn_asphalt', 0x8a8a8a)));
      road.add(new THREE.Mesh(boxAt(4.6, 0.22, 7, 0, 0.5, 0, 2), M('rough_wood', 0x5a4a3a)));
      for (const sx of [-1, 1]) {
        road.add(new THREE.Mesh(boxAt(0.25, 1.2, 0.25, sx * 7, 0.6, sx * 4, 1), C(0x333333)));
        const arm = new THREE.Mesh(boxAt(5, 0.14, 0.14, -sx * 2.5, 0, 0, 1), C(0xd02a2a)); arm.position.set(sx * 7, 1.1, sx * 4);
        if (r() < 0.5) arm.rotation.z = sx * 1.3; road.add(arm);
      }
      const sg = sign('ПЕРЕЕЗД', 1.4, 0.35, '#ffffff', '#c01818'); sg.position.set(-7.5, 2.0, -4); road.add(sg);
      this.place(ctx, road, sc, 0, 0);
      ctx.occ.push([sc - 5, sc + 5, -200, 200]);
      if (r() < 0.55) { const c = makeCar(r, r() < 0.4); this.put(ctx, c, sc + R(r, -2, 2), (r() < 0.5 ? 1 : -1) * R(r, 9, 40), 1); }
      if (ctx.s0 > 1500 && r() < 0.35) this.obstacle(ctx, sc, 'car');
    } else if (!nearSt && ctx.s0 > 1500 && z !== 'settlement' && r() < 0.022) {
      const type = ['forest', 'field', 'swamp'].includes(z) ? 'tree' : z === 'town' || z === 'industrial' ? 'barricade' : 'car';
      this.obstacle(ctx, R(r, ctx.s0 + 20, ctx.s1 - 20), type);
    }
  }
  obstacle(ctx, s, type) {
    const id = 'o' + ctx.ci;
    if (this.cleared.has(id)) return;
    const r = ctx.r, g = new THREE.Group();
    let label;
    if (type === 'tree') {
      label = 'Упавшее дерево';
      const t = new THREE.Mesh(packGeo(ctx.season === 'winter' ? 'PineTree_Snow_2' : 'PineTree_2'), PACK_MAT);
      t.scale.setScalar(3.6); t.rotation.set(0.3, 0, -HALF_PI); t.position.set(-6.5, 0.9, 0); t.castShadow = true; g.add(t);
      g.rotation.z = 0;
    } else if (type === 'car') {
      label = 'Машина на путях';
      const c = makeCar(r, r() < 0.5); g.add(c.g); c.g.children[0].rotation.y = HALF_PI + R(r, -0.5, 0.5);
    } else {
      label = 'Баррикада';
      const p = [];
      for (let i = 0; i < 6; i++) p.push(boxAt(R(r, 1.2, 2.5), R(r, 0.8, 1.6), R(r, 0.8, 1.4), R(r, -3, 3), 0.6, R(r, -0.6, 0.6), 1.5, r()));
      g.add(new THREE.Mesh(merge(p), M('concrete_panels', 0xa8a49c)));
      const tyre = shared(new THREE.TorusGeometry(0.4, 0.18, 6, 10).rotateX(HALF_PI));
      tyre.userData.shared = false;
      for (let i = 0; i < 5; i++) { const t = new THREE.Mesh(tyre, C(0x1a1a1a)); t.position.set(R(r, -2.5, 2.5), 0.6 + i * 0.36, R(r, -0.4, 0.4)); g.add(t); }
    }
    this.place(ctx, g, s, 0, 0, 0.4);
    const o = { id, s, type, label, mesh: g };
    ctx.obs.push(o); this.obstacles.set(id, o);
  }

  // ---------- деревья и растительность: рядом с путём — готовые модели (Quaternius Nature, CC0), вдали — упрощённые
  _trees(ctx) {
    const r = ctx.r, z = ctx.zone, se = ctx.season, reg = ctx.region, win = se === 'winter', aut = se === 'autumn';
    const counts = { forest: 300, field: 30, village: 55, dacha: 45, town: 28, industrial: 14, swamp: 70, settlement: 12 };
    let n = counts[z] || 30;
    const birchShare = z === 'swamp' ? 0.5 : 0.2 + reg.birch * 0.5;
    const trunks = [], icos = [], cones = [], inst = new Map();
    const v2 = (k) => RI(r, 1, k);               // на участок — свои варианты моделей
    const V = { birch: [v2(3), v2(3)], common: [v2(3), v2(3)], pine: [v2(3), v2(3)], willow: [v2(2)] };
    const put = (name, p, sc, rot = r() * 6.28, tint) => {
      const key = tint ? name + '|' + tint : name;
      if (!inst.has(key)) inst.set(key, { name, tint, list: [] });
      inst.get(key).list.push([p.x, p.y || 0, p.z, sc, rot]);
    };
    const NEAR = 65;
    let belt = z === 'field' && r() < 0.6 ? (r() < 0.5 ? 1 : -1) * R(r, 25, 90) : null;
    if (belt) n += 60;
    for (let i = 0, tries = 0; i < n && tries < n * 3; tries++) {
      const s = R(r, ctx.s0, ctx.s1);
      let d = belt && i >= n - 60 ? belt + R(r, -4, 4) : (r() < 0.5 ? -1 : 1) * (9 + Math.pow(r(), 0.8) * 230);
      if (ctx.bands.some((b) => d > b[0] && d < b[1])) continue;
      if (ctx.occ.some((o) => s > o[0] && s < o[1] && d > o[2] && d < o[3])) continue;
      i++;
      const p = worldPos(s, d).sub(ctx.O);
      const kind = z === 'swamp' && r() < 0.35 ? 'dead' : z === 'swamp' && r() < 0.3 ? 'willow' : r() < birchShare ? 'birch' : r() < 0.3 ? 'common' : 'pine';
      const sc = R(r, 0.8, 1.25);
      if (Math.abs(d) < NEAR) {
        const vi = pick(r, V[kind] || [1]);
        if (kind === 'birch') put(win ? 'BirchTree_Dead_' + (vi > 2 ? 2 : vi) : aut ? 'BirchTree_Autumn_' + vi : 'BirchTree_' + vi, p, sc * 3.0);
        else if (kind === 'common') put(win ? 'CommonTree_Dead_' + (vi > 2 ? 2 : vi) : aut ? 'CommonTree_Autumn_' + vi : 'CommonTree_' + vi, p, sc * 3.0);
        else if (kind === 'pine') put(win ? 'PineTree_Snow_' + vi : 'PineTree_' + vi, p, sc * 3.6);
        else if (kind === 'willow') put(win ? 'Willow_Dead_1' : aut ? 'Willow_Autumn_1' : 'Willow_' + vi, p, sc * 2.8);
        else put(pick(r, ['Willow_Dead_1', 'BirchTree_Dead_1', 'BirchTree_Dead_2', 'CommonTree_Dead_1']), p, sc * 2.8);
        continue;
      }
      // дальний план — простые формы
      if (kind === 'birch' || kind === 'common' || kind === 'willow') {
        const h = 8 * sc;
        trunks.push([p, 0.22 * sc, h, kind === 'birch' ? 0xe8e4d8 : 0x6a5040]);
        if (!win) icos.push([p, h * 0.68, 2.3 * sc, 3.4 * sc, aut ? (r() < 0.6 ? 0xe0a030 : 0xd07028) : kind === 'birch' ? 0x5f9a3a : 0x4f8a34]);
      } else if (kind === 'pine') {
        const h = 11 * sc;
        trunks.push([p, 0.25 * sc, 2.2, 0x6a4a32]);
        cones.push([p, 1.4, 2.8 * sc, h, win ? 0xc8d4d0 : 0x2f6a35]);
      } else trunks.push([p, 0.18 * sc, 6 * sc, 0x6a645a]);
    }
    // подлесок у пути: кусты, камни, трава, пни, брёвна, цветы
    const near = { forest: 70, field: 60, village: 40, dacha: 35, town: 14, industrial: 10, swamp: 55, settlement: 6 }[z] || 20;
    for (let i = 0, tries = 0; i < near && tries < near * 3; tries++) {
      const s = R(r, ctx.s0, ctx.s1), d = (r() < 0.5 ? -1 : 1) * R(r, 4.5, 45);
      if (Math.abs(d) < 8 && r() < 0.6) continue;
      if (ctx.bands.some((b) => d > b[0] && d < b[1]) && Math.abs(d) > 4) continue;
      if (ctx.occ.some((o) => s > o[0] && s < o[1] && d > o[2] && d < o[3])) continue;
      i++;
      const p = worldPos(s, d).sub(ctx.O), k = r();
      if (k < 0.32) put(win ? 'Bush_Snow_' + RI(r, 1, 2) : z !== 'town' && r() < 0.25 && !aut ? 'BushBerries_1' : 'Bush_' + RI(r, 1, 2), p, R(r, 1.6, 2.6), undefined, aut ? 0xe6b070 : undefined);
      else if (k < 0.5) put(win ? 'Rock_Snow_' + RI(r, 1, 2) : r() < 0.5 ? 'Rock_Moss_' + RI(r, 1, 3) : 'Rock_' + RI(r, 1, 2), p, R(r, 1.2, 3));
      else if (k < 0.85) { if (!win) put(z === 'field' && r() < 0.5 ? 'Wheat' : r() < 0.25 && !aut ? 'Flowers' : 'Grass' + (r() < 0.5 ? '' : '_2'), p, R(r, 1.2, 1.8), undefined, aut ? 0xd8b060 : undefined); }
      else if (z === 'forest' || z === 'swamp') put(win ? 'TreeStump_Snow' : r() < 0.5 ? 'TreeStump' : r() < 0.5 ? 'WoodLog_Moss' : 'WoodLog', p, R(r, 1.6, 2.4));
    }
    const _rq = new THREE.Quaternion();
    for (const { name, tint, list } of inst.values()) {
      const geo = packGeo(name, tint ? { tint } : {});
      const im = new THREE.InstancedMesh(geo, PACK_MAT, list.length);
      list.forEach(([x, y, zz, sc, rot], i) => { _rq.setFromAxisAngle(_up, rot); _m4.compose(_v.set(x, y, zz), _rq, _s.set(sc, sc, sc)); im.setMatrixAt(i, _m4); });
      im.castShadow = geo.boundingBox.max.y > 1.5; im.receiveShadow = true;
      im.computeBoundingSphere();
      ctx.g.add(im);
    }
    if (trunks.length) {
      const im = new THREE.InstancedMesh(G.trunk, trunkMat, trunks.length);
      trunks.forEach(([p, rad, h, col], i) => { _m4.makeScale(rad, h, rad).setPosition(p.x, 0, p.z); im.setMatrixAt(i, _m4); im.setColorAt(i, _col.set(col)); });
      ctx.g.add(im);
    }
    if (icos.length) {
      const im = new THREE.InstancedMesh(G.ico, crownMat, icos.length);
      icos.forEach(([p, y, w, h, col], i) => { _m4.makeScale(w, h, w).setPosition(p.x, y, p.z); im.setMatrixAt(i, _m4); im.setColorAt(i, _col.set(col)); });
      ctx.g.add(im);
    }
    if (cones.length) {
      const im = new THREE.InstancedMesh(G.cone, crownMat, cones.length);
      cones.forEach(([p, y, w, h, col], i) => { _m4.makeScale(w, h, w).setPosition(p.x, y, p.z); im.setMatrixAt(i, _m4); im.setColorAt(i, _col.set(col)); });
      ctx.g.add(im);
    }
  }

  // ---------- типы построек
  buildB() {
    const self = this;
    const winGrid = (qb, r, w, d, floors, fh, h0 = 0, o = {}) => {
      const sp = o.sp || 3.1, ww = o.ww || 1.25, wh = o.wh || 1.45;
      const cols = Math.max(1, Math.floor((w - 1.2) / sp)), x0 = -(cols - 1) * sp / 2;
      for (const f of o.back === false ? [1] : [1, -1]) for (let fl = o.skip ? 1 : 0; fl < floors; fl++) for (let c = 0; c < cols; c++) {
        const x = x0 + c * sp, y = h0 + fl * fh + fh * 0.55;
        if (o.frame) qb.front(x, y, f * (d / 2 + 0.02), ww / 2 + 0.12, wh / 2 + 0.12, f, o.frame);
        qb.front(x, y, f * (d / 2 + 0.04), ww / 2, wh / 2, f, wpick(r, WIN));
      }
    };
    const flatRoof = (w, d, h) => boxAt(w + 0.3, 0.45, d + 0.3, 0, h + 0.2, 0, 3);
    const mk = (parts) => { const g = new THREE.Group(); for (const p of parts) if (p) g.add(p); return g; };
    const mesh = (geo, mat) => new THREE.Mesh(geo, mat);
    const cap = (t) => t[0] + t.slice(1).toLowerCase();

    this.B = {
      izba(r, ctx, label = 'Изба', loot = 'house') {
        const w = R(r, 6, 8.5), d = R(r, 6, 7.5), h = R(r, 2.7, 3.2), painted = r() < 0.45;
        const tint = painted ? pick(r, [0x86a9c9, 0x96c48f, 0xd9c47e, 0xc99586, 0xbcbcbc, 0xa7c4b5]) : pick(r, [0xffffff, 0xdcc8b0, 0xb9a68e]);
        const rh = R(r, 1.8, 2.6), roofG = gableGeo(w, d, rh, 0.5); roofG.translate(0, h, 0);
        const qb = new QuadBatch(), frame = pick(r, [0xf2f2f2, 0x3d6fb5, 0x5f9a5a, 0xe0c040, 0xf2f2f2]);
        for (const x of [-w / 3, 0, w / 3]) { qb.front(x, 1.65, d / 2 + 0.02, 0.62, 0.75, 1, frame); qb.front(x, 1.65, d / 2 + 0.04, 0.48, 0.6, 1, wpick(r, WIN)); }
        qb.side(w / 2 + 0.03, 1.65, 0, 0.5, 0.6, 1, wpick(r, WIN)); qb.side(-w / 2 - 0.03, 1.65, 0, 0.5, 0.6, -1, wpick(r, WIN));
        const parts = [mesh(boxAt(w, h, d, 0, h / 2, 0, 2.5), M(painted ? 'wood_plank_wall' : 'wood_trunk_wall', tint)),
          mesh(roofG, M('corrugated', pick(r, ROOF_T))), mesh(boxAt(0.6, 1.6, 0.6, w * 0.25, h + rh * 0.55, -d * 0.15, 1), M('red_brick_03')), qb.mesh()];
        if (r() < 0.7) parts.push(mesh(merge([boxAt(w + 5, 1.7, 0.08, 0, 0.85, d / 2 + 4, 2), boxAt(0.08, 1.7, 4, -(w + 5) / 2, 0.85, d / 2 + 2, 2),
          boxAt(0.08, 1.7, 4, (w + 5) / 2, 0.85, d / 2 + 2, 2)]), M('wood_plank_wall', pick(r, [0xa89880, 0x7a8a6a, 0x8a7a6a, 0xb0a890]))));
        return { g: mk(parts), w: w + 5, d: d + 4, loot, label };
      },
      hut(r, ctx) { return self.B.izba(r, ctx, 'Охотничья избушка', 'house'); },
      dacha(r) {
        const w = R(r, 4, 6), d = R(r, 4, 5.5), h = R(r, 2.4, 2.8), rh = R(r, 1.6, 2.4);
        const roofG = gableGeo(w, d, rh, 0.35); roofG.translate(0, h, 0);
        const qb = new QuadBatch();
        qb.front(-w / 4, 1.5, d / 2 + 0.03, 0.5, 0.55, 1, wpick(r, WIN)); qb.front(w / 4, 1.2, d / 2 + 0.03, 0.4, 1.0, 1, 0x4a3a2a);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 2), M('wood_plank_wall', pick(r, [0xe9e4c9, 0x9ccbe0, 0xf0c27b, 0xb6d7a8, 0xe8a0a0, 0xd8d8d8]))),
          mesh(roofG, M('corrugated', pick(r, ROOF_T))), qb.mesh()]), w: w + 2, d: d + 2, loot: 'dacha', label: 'Дача' };
      },
      greenhouse(r) {
        const w = R(r, 3, 6);
        return { g: mk([mesh(boxAt(w, 2, 3, 0, 1, 0, 2), C(0xd8ecf4, { transparent: true, opacity: 0.35 }))]), w, d: 3 };
      },
      khrush(r) {
        const floors = r() < 0.15 ? 4 : 5, fh = 2.8, w = R(r, 24, 48), d = R(r, 11, 12.5), h = floors * fh;
        const tex = pick(r, ['concrete_panels', 'white_bricks', 'white_bricks', 'red_brick_03']);
        const tint = tex === 'concrete_panels' ? pick(r, [0xd8d8d0, 0xc8d0d8, 0xe0d8c0, 0xd0c0b0]) : pick(r, [0xffffff, 0xe8e2d4, 0xd8c8b8]);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, floors, fh);
        const extra = [flatRoof(w, d, h)], balc = [];
        const nEnt = Math.max(1, Math.floor(w / 12));
        for (let i = 0; i < nEnt; i++) {
          const x = -w / 2 + (i + 0.5) * w / nEnt;
          qb.front(x, 1.1, d / 2 + 0.06, 0.6, 1.05, 1, 0x3a2e26);
          extra.push(boxAt(2.2, 0.15, 1.4, x, 2.4, d / 2 + 0.7, 2));
        }
        const cols = Math.max(1, Math.floor((w - 1.2) / 3.1)), x0 = -(cols - 1) * 3.1 / 2;
        for (let fl = 1; fl < floors; fl++) for (let c = 0; c < cols; c++) if (r() < 0.35) balc.push(boxAt(2.2, 1.0, 0.9, x0 + c * 3.1, fl * fh + 0.5, d / 2 + 0.45, 2));
        const parts = [mesh(boxAt(w, h, d, 0, h / 2, 0, 4), M(tex, tint)), mesh(merge(extra), C(0x55524e)), qb.mesh()];
        if (balc.length) parts.push(mesh(merge(balc), M('grey_plaster', 0xa8a49a)));
        return { g: mk(parts), w, d: d + 1, loot: 'apartment', label: floors === 5 ? 'Пятиэтажка' : 'Хрущёвка' };
      },
      panel9(r) {
        const floors = pick(r, [9, 9, 9, 12, 14, 16]), fh = 2.8, w = R(r, 25, 55), d = R(r, 12, 14), h = floors * fh;
        const qb = new QuadBatch(); winGrid(qb, r, w, d, floors, fh, 0, { sp: 3.3 });
        const nEnt = Math.max(1, Math.floor(w / 18));
        for (let i = 0; i < nEnt; i++) qb.front(-w / 2 + (i + 0.5) * w / nEnt, 1.1, d / 2 + 0.06, 0.7, 1.05, 1, 0x2e2a28);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 4), M('concrete_panels', pick(r, [0xe0e0dc, 0xd0d8e0, 0xe8dcc8, 0xc8c8c0]))),
          mesh(merge([flatRoof(w, d, h), boxAt(4, 3, 4, w * 0.2, h + 1.5, 0, 3)]), C(0x55524e)), qb.mesh()]), w, d, loot: 'apartment', label: `${floors}-этажный дом` };
      },
      brick(r) {
        const floors = RI(r, 2, 3), fh = 3.1, w = R(r, 12, 24), d = R(r, 10, 12), h = floors * fh;
        const tex = pick(r, ['red_brick_03', 'yellow_plaster', 'grey_plaster', 'white_bricks']);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, floors, fh, 0, { frame: tex === 'yellow_plaster' ? 0xf4f0e4 : null });
        const roof = r() < 0.6 ? (() => { const g = gableGeo(w, d, 2.2, 0.4); g.translate(0, h, 0); return mesh(g, M('corrugated', pick(r, ROOF_T))); })() : mesh(flatRoof(w, d, h), C(0x55524e));
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(tex, pick(r, [0xffffff, 0xf0e8d8, 0xe0d8d0]))), roof, qb.mesh()]), w, d,
          loot: floors > 2 ? 'apartment' : 'house', label: floors === 2 ? 'Двухэтажный дом' : 'Трёхэтажный дом' };
      },
      shop(r) {
        const kind = wpick(r, [['food', 5], ['med', 1.5], ['hoz', 1.2], ['auto', 1], ['hunt', 0.45]]);
        const texts = { food: ['ПРОДУКТЫ', 'ГАСТРОНОМ', 'УНИВЕРСАМ', 'МАГАЗИН', 'ПРОДУКТЫ 24', 'ХЛЕБ', 'КУЛИНАРИЯ'], med: ['АПТЕКА'], hoz: ['ХОЗТОВАРЫ', 'СТРОЙМАТЕРИАЛЫ'], auto: ['АВТОЗАПЧАСТИ', 'ШИНОМОНТАЖ'], hunt: ['ОХОТА И РЫБАЛКА'] };
        const colors = { food: ['#c8302a', '#ffffff'], med: ['#ffffff', '#1a8a3a'], hoz: ['#e0a020', '#222222'], auto: ['#1f3a8c', '#ffffff'], hunt: ['#2f4a2a', '#e8e0b0'] };
        const text = pick(r, texts[kind]);
        const w = R(r, 9, 18), d = R(r, 9, 12), h = R(r, 3.4, 4.2);
        const qb = new QuadBatch(), shut = [];
        const n = Math.max(2, Math.floor(w / 3.2));
        for (let i = 0; i < n; i++) {
          const x = -w / 2 + (i + 0.5) * w / n;
          if (i === Math.floor(n / 2)) qb.front(x, 1.1, d / 2 + 0.04, 0.6, 1.05, 1, 0x2a2a2a);
          else if (r() < 0.35) shut.push(boxAt(w / n - 0.4, 2.2, 0.08, x, 1.3, d / 2 + 0.05, 2));
          else qb.front(x, 1.5, d / 2 + 0.04, w / n / 2 - 0.3, 0.95, 1, wpick(r, WIN));
        }
        const [bg, fg] = colors[kind];
        const sg = sign(text, Math.min(w - 1, text.length * 0.55 + 1.5), 0.9, bg, fg); sg.position.set(0, h - 0.55, d / 2 + 0.07);
        const parts = [mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(pick(r, ['grey_plaster', 'white_bricks', 'red_brick_03', 'yellow_plaster']), pick(r, [0xffffff, 0xe8e0d0, 0xd8e0e8]))),
          mesh(flatRoof(w, d, h), C(0x4a4844)), qb.mesh(), sg];
        if (shut.length) parts.push(mesh(merge(shut), M('shutter', 0xd0d0d0)));
        return { g: mk(parts), w, d, loot: 'shop_' + kind, label: kind === 'med' ? 'Аптека' : `Магазин «${cap(text)}»` };
      },
      kiosk(r) {
        const t = pick(r, ['ТАБАК', 'ПЕЧАТЬ', 'ЛАРЁК', 'ШАУРМА', 'ЦВЕТЫ', 'КВАС']);
        const sg = sign(t, 2.6, 0.5, '#e8e0c8', '#a01818'); sg.position.set(0, 2.45, 1.11);
        return { g: mk([mesh(boxAt(3, 2.7, 2.2, 0, 1.35, 0, 2), M('shutter', pick(r, [0x9ac0e0, 0xe0c080, 0xa0d0a0, 0xd8d8d8]))), sg]), w: 3.5, d: 2.5, loot: 'kiosk', label: 'Ларёк «' + cap(t) + '»' };
      },
      garages(r) {
        const n = RI(r, 4, 10), w = n * 3.2, d = 6, h = 2.6;
        const dA = [], dB = [];
        for (let i = 0; i < n; i++) (i % 2 ? dA : dB).push(boxAt(2.6, 2.1, 0.06, -w / 2 + 1.6 + i * 3.2, 1.05, d / 2 + 0.03, 2));
        const parts = [mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(pick(r, ['corrugated', 'red_brick_03', 'grey_plaster']), pick(r, [0xffffff, 0xc8c0b8]))),
          mesh(boxAt(w + 0.4, 0.2, d + 0.6, 0, h + 0.1, 0.1, 3), C(0x3a3836)), mesh(merge(dB), M('rusty_metal_02', pick(r, [0xffffff, 0x9aba94, 0x9aaac0])))];
        if (dA.length) parts.push(mesh(merge(dA), M('rusty_metal_02', pick(r, [0xc08a70, 0xd8d0b0, 0x88a088]))));
        return { g: mk(parts), w, d, loot: 'garage', label: 'Гаражи' };
      },
      factory(r) {
        const w = R(r, 28, 55), d = R(r, 16, 28), h = R(r, 8, 14);
        const tex = pick(r, ['red_brick_03', 'red_brick_03', 'concrete_panels']);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, 1, h, 0, { sp: 5, ww: 3.6, wh: 2.8 });
        qb.front(w * 0.3, 2.5, d / 2 + 0.05, 2.2, 2.5, 1, 0x3a3a36);
        const parts = [mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(tex, pick(r, [0xffffff, 0xd8c8b8, 0xb8a8a0]))), mesh(flatRoof(w, d, h), C(0x45423e)), qb.mesh()];
        if (r() < 0.65) { const ch = R(r, 25, 42); parts.push(mesh(cylGeo(1.1, 1.7, ch, 10).translate(-w * 0.3, ch / 2, -d * 0.25), M('red_brick_03', 0xd0b0a0))); }
        return { g: mk(parts), w, d, loot: 'factory', label: `Цех завода «${pick(r, FACTORIES)}»` };
      },
      warehouse(r) {
        const w = R(r, 20, 40), d = R(r, 12, 20), h = R(r, 5, 8);
        const roofG = gableGeo(w, d, 2, 0.3, 3); roofG.translate(0, h, 0);
        const qb = new QuadBatch(); qb.front(0, 2.2, d / 2 + 0.05, 2.5, 2.2, 1, 0x3a3836);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M('corrugated', pick(r, [0xffffff, 0xb0c0b0, 0xc0b0a0]))), mesh(roofG, M('corrugated', 0x8a8a8a)), qb.mesh()]),
          w, d, loot: 'factory', label: 'Склад' };
      },
      silo(r) {
        const n = RI(r, 3, 5), h = R(r, 18, 26), parts = [];
        for (let i = 0; i < n; i++) parts.push(cylGeo(3, 3, h, 14, 4).translate(-n * 3 + 3 + i * 6, h / 2, 0));
        parts.push(boxAt(6, h + 8, 6, n * 3 + 3, (h + 8) / 2, 0, 4));
        return { g: mk([mesh(merge(parts), M('grey_plaster', 0xc8c4bc))]), w: n * 6 + 8, d: 7, loot: 'factory', label: 'Элеватор' };
      },
      transformer(r) {
        const sg = sign('НЕ ВЛЕЗАЙ! УБЬЁТ!', 1.6, 0.4, '#f6f6f2', '#c01818'); sg.position.set(0, 2.2, 1.27);
        return { g: mk([mesh(boxAt(3, 3, 2.5, 0, 1.5, 0, 2), M('white_bricks', 0xe0e0e0)), sg]), w: 3.5, d: 3 };
      },
      church(r) {
        const w = R(r, 9, 11), d = R(r, 13, 17), h = R(r, 7, 9);
        const wall = M('grey_plaster', pick(r, [0xffffff, 0xf2e2a8, 0xbcd4ea, 0xc8e6cc]));
        const dome = P(pick(r, [0xd8a838, 0xd8a838, 0x2a4f9a, 0x2f7a4a]), 90), gold = P(0xe0b040, 100);
        const roofG = gableGeo(d, w, 2.2, 0.3); roofG.rotateY(HALF_PI); roofG.translate(0, h, 0);
        const g = mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), wall), mesh(roofG, M('corrugated', 0x5a7a6a)),
          mesh(cylGeo(2.3, 2.3, 3.4, 12).translate(0, h + 2.6, -d * 0.1), wall),
          mesh(boxAt(4.2, 13, 4.2, 0, 6.5, d / 2 + 2.1, 3), wall)]);
        const sph = shared(new THREE.SphereGeometry(1, 12, 9)); sph.userData.shared = false;
        const d1 = new THREE.Mesh(sph, dome); d1.scale.set(2.5, 3, 2.5); d1.position.set(0, h + 5.3, -d * 0.1); g.add(d1);
        const d2 = new THREE.Mesh(sph, dome); d2.scale.set(1.5, 1.9, 1.5); d2.position.set(0, 14.2, d / 2 + 2.1); g.add(d2);
        for (const [y, z] of [[h + 8.6, -d * 0.1], [16.4, d / 2 + 2.1]]) {
          g.add(mesh(merge([boxAt(0.12, 2, 0.12, 0, y, z, 1), boxAt(0.9, 0.1, 0.1, 0, y + 0.4, z, 1), boxAt(0.6, 0.08, 0.08, 0, y - 0.3, z, 1, 0.3)]), gold));
        }
        const qb = new QuadBatch(); qb.front(0, 2, d / 2 + 4.25, 0.8, 1.4, 1, 0x3a2a1a);
        for (const z of [-d / 4, d / 4]) { qb.side(w / 2 + 0.03, 4, z, 0.5, 1.1, 1, wpick(r, WIN)); qb.side(-w / 2 - 0.03, 4, z, 0.5, 1.1, -1, wpick(r, WIN)); }
        g.add(qb.mesh());
        return { g, w, d: d + 4.2, loot: 'church', label: 'Церковь' };
      },
      police(r) {
        const b = self.B.brick(r);
        const sg = sign('ПОЛИЦИЯ', 4, 0.8, '#1d4fa0', '#ffffff'); sg.position.set(0, 2.6, 5.6); b.g.add(sg);
        b.loot = 'police'; b.label = 'Отдел полиции'; return b;
      },
      hospital(r) {
        const floors = RI(r, 3, 4), w = R(r, 30, 45), d = 12, h = floors * 3.2;
        const qb = new QuadBatch(); winGrid(qb, r, w, d, floors, 3.2);
        const sg = sign('БОЛЬНИЦА', 6, 1.1, '#ffffff', '#c41a1a'); sg.position.set(0, h - 0.9, d / 2 + 0.08);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M('grey_plaster', 0xf4f4f0)), mesh(flatRoof(w, d, h), C(0x55524e)), qb.mesh(), sg]), w, d, loot: 'hospital', label: 'Больница' };
      },
      school(r) {
        const n = RI(r, 1, 40), w = R(r, 34, 50), d = 13, h = 3 * 3.4;
        const tex = pick(r, ['yellow_plaster', 'red_brick_03', 'white_bricks']);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, 3, 3.4, 0, { sp: 3.6, ww: 1.8, wh: 1.8 });
        const sg = sign('ШКОЛА №' + n, 5, 0.9, '#ffffff', '#1d3f80'); sg.position.set(0, h - 0.8, d / 2 + 0.08);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(tex)), mesh(flatRoof(w, d, h), C(0x55524e)), qb.mesh(), sg]), w, d, loot: 'school', label: 'Школа №' + n };
      },
      azs(r) {
        const col = pick(r, [0xc02a2a, 0x1f4e9c, 0x2a8a3a, 0xe0b020]);
        const posts = merge([[-4, -2.5], [4, -2.5], [-4, 2.5], [4, 2.5]].map(([x, z]) => boxAt(0.3, 5, 0.3, x, 2.5, z, 1)));
        const n = RI(r, 1, 99);
        const sgn = new THREE.Group(); sgn.add(mesh(boxAt(0.25, 5, 0.25, 0, 2.5, 0, 1), C(0x555555)));
        const sg = sign('АЗС №' + n, 2.6, 0.9, '#' + col.toString(16).padStart(6, '0'), '#ffffff'); sg.position.y = 5; sgn.add(sg); sgn.position.set(6.5, 0, 5);
        return { g: mk([mesh(boxAt(10, 0.6, 7, 0, 5.2, 0, 2), C(col)), mesh(posts, C(0xd8d8d8)),
          mesh(merge([boxAt(0.8, 1.6, 0.5, -2, 0.8, 0, 1), boxAt(0.8, 1.6, 0.5, 2, 0.8, 0, 1)]), C(0xe0e0e0)),
          mesh(boxAt(6, 3.2, 5, 0, 1.6, -7, 2), M('white_bricks')), sgn]), w: 14, d: 15, loot: 'azs', label: 'АЗС №' + n };
      },
      military(r) {
        const bags = [];
        for (let i = 0; i < 8; i++) bags.push(boxAt(1.3, 0.5, 0.6, -5 + i * 1.3, 0.25, 6, 1), boxAt(1.3, 0.5, 0.6, -4.4 + i * 1.3, 0.75, 6, 1));
        const g = mk([mesh(merge(bags), C(0x9a8a62))]);
        for (const x of [-4, 3]) { const t = self.B.tent(r); t.g.position.set(x, 0, -1); g.add(t.g); }
        const btr = new THREE.Group();
        btr.add(mesh(boxAt(2.8, 1.5, 7, 0, 1.3, 0, 2), C(0x55603a)));
        btr.add(mesh(cylGeo(0.6, 0.7, 0.6, 8).translate(0, 2.3, -1), C(0x55603a)));
        btr.add(mesh(shared(new THREE.CylinderGeometry(0.06, 0.06, 2, 5).rotateX(HALF_PI).translate(0, 2.35, -2.5)), C(0x222222)));
        const wg = new THREE.CylinderGeometry(0.55, 0.55, 0.4, 10).rotateZ(HALF_PI);
        btr.add(mesh(merge([-2.6, -0.9, 0.9, 2.6].flatMap((z) => [wg.clone().translate(-1.45, 0.55, z), wg.clone().translate(1.45, 0.55, z)])), C(0x1a1a1a)));
        wg.dispose();
        btr.position.set(R(r, -3, 3), 0, -7); btr.rotation.y = R(r, -1, 1); g.add(btr);
        const sg = sign('СТОЙ! КПП', 2.4, 0.6, '#c01818', '#ffffff'); sg.position.set(-6, 1.6, 6.4); g.add(sg);
        return { g, w: 16, d: 16, loot: 'military', label: 'Военный блокпост' };
      },
      tent(r) {
        const t = gableGeo(3.4, 4.5, 2.3, 0.1, 2); t.rotateY(HALF_PI);
        return { g: mk([mesh(t, C(pick(r, [0x5a6a3a, 0x4a5a3a, 0x6a6a4a, 0x3a4a5a])))]), w: 4.5, d: 3.6 };
      },
      tower(r) {
        const legs = merge([[-1.2, -1.2], [1.2, -1.2], [-1.2, 1.2], [1.2, 1.2]].map(([x, z]) => boxAt(0.2, 6, 0.2, x, 3, z, 1)));
        return mk([mesh(legs, C(0x4a3a2a)), mesh(merge([boxAt(3.2, 0.2, 3.2, 0, 6, 0, 1), boxAt(3.2, 1.0, 0.1, 0, 6.6, 1.55, 1), boxAt(3.2, 1.0, 0.1, 0, 6.6, -1.55, 1)]), M('wood_plank_wall', 0x9a8a70)),
          mesh((() => { const g = gableGeo(3.2, 3.2, 1, 0.3); g.translate(0, 8.2, 0); return g; })(), M('corrugated', 0x6a6a6a))]);
      },
      waterTower(r) {
        const cone = new THREE.ConeGeometry(3.8, 1.8, 12).translate(0, 17.9, 0);
        return { g: mk([mesh(cylGeo(2.6, 2.9, 13, 12, 3).translate(0, 6.5, 0), M('red_brick_03')), mesh(cylGeo(3.5, 3.4, 4, 12, 2).translate(0, 15, 0), M('wood_plank_wall', 0xa89880)),
          mesh(cone, M('corrugated', 0x7a8a7a))]), w: 8, d: 8 };
      },
      farm(r) {
        const w = R(r, 36, 60), d = 12, h = 4, roofG = gableGeo(w, d, 2.4, 0.4, 3); roofG.translate(0, h, 0);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, 1, 3, 0.5, { sp: 4, ww: 1.4, wh: 0.8 });
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M(pick(r, ['white_bricks', 'grey_plaster']), 0xe8e4dc)), mesh(roofG, M('corrugated', pick(r, ROOF_T))), qb.mesh()]),
          w, d, loot: 'dacha', label: 'Колхозная ферма' };
      },
      ruins(r) {
        const w = R(r, 7, 14), d = R(r, 6, 10), p = [];
        p.push(boxAt(w, R(r, 1, 3.5), 0.4, 0, 0, d / 2, 2), boxAt(0.4, R(r, 1.5, 4), d, -w / 2, 0, 0, 2), boxAt(w * 0.6, R(r, 0.8, 2.5), 0.4, w * 0.2, 0, -d / 2, 2));
        p.forEach((g) => { g.computeBoundingBox(); const hh = g.boundingBox.max.y - g.boundingBox.min.y; g.translate(0, hh / 2, 0); });
        for (let i = 0; i < 8; i++) p.push(boxAt(R(r, 0.3, 1), R(r, 0.2, 0.6), R(r, 0.3, 1), R(r, -w / 2, w / 2), 0.2, R(r, -d / 2, d / 2), 1, r() * 3));
        return { g: mk([mesh(merge(p), M(pick(r, ['red_brick_03', 'grey_plaster', 'white_bricks']), 0x8a7a70))]), w, d, loot: 'ruins', label: 'Руины дома' };
      },
      busStop(r) {
        const sg = sign('ОСТАНОВКА', 2, 0.4, '#ffffff', '#1d3f80'); sg.position.set(0, 2.8, 0.81);
        return { g: mk([mesh(merge([boxAt(4, 2.4, 0.15, 0, 1.2, -0.7, 2), boxAt(4.4, 0.15, 1.7, 0, 2.45, 0, 2), boxAt(0.15, 2.4, 1.4, -2, 1.2, 0, 2), boxAt(0.15, 2.4, 1.4, 2, 1.2, 0, 2)]),
          M('grey_plaster', 0xb5b0a5)), sg]), w: 5, d: 2 };
      },
      lenin(r) {
        const met = P(pick(r, [0x6b5a3a, 0xb8b8b8, 0x8a8a84]), 40);
        const g = mk([mesh(boxAt(2.2, 3, 2.2, 0, 1.5, 0, 2), M('grey_plaster', 0x9a9a98)),
          mesh(merge([cylGeo(0.42, 0.6, 2.1, 8).translate(0, 4.05, 0), new THREE.SphereGeometry(0.3, 8, 6).translate(0, 5.4, 0),
            boxAt(0.2, 1.1, 0.2, 0.5, 5.1, -0.3, 1).rotateZ(0.0)]), met)]);
        return { g, w: 4, d: 4 };
      },
      car(r) { return makeCar(r, r() < 0.4); },
      booth(r) {
        const sg = sign('КАССА', 1.6, 0.4, '#1f4e8c', '#ffffff'); sg.position.set(0, 2.4, 1.56);
        return { g: mk([mesh(boxAt(4, 2.8, 3, 0, 1.4, 0, 2), M('grey_plaster', 0xd8d0b8)), mesh(boxAt(4.4, 0.2, 3.4, 0, 2.9, 0, 2), C(0x55524e)), sg]),
          w: 4.4, d: 3.4, loot: 'kiosk', label: 'Билетная касса' };
      },
      stationHouse(r, ctx, st) {
        const floors = st.kind === 'town' ? 2 : RI(r, 1, 2), w = R(r, 16, 28) + (st.kind === 'town' ? 10 : 0), d = R(r, 8, 11), h = floors * 3.6 + 0.6;
        const wall = M(pick(r, ['yellow_plaster', 'yellow_plaster', 'red_brick_03', 'grey_plaster']), pick(r, [0xffffff, 0xf0d8c8, 0xd8e8d0, 0xd0dcec]));
        const qb = new QuadBatch(); winGrid(qb, r, w, d, floors, 3.6, 0.3, { sp: 3.4, ww: 1.4, wh: 2.0, frame: 0xf6f2e8 });
        qb.front(0, 1.4, -d / 2 - 0.06, 0.9, 1.3, -1, 0x3a2a1a);
        const roofG = gableGeo(w, d, 2.6, 0.6); roofG.translate(0, h, 0);
        const g = mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), wall), mesh(boxAt(w + 0.4, 0.35, d + 0.4, 0, h - 0.2, 0, 3), C(0xf2eee4)),
          mesh(roofG, M('corrugated', pick(r, [0x4f7a5a, 0x8a5a4a, 0x7a8a8a]))), qb.mesh()]);
        for (const f of [1, -1]) {
          const sg = sign(st.name.toUpperCase(), Math.min(w - 2, st.name.length * 0.6 + 2), 1.0, '#f6f2e8', '#1d3f80', false);
          sg.position.set(0, h + 0.9, f * (d / 2 + 0.4)); if (f < 0) sg.rotation.y = Math.PI; g.add(sg);
        }
        return { g, w, d, loot: 'station', label: 'Вокзал ' + st.name };
      },
      depot(r) {
        const w = 44, d = 18, h = 11, roofG = gableGeo(w, d, 3, 0.4, 3); roofG.translate(0, h, 0);
        const qb = new QuadBatch(); winGrid(qb, r, w, d, 1, h, 0, { sp: 5.5, ww: 3, wh: 4 });
        for (const x of [-12, 0, 12]) qb.front(x, 3.2, d / 2 + 0.07, 2.4, 3.2, 1, 0x2a2622);
        const sg = sign('ЛОКОМОТИВНОЕ ДЕПО', 12, 1.2, '#f2eee4', '#7a1f1a', false); sg.position.set(0, h - 1.3, d / 2 + 0.1);
        return { g: mk([mesh(boxAt(w, h, d, 0, h / 2, 0, 3), M('red_brick_03')), mesh(roofG, M('corrugated', 0x6a6a6a)), qb.mesh(), sg]), w, d };
      },
    };
  }
}
