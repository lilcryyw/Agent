import * as THREE from '../vendor/three.module.min.js';
import { T, rngOf, R, RI, pick, wpick, clamp, lerp, worldPos, toTrack, frameAt } from './util.js';
import { World, ZONE_DENSITY, ZONE_NAMES } from './world.js';
import { Train, BRAKE_NAMES, BRAKE_HINT } from './train.js';
import { Zombies } from './zombies.js';
import { loadChars } from './chars.js';
import { Player } from './player.js';
import { Audio } from './audio.js';
import { ITEMS, CAT_NAMES, WEAPONS, AMMO, LOOT, WAGON_CARGO, LOOT_TIME, UPGRADES, makeUnique, ICONS, itemDesc } from './data.js';

const $ = (s) => document.querySelector(s);
const SAVE = 'mp_save_v2', SAFE = 'mp_safe_v2', OPTS = 'mp_opts_v1';
const PACK_MAX = 30;
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* хранилище недоступно */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* ничего */ } },
};
const opts = Object.assign({ sound: true, vig: true, hq: false }, store.get(OPTS) || {});

// ---------------- рендер и сцена
const canvas = $('#c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: opts.hq, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, opts.hq ? 2 : 1.3));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(62, 1, 0.1, 900);
scene.fog = new THREE.Fog(0x9ab0c4, 40, 420);
scene.background = new THREE.Color(0x9ab0c4);
const hemi = new THREE.HemisphereLight(0xdfe8f0, 0x5a5a48, 1.1); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff2dc, 1.5); scene.add(sun); scene.add(sun.target);
const head = new THREE.SpotLight(0xfff4d8, 0, 0, 0.32, 0.5, 0);
const headT = new THREE.Object3D();
const search = new THREE.SpotLight(0xffffff, 0, 0, 0.12, 0.3, 0);
const searchT = new THREE.Object3D();
const torch = new THREE.SpotLight(0xfff0d0, 0, 40, 0.5, 0.6, 1.2);
const torchT = new THREE.Object3D(); scene.add(torch); scene.add(torchT); torch.target = torchT;

function resize() {
  renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  sizeDash();
}
addEventListener('resize', resize);

const stars = (() => {
  const p = []; const r = Math.random;
  for (let i = 0; i < 600; i++) { const a = r() * Math.PI * 2, e = Math.asin(r()), d = 600; p.push(Math.cos(a) * Math.cos(e) * d, Math.sin(e) * d, Math.sin(a) * Math.cos(e) * d); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
  const m = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, sizeAttenuation: false, fog: false, transparent: true, opacity: 0 }));
  scene.add(m); return m;
})();
const RAIN_N = 1400;
const rain = (() => {
  const p = new Float32Array(RAIN_N * 6);
  for (let i = 0; i < RAIN_N; i++) { const x = (Math.random() - 0.5) * 60, y = Math.random() * 30, z = (Math.random() - 0.5) * 60; p.set([x, y, z, x, y - 0.6, z], i * 6); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  const m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xaab8c8, transparent: true, opacity: 0.5 }));
  m.frustumCulled = false; m.visible = false; scene.add(m); return m;
})();
const snow = (() => {
  const p = new Float32Array(RAIN_N * 3);
  for (let i = 0; i < RAIN_N; i++) p.set([(Math.random() - 0.5) * 60, Math.random() * 30, (Math.random() - 0.5) * 60], i * 3);
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  const m = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 0.16 }));
  m.frustumCulled = false; m.visible = false; scene.add(m); return m;
})();
const tracers = [];
for (let i = 0; i < 8; i++) {
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
  const l = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xffe08a, transparent: true, opacity: 0.9 }));
  l.visible = false; l.frustumCulled = false; l.userData.t = 0; scene.add(l); tracers.push(l);
}
const BLOOD_N = 120;
const blood = (() => {
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(BLOOD_N * 3), 3));
  const m = new THREE.Points(g, new THREE.PointsMaterial({ color: 0x6a0e0a, size: 0.12 }));
  m.frustumCulled = false; scene.add(m);
  m.userData.v = new Float32Array(BLOOD_N * 3); m.userData.life = new Float32Array(BLOOD_N); m.userData.i = 0;
  return m;
})();

// ---------------- состояние
const audio = new Audio(); audio.on = opts.sound;
let S = null, world = null, train = null, player = null;
const zombies = new Zombies(scene);
let running = false, paused = true, camMode = 'chase';
const orbit = { yaw: 0.35, h: 8, dist: 19 }, look = { yaw: 0, pitch: -0.04 }, fcam = { yaw: 0, pitch: 0.25 };
let fireCd = 0, spawnT = 1, saveT = 10, hudT = 0, turretCd = 0, arrivedK = -1, warnedK = -1, guardT = 0;
let task = null;
const camPos = new THREE.Vector3(), camLook = new THREE.Vector3();
const _tt = {};

function newState(seed) {
  return {
    v: 2, seed, time: 7.3, day: 1, hp: 100, food: 85, infected: false, money: 150,
    pack: { tushenka: 2, voda: 1, bint: 2, pm: 1 }, cargo: { kanistra: 1, grechka: 2, suhari: 2 },
    uniques: [], ammo: { p9: 36, p12: 0, p545: 0, p762: 0 }, weapon: 'pm',
    kills: 0, found: 0, looted: [], cleared: [], settle: {}, visited: [], weather: { type: 'cloudy', t: 5 }, maxS: 0, tut: 0, log: [],
  };
}
function migrate(o) {
  if (o.v === 2) return o;
  const n = Object.assign(newState(o.seed), o, { v: 2 });
  n.cargo = o.inv || {}; n.pack = {};
  for (const id of Object.keys(n.cargo)) if (WEAPONS[id]) { n.pack[id] = n.cargo[id]; delete n.cargo[id]; }
  n.uniques = (o.uniques || []).map((u) => Object.assign(u, { where: 'cargo' }));
  delete n.inv; return n;
}
function setupWorld() {
  if (world) world.clear();
  zombies.clear();
  world = new World(scene, S.seed);
  world.looted = new Set(S.looted); world.cleared = new Set(S.cleared);
  world.prime(train.s);
}
function buildTrain(o) {
  if (train) for (const c of train.cars) scene.remove(c.g);
  train = new Train(scene);
  if (o) train.load(o);
  train.vigOn = opts.vig;
  train.build();
  const L = train.loco;
  head.position.copy(L.lampPos); L.g.add(head); headT.position.set(0, 0, -80); L.g.add(headT); head.target = headT;
  search.position.set(0.9, 5.15, -8.2); L.g.add(search); searchT.position.set(0, -2, -200); L.g.add(searchT); search.target = searchT;
  computeAxles();
}
function newGame() {
  store.del(SAVE); store.del(SAFE);
  S = newState((Math.random() * 1e9) | 0);
  buildTrain(null); setupWorld(); enterCab(true); updateCargo(); start();
  notify('Депо «Узловая». Город пал. Впереди — тысячи километров пути.', 'radio');
}
function snapshot() {
  S.looted = [...world.looted]; S.cleared = [...world.cleared]; S.train = train.save();
  S.player = { mode: player.mode, off: player.off, d: player.d, x: player.pos.x, z: player.pos.z };
  return JSON.parse(JSON.stringify(S));
}
function saveGame() { if (S && running && !player.busy) store.set(SAVE, snapshot()); }
function loadGame(o) {
  S = migrate(o);
  buildTrain(S.train); setupWorld();
  const pm = S.player;
  if (pm && pm.mode === 'ground') { player.mode = 'ground'; player.pos.set(pm.x, 0, pm.z); player.root.visible = true; }
  else if (pm && pm.mode === 'roof') { player.mode = 'roof'; player.off = pm.off; player.d = pm.d; player.root.visible = true; }
  else enterCab(true);
  updateCargo(); start();
}
function start() {
  running = true; paused = false; task = null; lootPending = null;
  orbit.yaw = 0.35; orbit.h = 8; orbit.dist = 19; camMode = 'chase';
  $('#title').hidden = true; $('#hud').hidden = false; closeModal(); resize();
  audio.init();
  try { navigator.wakeLock && navigator.wakeLock.request('screen').catch(() => {}); } catch (e) { /* нет */ }
}

// ---------------- груз: рюкзак и вагоны
const wOf = (id) => (ITEMS[id] ? ITEMS[id].w : 0);
function kg(where) {
  let w = 0; for (const [id, q] of Object.entries(S[where])) w += wOf(id) * q;
  for (const u of S.uniques) if (u.where === where) w += u.w; return w;
}
function updateCargo() { train.cargoKg = kg('cargo'); }
function add(where, id, q = 1) { S[where][id] = (S[where][id] || 0) + q; }
function take(where, id, q = 1) {
  S[where][id] -= q; if (S[where][id] <= 0) delete S[where][id];
  if (WEAPONS[id] && !S.pack[id] && S.weapon === id) S.weapon = ownedWeapons()[0] || null;
}
function ownedWeapons() { return Object.keys(WEAPONS).filter((w) => S.pack[w] > 0); }
function nearTrain() {
  if (player.mode !== 'ground') return true;
  toTrack(player.pos.x, player.pos.z, _tt);
  const ds = _tt.s > train.s ? _tt.s - train.s : _tt.s < train.sRear ? train.sRear - _tt.s : 0;
  return Math.hypot(ds, Math.max(0, Math.abs(_tt.d) - 1.6)) < 8;
}

// ---------------- уведомления: бортовой дисплей, рация, мысли
const notes = []; let noteT = 0, noteCur = null;
const NOTE_SRC = { klub: 'КЛУБ-У', radio: 'РАЦИЯ', me: '', alert: 'ВНИМАНИЕ', good: '' };
function notify(text, kind = 'me') {
  if ((noteCur && noteCur.text === text) || notes.some((n) => n.text === text)) return;
  notes.push({ text, kind });
  while (notes.length > 3) { const i = notes.findIndex((n) => n.kind !== 'alert'); notes.splice(i >= 0 ? i : 0, 1); }
  if (S) { S.log.unshift(`${hhmm()} · ${text}`); S.log.length = Math.min(S.log.length, 40); }
  if (kind === 'alert') noteT = Math.min(noteT, 0.6);
}
function noteTick(dt) {
  noteT -= dt;
  if (noteT > 0) return;
  noteCur = notes.shift() || null;
  const el = $('#note');
  if (!noteCur) { el.classList.remove('on'); noteT = 0.2; return; }
  el.className = 'on ' + noteCur.kind;
  el.querySelector('b').textContent = NOTE_SRC[noteCur.kind] || '';
  el.querySelector('span').textContent = noteCur.text;
  noteT = noteCur.kind === 'alert' ? 4 : Math.min(5.5, 2.4 + noteCur.text.length / 28);
}
function hhmm() { if (!S) return ''; const h = Math.floor(S.time), m = Math.floor((S.time - h) * 60); return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'); }
function hurtFlash(k = 1) { const h = $('#hurt'); h.style.opacity = Math.min(0.85, 0.35 * k + 0.2); clearTimeout(h._t); h._t = setTimeout(() => (h.style.opacity = 0), 160); }

// ---------------- контекст для зомби
const zctx = {
  train: null, player: null, cam: camera.position,
  groundH(s, d) {
    if (Math.abs(d) < 2.2) return 0.4;
    const st = world.nearestStation(s);
    if (Math.abs(st.s - s) < st.len / 2 && d * st.side > 1.95 && d * st.side < 6.5) return 1.1;
    return 0;
  },
  hurtTrain(d) { if (!running) return; train.dur -= d; if (d > 1.5) { audio.thud(); if (player.mode !== 'ground') hurtFlash(0.4); } if (train.dur <= 0) gameOver('Поезд разбит. Зомби взяли его штурмом.'); },
  hurtPlayer(d, outside) {
    if (!running) return;
    S.hp -= d * (outside ? 1 : 0.6); hurtFlash(1); audio.thud();
    if (task) { task = null; $('#prog').hidden = true; notify('Обыск прерван!', 'alert'); }
    if (outside && !S.infected && Math.random() < 0.1) { S.infected = true; notify('Укус! Нужны антибиотики.', 'alert'); }
    if (S.hp <= 0) gameOver(outside ? 'Вас загрызли.' : 'Зомби ворвались в кабину.');
  },
  onKill() { S.kills++; },
  sound(kind, z, dist) { if (kind === 'groan') audio.groan(1 - dist / 45); else if (kind === 'splat') audio.splat(); },
  scream(z) {
    audio.scream(); notify('Крикун созывает мертвецов!', 'alert');
    const r = Math.random, p = z.h.root.position;
    for (let i = 0; i < RI(r, 3, 6); i++) { const a = r() * 6.28, d = R(r, 25, 60); zombies.spawn(r() < 0.4 ? 'runner' : 'walker', p.x + Math.cos(a) * d, p.z + Math.sin(a) * d, train.s / 1000, r); }
  },
};

// ---------------- игровой цикл
let last = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  if (running && !paused) step(dt);
  if (train) { updateCamera(dt); renderer.render(scene, camera); }
  if (running) { noteTick(dt); hudT -= dt; if (hudT <= 0) { hudT = 0.12; updateHud(); } drawDash(); }
}
function env() {
  const season = world.seasonAt(train.s), w = S.weather.type;
  let mu = 0.25;
  if (w === 'rain') mu = 0.17; if (w === 'fog') mu = 0.21; if (w === 'snow' || season === 'winter') mu = Math.min(mu, 0.16);
  if (season === 'autumn') mu -= 0.03;
  return { mu, season };
}
function step(dt) {
  const E = env(), prevS = train.s;
  if (player.mode !== 'cab') train.pos = 0;
  train.update(dt, E);
  for (const ev of train.events.splice(0)) {
    if (ev[0] === 'msg') notify(ev[1], 'klub');
    else if (ev[0] === 'alarm') { notify(ev[1], 'alert'); audio.alarm(); }
    else if (ev[0] === 'vig') audio.beep();
    else if (ev[0] === 'start') audio.starter();
  }
  if (S.tut === 0 && train.kmh > 15) { S.tut = 1; notify('Поехали. Касание по зомби — выстрел. Остановитесь у домов и выйдите на вылазку.', 'me'); }
  for (const o of world.obstacles.values()) {
    if (o.s - 1.6 < train.s && o.s > train.s - 3) {
      if (train.kmh > 15) {
        const dmg = { tree: 10, car: 16, barricade: 22 }[o.type] * (train.up.plow ? 0.3 : 1) * Math.min(2, train.kmh / 30);
        zctx.hurtTrain(dmg); train.v *= 0.55; audio.thud(); audio.splat();
        notify(`Протаранили: ${o.label.toLowerCase()}. Прочность −${dmg.toFixed(0)}%`, 'alert');
        world.removeObstacle(o);
      } else if (train.v > 0) {
        train.v = 0; train.s = o.s - 1.6; train.F = 0; notify(`Путь перекрыт: ${o.label.toLowerCase()}. Выйдите и разберите.`, 'alert');
      }
      break;
    }
  }
  const j0 = Math.floor(prevS / 25), j1 = Math.floor(train.s / 25);
  if (j0 !== j1 && train.v > 1) { const back = train.s - j1 * 25; audio.clack(train.v, AXLES.filter((a) => a < 40 && a > back).map((a) => a - back)); }
  world.update(train.s);
  player.update(dt, input(), train, world, zctx.groundH);
  if (player.mode === 'ground' && Math.abs(train.v) > 0.5 && !S.leftWarn) { S.leftWarn = true; notify('Поезд катится без машиниста!', 'alert'); }
  const hrs = dt / 40;
  S.time += hrs; if (S.time >= 24) { S.time -= 24; S.day++; }
  S.weather.t -= hrs; if (S.weather.t <= 0) newWeather(E.season);
  if (E.season === 'winter' && S.weather.type === 'rain') S.weather.type = 'snow';
  if (E.season !== 'winter' && S.weather.type === 'snow') S.weather.type = 'rain';
  S.food = Math.max(0, S.food - dt * 0.06);
  if (S.food <= 0) { S.hp -= dt * 0.25; if (S.hp <= 0) return gameOver('Вы умерли от голода.'); }
  if (S.infected) { S.hp -= dt * 0.12; if (S.hp <= 0) return gameOver('Инфекция взяла своё.'); }
  if (S.food > 60 && !S.infected) S.hp = Math.min(100, S.hp + dt * 0.04);
  spawn(dt);
  zctx.train = train; zctx.player = player;
  zombies.update(dt, zctx);
  guards(dt); turret(dt); taskTick(dt); fx(dt);
  const st = world.nearestStation(train.s);
  if (st.settle && st.k !== warnedK && st.s - train.s < 1200 && st.s - train.s > 300) { warnedK = st.k; notify(`${st.kind === 'depot' ? 'Депо' : 'Поселение «' + st.settle + '»'} на станции ${st.name}: торговля и ремонт. Ждём.`, 'radio'); }
  if (Math.abs(train.v) < 0.05 && Math.abs(st.s - train.s) < st.len / 2 + 40 && arrivedK !== st.k) {
    arrivedK = st.k;
    if (!S.visited.includes(st.name)) S.visited.push(st.name);
    notify((st.settle ? 'Поселение «' + st.settle + '», ' : 'Станция ') + st.name, st.settle ? 'radio' : 'klub');
    if (st.settle) store.set(SAFE, snapshot());
  }
  S.maxS = Math.max(S.maxS, train.s);
  saveT -= dt; if (saveT <= 0) { saveT = 15; saveGame(); }
}
let AXLES = [];
function computeAxles() {
  AXLES = []; let off = 0;
  for (const c of train.cars) {
    const bog = c.kind === 'loco' ? [-5.4, 5.4] : c.kind === 'tank' ? [-3.9, 3.9] : [-4.4, 4.4], n = c.kind === 'loco' ? 3 : 2;
    for (const b of bog) for (let i = 0; i < n; i++) AXLES.push(off + c.len / 2 + b + (i - (n - 1) / 2) * 1.85);
    off += c.len + 0.6;
  }
}
function newWeather(season) {
  const r = Math.random;
  const t = season === 'winter' ? [['cloudy', 2], ['snow', 3], ['clear', 2], ['fog', 1]] : season === 'autumn' ? [['cloudy', 3], ['rain', 3], ['fog', 2], ['clear', 1]] : [['clear', 3], ['cloudy', 3], ['rain', 2], ['fog', 1]];
  S.weather = { type: wpick(r, t), t: R(r, 3, 8) };
}
function spawn(dt) {
  spawnT -= dt; if (spawnT > 0) return; spawnT = 0.9;
  const zone = world.zoneAt(train.s + 60), km = train.s / 1000;
  const night = S.time < 5.5 || S.time > 21;
  const dens = ZONE_DENSITY[zone] * (night ? 1.5 : 1) * (S.weather.type === 'fog' ? 1.2 : 1);
  const want = Math.min(30, Math.round(dens * 20 * (1 + km / 150)));
  if (zombies.alive >= want || zone === 'settlement' || train.s < 400) return;
  const r = Math.random, n = RI(r, 1, Math.min(5, 2 + Math.floor(km / 15)));
  let s, d;
  if (player.mode === 'ground' && r() < 0.6) { toTrack(player.pos.x, player.pos.z, _tt); s = _tt.s + R(r, -60, 60); d = _tt.d + (r() < 0.5 ? -1 : 1) * R(r, 25, 55); }
  else if (Math.abs(train.v) < 1) { s = train.s + R(r, -130, 140); d = (r() < 0.5 ? -1 : 1) * R(r, 18, 75); }
  else { s = train.s + R(r, 70, 280); d = (r() < 0.5 ? -1 : 1) * R(r, 6, 90); }
  if (world.zoneAt(s) === 'settlement') return;
  const season = world.seasonAt(s);
  for (let i = 0; i < n; i++) { const p = worldPos(s + R(r, -8, 8), d + R(r, -8, 8)); zombies.spawn(zombies.pickType(r, km, season), p.x, p.z, km, r); }
}
function guards(dt) {
  guardT -= dt; if (guardT > 0) return; guardT = 0.7;
  for (const z of zombies.list) {
    if (z.state === 'dead' || z.state === 'fly') continue;
    toTrack(z.h.root.position.x, z.h.root.position.z, _tt);
    if (world.zoneAt(_tt.s) === 'settlement' && Math.random() < 0.5) { zombies.kill(z); if (Math.random() < 0.6) audio.shot('rifle'); break; }
  }
}
const _tp = new THREE.Vector3(), _tz = new THREE.Vector3();
function turret(dt) {
  if (!train.up.turret) return;
  turretCd -= dt; if (turretCd > 0 || (S.ammo.p762 || 0) <= 0) return;
  const tur = train.loco.up.turret; tur.getWorldPosition(_tp); _tp.y += 1;
  let best = null, bd = 48;
  for (const z of zombies.list) {
    if (z.state === 'dead' || z.state === 'fly') continue;
    const d = _tp.distanceTo(z.h.root.position) - (z.state === 'attack' ? 20 : 0);
    if (d < bd) { bd = d; best = z; }
  }
  if (!best) return;
  turretCd = 0.16; S.ammo.p762--;
  _tz.copy(best.h.root.position); _tz.y += 1.1 * best.size;
  const gun = tur.userData.gun, lp = tur.worldToLocal(_tz.clone());
  gun.rotation.y = Math.atan2(-lp.x, -lp.z);
  audio.shot('turret');
  const hit = Math.random() < 0.75;
  if (hit && zombies.hit(best, 30, Math.random() < 0.1)) zctx.onKill(best);
  tracer(_tp, hit ? _tz : _tz.clone().add(new THREE.Vector3(R(Math.random, -1, 1), 0.5, R(Math.random, -1, 1))));
  if (hit) bleed(_tz);
}

// ---------------- точки поезда: двери, лестницы
function trainSpots() {
  const out = []; let o = 0;
  for (const c of train.cars) {
    const center = -o - c.len / 2;
    if (c.kind === 'loco') {
      for (const f of [1, -1]) out.push({ kind: 'door', off: center + 6.45, d: f * 2.05, f });
      for (const f of [1, -1]) out.push({ kind: 'ladder', off: center - 8.57, d: f * 2.0, f, top: center - 7.6 });
    } else if (c.kind === 'box') {
      for (const f of [1, -1]) out.push({ kind: 'ladder', off: center - 6.75, d: f * 2.0, f, top: center - 5.8 });
    }
    o += c.len + 0.6;
  }
  return out;
}
function spotPos(sp) { return worldPos(train.s + sp.off, sp.d); }
function enterCab(instant) {
  if (instant) { player.mode = 'cab'; player.root.visible = false; return; }
  const doors = trainSpots().filter((s) => s.kind === 'door');
  const dd = doors.map((s) => [spotPos(s).distanceTo(player.pos), s]).sort((a, b) => a[0] - b[0])[0][1];
  player.climb([{ p: player.pos.clone() }, { rel: true, off: dd.off, d: dd.d, y: 0.4 }, { rel: true, off: dd.off, d: dd.f * 1.5, y: 2.1 }], 'cab', 1.2);
  audio.click();
}
function exitCab() {
  if (Math.abs(train.v) > 0.4) return notify('Сначала остановите поезд.', 'me');
  const side = orbitSide();
  const door = trainSpots().find((s) => s.kind === 'door' && s.f === side);
  train.pos = 0; if (train.brake < 3) train.brake = 3;
  player.pos.copy(worldPos(train.s + door.off, door.f * 1.5)); player.pos.y = 2.1;
  player.root.visible = true;
  player.climb([{ p: player.pos.clone() }, { rel: true, off: door.off, d: door.d, y: 0.4 }, { rel: true, off: door.off, d: door.f * 3.2, y: 0.4 }], 'ground', 1.1);
  frameAt(train.s, _tt); fcam.yaw = _tt.yaw + side * 0.35; fcam.pitch = 0.3;
  S.leftWarn = false;
  if (S.tut < 2) { S.tut = 2; notify('Джойстик слева — идти, до упора — бег. Свайп справа — осмотреться. Красная кнопка — огонь.', 'me'); }
}
function orbitSide() { return Math.sin(orbit.yaw) >= 0 ? 1 : -1; }
function climbUp(sp) {
  player.climb([{ p: player.pos.clone() }, { rel: true, off: sp.off, d: sp.d, y: 0.4 }, { rel: true, off: sp.off, d: sp.f * 1.7, y: 3.0 }, { rel: true, off: sp.top, d: sp.f * 0.8, y: player.roofY(train, sp.top) }], 'roof', 2.2);
}
function climbDown(sp) {
  player.climb([{ p: player.pos.clone() }, { rel: true, off: sp.top, d: sp.f * 1.0, y: player.roofY(train, sp.top) }, { rel: true, off: sp.off, d: sp.f * 1.7, y: 3.0 }, { rel: true, off: sp.off, d: sp.d + sp.f, y: 0.4 }], 'ground', 2.0);
}

// ---------------- обыск, расчистка
function startTask(kind, obj) {
  if (task || player.busy) return;
  task = { kind, obj, t: 0, total: kind === 'loot' ? (LOOT_TIME[obj.type] || 6) : 8, at: player.pos.clone() };
  $('#prog').hidden = false;
  $('#prog .pl').textContent = kind === 'loot' ? 'Обыск: ' + obj.label : 'Разбираем: ' + obj.label.toLowerCase();
  audio.click();
}
function taskTick(dt) {
  if (!task) return;
  if (player.pos.distanceTo(task.at) > 0.8) { task = null; $('#prog').hidden = true; notify('Обыск брошен.', 'me'); return; }
  task.t += dt;
  $('#prog .pb u').style.width = (100 * Math.min(1, task.t / task.total)).toFixed(0) + '%';
  if (task.t < task.total) return;
  const T0 = task; task = null; $('#prog').hidden = true;
  if (T0.kind === 'clear') { world.removeObstacle(T0.obj); notify('Путь свободен.', 'good'); return; }
  world.looted.add(T0.obj.id);
  const items = rollLoot(T0.obj); S.found += items.length;
  showLoot(T0.obj, items);
}
function strHash(s) { let h = 7; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 2654435761); return h >>> 0; }
function rollLoot(L) {
  const r = rngOf(S.seed, 707, strHash(L.id)), out = [];
  if (L.type === 'wagon_tank') { out.push({ fuel: RI(r, 150, 600) }); return out; }
  let table = L.type;
  if (L.type === 'wagon_box') { const [id, a, b] = pick(r, WAGON_CARGO); out.push({ id, qty: RI(r, a, b) }); table = 'station'; if (r() < 0.6) return out; }
  const T0 = LOOT[table]; if (!T0) return out;
  const n = RI(r, T0.rolls[0], T0.rolls[1]) + (train.s > 40000 && r() < 0.4 ? 1 : 0);
  for (let i = 0; i < n; i++) {
    const e = wpick(r, T0.t);
    if (e === 'money') out.push({ money: RI(r, 10, 70) });
    else if (e.startsWith('am_')) { const a = e.slice(3); out.push({ ammo: a, n: RI(r, AMMO[a].find[0], AMMO[a].find[1]) }); }
    else if (e === 'UNIQUE') { const u = makeUnique(r); u.uid = L.id + '.' + i; out.push({ unique: u }); }
    else { const ex = out.find((o) => o.id === e); if (ex) ex.qty++; else out.push({ id: e, qty: 1 }); }
  }
  return out;
}

// ---------------- стрельба
const _p = new THREE.Vector3(), _o = new THREE.Vector3();
const alive = (z) => z.state !== 'dead' && z.state !== 'fly';
function pickZombie(sx, sy) {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  let best = null, bd = 1e9;
  for (const z of zombies.list) {
    if (!alive(z)) continue;
    _p.copy(z.h.root.position); _p.y += 1.1 * z.size;
    const wd = camera.position.distanceTo(_p);
    _p.project(camera); if (_p.z > 1) continue;
    const px = (_p.x + 1) / 2 * W, py = (1 - _p.y) / 2 * H, dd = Math.hypot(px - sx, py - sy);
    const rad = Math.max(40, 1100 * z.size / wd);
    if (dd < rad && dd < bd) { bd = dd; best = z; }
  }
  return best;
}
function autoTarget() {
  if (!S.weapon) return null;
  const W = WEAPONS[S.weapon]; shotOrigin(_o);
  const f = new THREE.Vector3(); camera.getWorldDirection(f); f.y = 0; f.normalize();
  let best = null, bs = -1;
  for (const z of zombies.list) {
    if (!alive(z)) continue;
    _p.copy(z.h.root.position); const d = _p.distanceTo(_o);
    if (d > W.range * 1.3) continue;
    _p.sub(_o); _p.y = 0; _p.normalize();
    const dot = _p.dot(f);
    const score = d < 6 ? 2 - d / 6 : dot > 0.8 ? dot - d / 400 : -1;
    if (score > bs) { bs = score; best = z; }
  }
  return best;
}
function shotOrigin(v) {
  if (player.mode === 'cab') return train.loco.g.localToWorld(v.set(1.2, 3.8, -7.8));
  return v.copy(player.pos).add(new THREE.Vector3(0, 1.45, 0));
}
function fire(z) {
  if (!S.weapon || fireCd > 0) return;
  const W = WEAPONS[S.weapon];
  if ((S.ammo[W.ammo] || 0) <= 0) { notify('Нет патронов ' + AMMO[W.ammo].n, 'me'); audio.click(); fireCd = 0.6; return; }
  S.ammo[W.ammo]--; fireCd = W.rate; audio.shot(W.snd);
  shotOrigin(_o);
  if (!z) {
    const f = new THREE.Vector3(); camera.getWorldDirection(f);
    if (player.mode !== 'cab') { player.aimDir.copy(f); player.aimT = 0.6; }
    tracer(_o, _o.clone().addScaledVector(f, 60)); return;
  }
  _p.copy(z.h.root.position); _p.y += 1.1 * z.size;
  if (player.mode !== 'cab') { player.aimDir.copy(_p).sub(_o).normalize(); player.aimT = 0.7; }
  const d3 = _o.distanceTo(_p), r = Math.random;
  const hitP = clamp(1.05 - d3 / W.range * 0.6, 0.12, 0.97);
  let dmg = 0, hits = 0;
  for (let i = 0; i < W.pellets; i++) if (r() < hitP) { hits++; dmg += W.dmg * (W.pellets > 1 ? clamp(1 - d3 / W.range * 0.7, 0.2, 1) : 1); }
  const headShot = hits > 0 && r() < 0.18;
  if (hits) { if (zombies.hit(z, dmg, headShot)) zctx.onKill(z); bleed(_p); tracer(_o, _p); if (headShot) hitMark(); }
  else tracer(_o, _p.clone().add(new THREE.Vector3(R(r, -1.5, 1.5), R(r, -0.5, 1.2), R(r, -1.5, 1.5))));
}
function tracer(a, b) {
  const l = tracers.find((t) => !t.visible) || tracers[0];
  const p = l.geometry.attributes.position; p.setXYZ(0, a.x, a.y, a.z); p.setXYZ(1, b.x, b.y, b.z); p.needsUpdate = true;
  l.visible = true; l.userData.t = 0.06;
}
function bleed(p) {
  const pa = blood.geometry.attributes.position, u = blood.userData;
  for (let k = 0; k < 8; k++) { const i = u.i = (u.i + 1) % BLOOD_N; pa.setXYZ(i, p.x, p.y, p.z); u.v.set([R(Math.random, -2, 2), R(Math.random, 0, 3), R(Math.random, -2, 2)], i * 3); u.life[i] = 0.8; }
}
function hitMark() { const h = $('#hit'); h.classList.remove('on'); void h.offsetWidth; h.classList.add('on'); }
function fx(dt) {
  fireCd -= dt;
  for (const t of tracers) if (t.visible) { t.userData.t -= dt; if (t.userData.t <= 0) t.visible = false; }
  const pa = blood.geometry.attributes.position, u = blood.userData;
  for (let i = 0; i < BLOOD_N; i++) if (u.life[i] > 0) {
    u.life[i] -= dt; u.v[i * 3 + 1] -= 9.8 * dt;
    pa.setXYZ(i, pa.getX(i) + u.v[i * 3] * dt, Math.max(0.05, pa.getY(i) + u.v[i * 3 + 1] * dt), pa.getZ(i) + u.v[i * 3 + 2] * dt);
    if (u.life[i] <= 0) pa.setXYZ(i, 0, -50, 0);
  }
  pa.needsUpdate = true;
  if (S.weapon && WEAPONS[S.weapon].auto) {
    if (fireHeld) fire(autoTarget());
    else if (ptr.down && !ptr.drag) { const z = pickZombie(ptr.x, ptr.y); if (z) fire(z); }
  }
}

// ---------------- камера, свет, небо
const _fw = new THREE.Vector3(), _cv = new THREE.Vector3(), _ct = {};
function updateCamera(dt) {
  const L = train.loco.g, yaw = L.rotation.y;
  const foot = running && player && player.mode !== 'cab';
  if (foot) {
    const p = player.pos, dist = player.mode === 'roof' ? 6 : 4.6, a = fcam.yaw, pc = Math.cos(fcam.pitch);
    _fw.set(p.x + Math.sin(a) * dist * pc + Math.cos(a) * 0.7, p.y + 1.7 + Math.sin(fcam.pitch) * dist, p.z + Math.cos(a) * dist * pc - Math.sin(a) * 0.7);
    // камера не заходит в поезд и в дома
    toTrack(_fw.x, _fw.z, _ct);
    if (_ct.s < train.s + 1.5 && _ct.s > train.sRear - 1.5 && Math.abs(_ct.d) < 2.2 && _fw.y < 6.3) {
      if (player.mode === 'roof') _fw.y = 6.4;
      else { toTrack(p.x, p.z, _tt); const sg = _tt.d >= 0 ? 1 : -1; worldPos(_ct.s, sg * 2.2, 0, _cv); _fw.x = _cv.x; _fw.z = _cv.z; }
    }
    const cc = world.collide(_ct.s, _ct.d, 0.3); if (cc.hit) { worldPos(cc.s, cc.d, 0, _cv); _fw.x = _cv.x; _fw.z = _cv.z; }
    camPos.lerp(_fw, Math.min(1, dt * 12)); if (camPos.distanceTo(_fw) > 20) camPos.copy(_fw);
    camera.position.copy(camPos);
    camera.lookAt(p.x - Math.sin(a) * 6 + Math.cos(a) * 0.7, p.y + 1.5, p.z - Math.cos(a) * 6 - Math.sin(a) * 0.7);
  } else if (camMode === 'cab' && running) {
    L.localToWorld(camPos.set(0.55, 3.9, -9.05));
    camera.position.copy(camPos);
    const a = yaw + look.yaw, pt = look.pitch;
    camera.lookAt(camPos.x - Math.sin(a) * Math.cos(pt) * 50, camPos.y + Math.sin(pt) * 50, camPos.z - Math.cos(a) * Math.cos(pt) * 50);
  } else {
    const a = yaw + orbit.yaw;
    const tx = L.position.x - Math.sin(yaw) * 2, tz = L.position.z - Math.cos(yaw) * 2;
    _fw.set(tx + Math.sin(a) * orbit.dist, orbit.h + 1, tz + Math.cos(a) * orbit.dist);
    camPos.lerp(_fw, camPos.lengthSq() ? Math.min(1, dt * 6) : 1);
    if (camPos.distanceTo(_fw) > 60) camPos.copy(_fw);
    camera.position.copy(camPos);
    camLook.set(tx - Math.sin(yaw) * 14, 2.5, tz - Math.cos(yaw) * 14);
    camera.lookAt(camLook);
  }
  $('#cabframe').hidden = !(camMode === 'cab' && !foot && running);
  if (!S) return;
  const t = S.time, elev = Math.sin((t - 6) / 12 * Math.PI);
  const dayK = clamp(elev * 2.2 + 0.25, 0, 1), dusk = clamp(1 - Math.abs(elev) * 4, 0, 1) * (elev > -0.3 ? 1 : 0);
  const w = S.weather.type, over = w === 'clear' ? 0 : w === 'cloudy' ? 0.5 : 0.8;
  const sky = _c1.setRGB(0.05, 0.07, 0.12).lerp(_c2.setRGB(0.55 - over * 0.12, 0.67 - over * 0.1, 0.78 - over * 0.12), dayK).lerp(_c3.setRGB(0.85, 0.55, 0.38), dusk * 0.45 * (1 - over * 0.6));
  if (env().season === 'winter') sky.lerp(_c2.setRGB(0.75, 0.8, 0.86), 0.25 * dayK);
  scene.background.copy(sky); scene.fog.color.copy(sky);
  const fogK = { clear: 1, cloudy: 0.85, rain: 0.55, fog: 0.22, snow: 0.45 }[w];
  scene.fog.far = lerp(170, 430, dayK) * fogK + 20; scene.fog.near = 8 + 30 * fogK * dayK;
  hemi.intensity = 0.22 + 0.95 * dayK; sun.intensity = 1.5 * dayK * (1 - over * 0.6);
  sun.position.set(camera.position.x + Math.cos(t / 24 * 6.28) * 100, 80, camera.position.z - 60); sun.target.position.copy(camera.position);
  const night = 1 - dayK;
  head.intensity = train.engine ? 0.6 + night * 3.2 : 0;
  search.intensity = train.up.light && train.engine ? night * 4 : 0;
  torch.intensity = foot ? night * 3 : 0;
  if (foot) { torch.position.copy(player.pos).add(new THREE.Vector3(0, 1.6, 0)); torchT.position.set(player.pos.x - Math.sin(player.yaw) * 10, 0, player.pos.z - Math.cos(player.yaw) * 10); }
  stars.material.opacity = night * (w === 'clear' ? 1 : 0.25); stars.position.copy(camera.position);
  rain.visible = w === 'rain'; snow.visible = w === 'snow';
  if (rain.visible || snow.visible) precip(dt, rain.visible ? rain : snow, rain.visible ? 22 : 2.2);
}
const _c1 = new THREE.Color(), _c2 = new THREE.Color(), _c3 = new THREE.Color();
function precip(dt, obj, sp) {
  obj.position.set(camera.position.x, camera.position.y - 12, camera.position.z);
  const p = obj.geometry.attributes.position, stride = obj === rain ? 2 : 1;
  for (let i = 0; i < p.count; i += stride) {
    let y = p.getY(i) - sp * dt, x = p.getX(i);
    if (obj === snow) x += Math.sin(y + i) * dt * 0.6;
    if (y < 0) y += 30;
    p.setY(i, y); p.setX(i, x);
    if (stride === 2) { p.setY(i + 1, y - 0.6); p.setX(i + 1, x); }
  }
  p.needsUpdate = true;
}
function gameOver(why) {
  if (!running) return;
  running = false; paused = true; store.del(SAVE);
  const safe = store.get(SAFE);
  openModal('Конец пути', `<p class="lead">${why}</p>
    <div class="grid2"><div><b>${(S.maxS / 1000).toFixed(1)}</b> км пройдено</div><div><b>${S.kills}</b> зомби уничтожено</div>
    <div><b>${S.found}</b> находок</div><div><b>${S.day}</b> дн. в пути</div></div>`,
  (safe ? '<button class="pri" data-act="loadSafe">Вернуться в последнее поселение</button>' : '') + '<button data-act="new">Новый рейс</button>', true);
}

// ---------------- ввод
const ptr = { down: false, drag: false, x: 0, y: 0, sx: 0, sy: 0, id: null };
const joy = { id: null, x0: 0, y0: 0, jx: 0, jy: 0 };
const keys = {};
let fireHeld = false;
function input() {
  let jx = joy.jx, jy = joy.jy;
  if (keys.w) jy = 1; if (keys.s) jy = -1; if (keys.a) jx = -1; if (keys.d) jx = 1;
  if (task && Math.hypot(jx, jy) > 0.3) { task = null; $('#prog').hidden = true; }
  if (task) { jx = 0; jy = 0; }
  return { jx, jy, camYaw: fcam.yaw, slow: S.hp < 25 };
}
canvas.addEventListener('pointerdown', (e) => {
  if (!running || paused) return;
  const foot = player.mode !== 'cab';
  if (foot && e.clientX < innerWidth * 0.42 && joy.id === null) {
    joy.id = e.pointerId; joy.x0 = e.clientX; joy.y0 = e.clientY; joy.jx = joy.jy = 0;
    const j = $('#joy'); j.hidden = false; j.style.left = e.clientX + 'px'; j.style.top = e.clientY + 'px'; $('#joy i').style.transform = '';
    canvas.setPointerCapture(e.pointerId); return;
  }
  if (ptr.id !== null) return;
  ptr.down = true; ptr.drag = false; ptr.id = e.pointerId;
  ptr.x = ptr.sx = e.clientX; ptr.y = ptr.sy = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => {
  if (e.pointerId === joy.id) {
    let dx = e.clientX - joy.x0, dy = e.clientY - joy.y0; const l = Math.hypot(dx, dy), mx = 55;
    if (l > mx) { dx *= mx / l; dy *= mx / l; }
    joy.jx = dx / mx; joy.jy = -dy / mx;
    $('#joy i').style.transform = `translate(${dx}px,${dy}px)`;
    return;
  }
  if (!ptr.down || e.pointerId !== ptr.id) return;
  const dx = e.clientX - ptr.x, dy = e.clientY - ptr.y;
  ptr.x = e.clientX; ptr.y = e.clientY;
  if (!ptr.drag && Math.hypot(ptr.x - ptr.sx, ptr.y - ptr.sy) > 12) ptr.drag = true;
  if (ptr.drag) {
    if (player.mode !== 'cab') { fcam.yaw -= dx * 0.007; fcam.pitch = clamp(fcam.pitch + dy * 0.004, -0.25, 1.1); }
    else if (camMode === 'cab') { look.yaw = clamp(look.yaw - dx * 0.005, -1.6, 1.6); look.pitch = clamp(look.pitch - dy * 0.004, -0.6, 0.5); }
    else { orbit.yaw -= dx * 0.008; orbit.h = clamp(orbit.h + dy * 0.04, 2.5, 30); }
  }
});
const endPtr = (e) => {
  if (e.pointerId === joy.id) { joy.id = null; joy.jx = joy.jy = 0; $('#joy').hidden = true; return; }
  if (!ptr.down || e.pointerId !== ptr.id) return;
  if (!ptr.drag && running && !paused) { const z = pickZombie(ptr.x, ptr.y); if (z) fire(z); }
  ptr.down = false; ptr.id = null;
};
canvas.addEventListener('pointerup', endPtr); canvas.addEventListener('pointercancel', endPtr);
canvas.addEventListener('wheel', (e) => { orbit.dist = clamp(orbit.dist + e.deltaY * 0.02, 8, 45); }, { passive: true });

function setPos(p) {
  p = clamp(Math.round(p), 0, 15);
  if (p === train.pos) return;
  if (p > 0 && !train.engine) { notify('Сначала запустите дизель.', 'me'); return; }
  if (p > 0 && train.rev === 0) { notify('Реверсор в нуле — выберите «В».', 'me'); return; }
  train.pos = p; audio.click();
}
function setBrake(b) { b = clamp(Math.round(b), 0, 5); if (b !== train.brake) { train.brake = b; audio.click(); } }
function lever(el, n, set, invert) {
  const calc = (e) => { const r = el.querySelector('.rail').getBoundingClientRect(); const k = clamp((e.clientY - r.top) / r.height, 0, 1); return invert ? (1 - k) * (n - 1) : k * (n - 1); };
  el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); el._d = true; set(calc(e)); e.preventDefault(); });
  el.addEventListener('pointermove', (e) => { if (el._d) set(calc(e)); });
  el.addEventListener('pointerup', () => (el._d = false)); el.addEventListener('pointercancel', () => (el._d = false));
}
function hold(el, on, off) {
  el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); el.classList.add('held'); on(); e.preventDefault(); });
  const up = () => { el.classList.remove('held'); off(); };
  el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
}
function bindUi() {
  const km = $('#km .notches'); for (let i = 15; i >= 0; i--) km.insertAdjacentHTML('beforeend', `<i>${i % 5 === 0 ? i : ''}</i>`);
  const kr = $('#kr .notches'); BRAKE_NAMES.forEach((n) => kr.insertAdjacentHTML('beforeend', `<i>${n}</i>`));
  lever($('#km'), 16, (v) => setPos(v), true);
  lever($('#kr'), 6, (v) => setBrake(v), false);
  hold($('#bHorn'), () => audio.set(audio.horn, 0.22, 0.03), () => audio.set(audio.horn, 0, 0.05));
  hold($('#bSand'), () => (train.sanding = true), () => (train.sanding = false));
  hold($('#bFire'), () => { fireHeld = true; fire(autoTarget()); }, () => (fireHeld = false));
  $('#bRB').addEventListener('click', () => { train.pressVigilance(); audio.click(); });
  $('#bEngine').addEventListener('click', () => {
    if (train.engine) { if (Math.abs(train.v) > 0.5) { notify('На ходу дизель не глушат.', 'me'); return; } train.stopEngine(); notify('Дизель остановлен.', 'klub'); }
    else train.startEngine();
  });
  for (const id of ['#bWeapon', '#bWeapon2']) $(id).addEventListener('click', () => {
    const own = ownedWeapons(); if (!own.length) { notify('Нет оружия.', 'me'); return; }
    S.weapon = own[(own.indexOf(S.weapon) + 1) % own.length]; audio.click();
  });
  document.querySelectorAll('#rev button').forEach((b) => b.addEventListener('click', () => {
    const v = +b.dataset.rev;
    if (v === train.rev) return;
    if (Math.abs(train.v) > 0.05) { notify('Реверсор переключают только на стоянке.', 'me'); return; }
    if (train.pos > 0) { notify('Сначала контроллер в 0.', 'me'); return; }
    train.rev = v; audio.click();
  }));
  $('#note').addEventListener('click', () => (noteT = 0));
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-act]'); if (b) act(b.dataset.act, b.dataset); });
  document.addEventListener('gesturestart', (e) => e.preventDefault());
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveGame(); });
  addEventListener('keydown', (e) => {
    if (!running || paused) return;
    const k = e.key.toLowerCase(); keys[k] = true;
    if (player.mode === 'cab') {
      if (k === 'w' || k === 'arrowup') setPos(train.pos + 1);
      if (k === 's' || k === 'arrowdown') setPos(train.pos - 1);
      if (k >= '1' && k <= '6') setBrake(+k - 1);
      if (k === ' ') train.pressVigilance();
      if (k === 'h') audio.set(audio.horn, 0.22, 0.03);
    } else if (k === ' ') { fireHeld = true; fire(autoTarget()); }
    if (k === 'e') { const b = document.querySelector('#ctx button'); if (b) b.click(); }
  });
  addEventListener('keyup', (e) => { const k = e.key.toLowerCase(); keys[k] = false; if (k === 'h') audio.set(audio.horn, 0, 0.05); if (k === ' ') fireHeld = false; });
}
function act(a, ds) {
  audio.init();
  switch (a) {
    case 'continue': { const o = store.get(SAVE); if (o) loadGame(o); else newGame(); break; }
    case 'new': newGame(); break;
    case 'loadSafe': { const o = store.get(SAFE); if (o) { loadGame(o); notify('Вы снова в поселении.', 'radio'); } break; }
    case 'help': showHelp(); break;
    case 'close': closeModal(); break;
    case 'inv': showInv(); break;
    case 'map': showMap(); break;
    case 'menu': showMenu(); break;
    case 'log': showLog(); break;
    case 'cam': camMode = camMode === 'chase' ? 'cab' : 'chase'; look.yaw = 0; look.pitch = -0.04; break;
    case 'abort': task = null; $('#prog').hidden = true; break;
    case 'exit': exitCab(); break;
    case 'enter': enterCab(false); break;
    case 'up': { const sp = trainSpots()[+ds.i]; if (sp) climbUp(sp); break; }
    case 'down': { const sp = trainSpots()[+ds.i]; if (sp) climbDown(sp); break; }
    case 'loot': { const L = world.loot.get(ds.id); if (L) startTask('loot', L); break; }
    case 'clear': { const o = world.obstacles.get(ds.id); if (o) startTask('clear', o); break; }
    case 'trade': showTrade('sell'); break;
    case 'tab': showTrade(ds.tab); break;
    case 'sell': sell(ds.w, ds.id, ds.all === '1'); break;
    case 'sellU': sellUnique(ds.uid); break;
    case 'buy': buy(ds.id); break;
    case 'buyAmmo': buyAmmo(ds.a); break;
    case 'buyFuel': buyFuel(+ds.l); break;
    case 'buyUp': buyUp(ds.id); break;
    case 'svc': service(ds.s); break;
    case 'sel': invSel = { w: ds.w, id: ds.id, uid: ds.uid }; showInv(); break;
    case 'use': useItem(ds.w, ds.id); break;
    case 'move': moveItem(ds.w, ds.id, ds.uid, ds.all === '1'); break;
    case 'drop': dropItem(ds.w, ds.id, ds.uid); break;
    case 'takeLoot': takeLoot(ds.to); break;
    case 'opt': opts[ds.k] = !opts[ds.k]; store.set(OPTS, opts); applyOpts(); showMenu(); break;
    case 'quit': saveGame(); running = false; closeModal(); $('#hud').hidden = true; showTitle(); break;
  }
}
function applyOpts() {
  audio.on = opts.sound; if (!opts.sound && audio.ctx) { audio.set(audio.eng, 0); audio.set(audio.hiss, 0); audio.set(audio.wind, 0); }
  if (train) train.vigOn = opts.vig;
  renderer.setPixelRatio(Math.min(devicePixelRatio, opts.hq ? 2 : 1.3)); resize();
}

// ---------------- окна
function openModal(title, body, foot = '', hard = false) {
  paused = true;
  $('#modal h2').textContent = title;
  $('#modal .mbody').innerHTML = body;
  $('#modal .mfoot').innerHTML = foot;
  $('#modal .x').hidden = hard;
  $('#modal').hidden = false;
}
function closeModal() {
  if ($('#modal').hidden) return;
  if (lootPending) return notify('Сначала решите, что взять.', 'me');
  $('#modal').hidden = true; if (running) paused = false;
  saveGame();
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let lootPending = null;
function lootRow(e, i) {
  let name, w = 0, note = '', ic = '📦';
  if (e.money) { name = `Деньги: ${e.money} ₽`; note = 'сразу'; ic = '💵'; }
  else if (e.ammo) { name = `Патроны ${AMMO[e.ammo].n} ×${e.n}`; note = 'сразу'; ic = '🎯'; }
  else if (e.fuel) { name = `Солярка из цистерны: ${e.fuel} л`; note = 'шлангом в бак'; ic = '⛽'; }
  else if (e.unique) { name = e.unique.n; w = e.unique.w; note = 'находка'; ic = '✉️'; }
  else { const it = ITEMS[e.id]; name = it.n + (e.qty > 1 ? ' ×' + e.qty : ''); w = it.w * e.qty; note = itemDesc(e.id); ic = icon(e.id); }
  return `<label class="lrow"><input type="checkbox" id="lt${i}" data-i="${i}" checked><span class="ic">${ic}</span><span>${esc(name)}<i>${esc(note)}</i></span><b>${w ? w.toFixed(1) + ' кг' : ''}</b></label>`;
}
function showLoot(L, items) {
  if (!items.length) { notify(`${L.label}: пусто, всё вынесли до нас.`, 'me'); return; }
  lootPending = items;
  const near = nearTrain();
  openModal(L.label, `<p class="sub">Рюкзак: <b>${kg('pack').toFixed(1)}</b> / ${PACK_MAX} кг${near ? ` · Вагоны: <b>${kg('cargo').toFixed(0)}</b> / ${train.capacity} кг` : ''}</p><div class="list">${items.map(lootRow).join('')}</div>`,
    `<button data-act="takeLoot" data-to="none" class="ghost">Оставить</button>${near ? '<button data-act="takeLoot" data-to="cargo">В вагон</button>' : ''}<button data-act="takeLoot" data-to="pack" class="pri">В рюкзак</button>`, true);
}
function takeLoot(to) {
  const items = lootPending; if (!items) return;
  if (to === 'none') { lootPending = null; closeModal(); return; }
  const picked = [...document.querySelectorAll('.lrow input')].filter((c) => c.checked).map((c) => items[+c.dataset.i]);
  let w = 0; for (const e of picked) w += e.unique ? e.unique.w : e.id ? ITEMS[e.id].w * e.qty : 0;
  const free = to === 'pack' ? PACK_MAX - kg('pack') : train.capacity - kg('cargo');
  if (w > free + 0.01) { notify(`Не влезает: ${w.toFixed(1)} кг, свободно ${free.toFixed(1)} кг. Снимите галочки${to === 'pack' && nearTrain() ? ' или положите в вагон' : ''}.`, 'alert'); return; }
  for (const e of picked) {
    if (e.money) S.money += e.money;
    else if (e.ammo) S.ammo[e.ammo] = (S.ammo[e.ammo] || 0) + e.n;
    else if (e.fuel) { const a = Math.min(e.fuel, train.fuelMax - train.fuel); train.fuel += a; notify(`В бак перекачано ${a.toFixed(0)} л`, 'good'); }
    else if (e.unique) S.uniques.push(Object.assign(e.unique, { where: to }));
    else { add(to, e.id, e.qty); if (WEAPONS[e.id] && to === 'pack' && !S.weapon) S.weapon = e.id; }
  }
  if (picked.length) audio.coin();
  lootPending = null; updateCargo(); closeModal();
}

let invSel = null;
function icon(id) { return WEAPONS[id] ? `<em class="gun">${WEAPONS[id].n}</em>` : ICONS[id] || '📦'; }
function tiles(where) {
  const ids = Object.keys(S[where]).filter((id) => ITEMS[id]).sort((a, b) => ITEMS[a].c.localeCompare(ITEMS[b].c));
  let h = '';
  for (const id of ids) {
    const on = invSel && invSel.w === where && invSel.id === id;
    h += `<button class="tile ${on ? 'on' : ''} ${S.weapon === id && where === 'pack' ? 'eq' : ''}" data-act="sel" data-w="${where}" data-id="${id}"><span>${icon(id)}</span><i>${esc(ITEMS[id].n)}</i>${S[where][id] > 1 ? `<b>${S[where][id]}</b>` : ''}</button>`;
  }
  for (const u of S.uniques) if (u.where === where) {
    const on = invSel && invSel.uid === u.uid;
    h += `<button class="tile ${on ? 'on' : ''}" data-act="sel" data-w="${where}" data-uid="${u.uid}"><span>✉️</span><i>${esc(u.n)}</i></button>`;
  }
  return h || '<p class="sub empty">Пусто</p>';
}
function showInv() {
  const near = nearTrain();
  let det = '<p class="sub">Нажмите на предмет: использовать, переложить или выбросить.</p>';
  if (invSel) {
    const { w, id, uid } = invSel;
    const u = uid ? S.uniques.find((x) => x.uid === uid) : null;
    const it = id ? ITEMS[id] : null;
    if ((it && S[w][id]) || u) {
      const other = w === 'pack' ? 'cargo' : 'pack';
      const use = it ? (it.food ? 'Съесть' : it.hp || it.cure ? 'Принять' : it.fuel ? 'Залить в бак' : it.repair ? 'Починить поезд' : it.weapon ? (S.weapon === id ? '' : 'Взять в руки') : '') : '';
      const needTrain = it && (it.fuel || it.repair);
      det = `<div class="det"><span class="big">${u ? '✉️' : icon(id)}</span><div><b>${esc(u ? u.n : it.n)}${it && S[w][id] > 1 ? ' ×' + S[w][id] : ''}</b><i>${u ? 'Находка — ценится у коллекционеров' : itemDesc(id)} · ${(u ? u.w : it.w).toFixed(2)} кг</i></div>
        <div class="row">${use && (!needTrain || near) && !(it.weapon && w !== 'pack') ? `<button class="pri" data-act="use" data-w="${w}" data-id="${id}">${use}</button>` : ''}
        ${near ? `<button data-act="move" data-w="${w}" data-id="${id || ''}" data-uid="${uid || ''}">${other === 'pack' ? 'В рюкзак' : 'В вагон'}</button>` : ''}
        ${near && it && S[w][id] > 1 ? `<button data-act="move" data-w="${w}" data-id="${id}" data-all="1">Все</button>` : ''}
        <button class="ghost" data-act="drop" data-w="${w}" data-id="${id || ''}" data-uid="${uid || ''}">Выбросить</button></div></div>`;
    } else invSel = null;
  }
  const W = S.weapon ? WEAPONS[S.weapon] : null;
  const ammo = Object.entries(AMMO).map(([k, a]) => `<span class="chip">${a.n}: <b>${S.ammo[k] || 0}</b></span>`).join('');
  openModal('Снаряжение', `<div class="eq"><span class="chip">В руках: <b>${W ? W.n : 'ничего'}</b></span>${ammo}<span class="chip">₽ <b>${S.money}</b></span></div>
    ${det}
    <div class="inv2"><section><h3>Рюкзак · ${kg('pack').toFixed(1)}/${PACK_MAX} кг</h3><div class="grid">${tiles('pack')}</div></section>
    <section class="${near ? '' : 'far'}"><h3>Вагоны · ${kg('cargo').toFixed(0)}/${train.capacity} кг${near ? '' : ' · далеко'}</h3><div class="grid">${tiles('cargo')}</div></section></div>`);
}
function useItem(w, id) {
  const it = ITEMS[id]; if (!it || !S[w][id]) return;
  if (it.weapon) { S.weapon = id; showInv(); return; }
  if (it.food) { if (S.food >= 99) return notify('Вы сыты.', 'me'); S.food = Math.min(100, S.food + it.food); }
  else if (it.hp || it.cure) { S.hp = Math.min(100, S.hp + (it.hp || 0)); if (it.cure && S.infected) { S.infected = false; notify('Инфекция остановлена.', 'good'); } }
  else if (it.fuel) { if (train.fuel >= train.fuelMax - 1) return notify('Бак полный.', 'me'); train.fuel = Math.min(train.fuelMax, train.fuel + it.fuel); }
  else if (it.repair) { if (train.dur >= train.durMax) return notify('Поезд цел.', 'me'); train.dur = Math.min(train.durMax, train.dur + it.repair * train.durMax / 100); }
  else return;
  take(w, id); updateCargo(); audio.click(); showInv();
}
function moveItem(w, id, uid, all) {
  const to = w === 'pack' ? 'cargo' : 'pack';
  if (uid) {
    const u = S.uniques.find((x) => x.uid === uid); if (!u) return;
    if (to === 'pack' && kg('pack') + u.w > PACK_MAX) return notify('Рюкзак полон.', 'alert');
    u.where = to; invSel = { w: to, uid };
  } else {
    let n = all ? S[w][id] : 1;
    const cap = to === 'pack' ? PACK_MAX - kg('pack') : train.capacity - kg('cargo');
    n = Math.min(n, Math.floor((cap + 1e-6) / Math.max(0.01, wOf(id))));
    if (n <= 0) return notify(to === 'pack' ? 'Рюкзак полон.' : 'Вагоны полны.', 'alert');
    take(w, id, n); add(to, id, n);
    if (to === 'pack' && WEAPONS[id] && !S.weapon) S.weapon = id;
    if (!S[w][id]) invSel = { w: to, id };
  }
  updateCargo(); audio.click(); showInv();
}
function dropItem(w, id, uid) {
  if (uid) S.uniques = S.uniques.filter((u) => u.uid !== uid); else take(w, id, 1);
  updateCargo(); showInv();
}

function kindName(st) { return { depot: 'депо', halt: 'остановочный пункт', station: 'станция', town: 'город', settlement: 'поселение' }[st.kind]; }
function showMap() {
  const list = world.nextStations(train.s, 7);
  const rows = list.map((st) => {
    const d = (st.s - train.s) / 1000;
    return `<div class="srow ${st.settle ? 'safe' : ''}"><span class="dot"></span><span><b>${esc(st.name)}</b><i>${kindName(st)}${st.settle ? ' «' + esc(st.settle) + '» — торговля' : ''}</i></span><em>${d < 0.05 ? 'здесь' : d.toFixed(1) + ' км'}</em></div>`;
  }).join('');
  const zone = world.zoneAt(train.s), season = env().season;
  openModal('Схема участка', `<p class="sub">Сейчас: ${ZONE_NAMES[zone]}, ${{ summer: 'лето', autumn: 'осень', winter: 'зима' }[season]} · ${(train.s / 1000 + 117).toFixed(1)} км</p>
    <div class="line">${rows}</div>
    <p class="sub">Убито зомби: <b>${S.kills}</b> · Находок: <b>${S.found}</b> · Станций: <b>${S.visited.length}</b> · День ${S.day}</p>`);
}
function showLog() { openModal('Журнал', `<div class="log">${(S.log || []).map((l) => `<div>${esc(l)}</div>`).join('') || '<p class="sub">Пока пусто.</p>'}</div>`); }
function showMenu() {
  const o = (k, n) => `<button class="tog ${opts[k] ? 'on' : ''}" data-act="opt" data-k="${k}">${n}: ${opts[k] ? 'вкл' : 'выкл'}</button>`;
  openModal('Пауза', `<div class="col"><button data-act="map">Схема участка</button><button data-act="log">Журнал сообщений</button>
    ${o('sound', 'Звук')}${o('vig', 'Бдительность (кнопка РБ)')}${o('hq', 'Высокое качество графики')}
    <button data-act="help">Как играть</button></div>`, '<button data-act="quit">В главное меню</button><button class="pri" data-act="close">Продолжить</button>');
}
function showHelp() {
  openModal('Как играть', `<ol class="help">
  <li><b>В кабине.</b> ПУСК — дизель. Реверсор «В». Кран машиниста (слева) в II — отпуск тормозов, ждите, пока ТЦ упадёт к нулю. Контроллер (справа) вверх — тяга.</li>
  <li><b>Тормоз:</b> кран в V (служебное), затем в III (держит давление). VI — экстренное. Поезд тяжёлый — тормозите заранее.</li>
  <li><b>Боксование</b> на мокрых рельсах, в листопад и снег — держите ПЕСОК. <b>РБ</b> — бдительность: нажмите, когда пищит.</li>
  <li><b>Выйти</b> можно только на стоянке. Снаружи: джойстик слева (до упора — бег), свайп справа — камера, красная кнопка — огонь, касание по зомби — выстрел в него.</li>
  <li>У дверей кабины — <b>«В кабину»</b>, у лестниц вагонов — <b>«На крышу»</b>. С крыши удобно отстреливаться.</li>
  <li>Подойдите к дому, магазину, гаражу, вагону — <b>«Обыскать»</b>. Не двигайтесь, пока идёт обыск.</li>
  <li><b>Рюкзак</b> — 30 кг, остальное складывайте в вагоны, когда стоите рядом с поездом.</li>
  <li>В <b>поселениях</b> торгуют: везде свои цены, одинаковый товар скупают всё дешевле.</li></ol>`, '<button class="pri" data-act="close">Понятно</button>');
}

const CATS = ['food', 'med', 'fuel', 'part', 'weapon', 'goods', 'valuable'];
function currentSettlement() {
  const st = world.nearestStation(train.s);
  if (!st.settle || Math.abs(train.v) > 0.05) return null;
  let s = train.s;
  if (player.mode === 'ground') { toTrack(player.pos.x, player.pos.z, _tt); s = _tt.s; }
  return Math.abs(st.s - s) < st.len / 2 + 80 ? st : null;
}
function settleData(st) {
  const km = train.s / 1000;
  let d = S.settle[st.k];
  if (!d) {
    const r = rngOf(S.seed, 606, st.k), dem = {};
    for (const c of CATS) dem[c] = R(r, 0.7, 1.4);
    const cheap = pick(r, CATS), dear = pick(r, CATS.filter((c) => c !== cheap));
    dem[cheap] = 0.6; dem[dear] = 1.65;
    const pool = Object.keys(ITEMS).filter((id) => !ITEMS[id].rare || r() < 0.25);
    const stock = {};
    for (let i = 0; i < RI(r, 7, 12); i++) { const id = pick(r, pool); if (ITEMS[id].c === 'weapon' && r() < 0.55) continue; stock[id] = (stock[id] || 0) + (ITEMS[id].c === 'weapon' ? 1 : RI(r, 1, 6)); }
    if (st.kind === 'depot') { stock.zapchasti = 4; stock.kanistra = 3; }
    const ups = Object.keys(UPGRADES).sort(() => r() - 0.5).slice(0, st.kind === 'depot' ? 2 : 3);
    const ammo = ['p9', 'p12'].concat(r() < 0.55 ? ['p545'] : [], r() < 0.4 ? ['p762'] : []);
    d = S.settle[st.k] = { dem, cheap, dear, stock, ups, ammo, sold: {}, km };
  } else {
    const f = Math.pow(0.5, Math.abs(km - d.km) / 15);
    for (const k of Object.keys(d.sold)) d.sold[k] *= f;
    d.km = km;
  }
  return d;
}
const sellP = (d, id) => Math.max(1, Math.round(ITEMS[id].v * 0.62 * d.dem[ITEMS[id].c] / (1 + 0.18 * (d.sold[id] || 0))));
const buyP = (d, id) => Math.max(2, Math.round(ITEMS[id].v * 1.35 * Math.max(0.8, d.dem[ITEMS[id].c])));
function showTrade(tab) {
  const st = currentSettlement(); if (!st) return;
  const d = settleData(st), near = nearTrain();
  const tabs = [['sell', 'Продать'], ['buy', 'Купить'], ['up', 'Улучшения'], ['svc', 'Услуги']]
    .map(([k, n]) => `<button class="tab ${k === tab ? 'on' : ''}" data-act="tab" data-tab="${k}">${n}</button>`).join('');
  let h = `<p class="sub">Деньги: <b>${S.money} ₽</b> · Дорого берут: <b>${CAT_NAMES[d.dear]}</b> · Дёшево продают: <b>${CAT_NAMES[d.cheap]}</b></p><div class="tabs">${tabs}</div><div class="list">`;
  if (tab === 'sell') {
    const rows = [];
    for (const w of near ? ['pack', 'cargo'] : ['pack']) for (const id of Object.keys(S[w]).filter((x) => ITEMS[x])) {
      const p = sellP(d, id), sat = (d.sold[id] || 0) > 1.5;
      rows.push(`<div class="trow"><span class="ic">${icon(id)}</span><span>${esc(ITEMS[id].n)} <i>×${S[w][id]} · ${w === 'pack' ? 'рюкзак' : 'вагон'}${sat ? ' · <em class="warn">рынок завален</em>' : ''}</i></span><b>${p} ₽</b><button data-act="sell" data-w="${w}" data-id="${id}">Продать</button>${S[w][id] > 1 ? `<button class="ghost" data-act="sell" data-w="${w}" data-id="${id}" data-all="1">Все</button>` : '<span></span>'}</div>`);
    }
    for (const u of S.uniques) if (near || u.where === 'pack') rows.push(`<div class="trow"><span class="ic">✉️</span><span>${esc(u.n)} <i>находка</i></span><b>${Math.round(u.v * d.dem.valuable * 0.85)} ₽</b><button data-act="sellU" data-uid="${u.uid}">Продать</button><span></span></div>`);
    h += rows.join('') || '<p class="sub">Продавать нечего.</p>';
  } else if (tab === 'buy') {
    const lp = Math.round(100 * 1.1 * d.dem.fuel);
    h += `<div class="trow"><span class="ic">⛽</span><span>Солярка 100 л <i>в баке ${train.fuel.toFixed(0)}/${train.fuelMax}</i></span><b>${lp} ₽</b><button data-act="buyFuel" data-l="100">Купить</button><span></span></div>`;
    for (const a of d.ammo) h += `<div class="trow"><span class="ic">🎯</span><span>Патроны ${AMMO[a].n} ×10 <i>есть ${S.ammo[a] || 0}</i></span><b>${Math.round(AMMO[a].v * 13 * Math.max(0.8, d.dem.weapon))} ₽</b><button data-act="buyAmmo" data-a="${a}">Купить</button><span></span></div>`;
    for (const [id, q] of Object.entries(d.stock)) if (q > 0) h += `<div class="trow"><span class="ic">${icon(id)}</span><span>${esc(ITEMS[id].n)} <i>${itemDesc(id)} · в наличии ${q}</i></span><b>${buyP(d, id)} ₽</b><button data-act="buy" data-id="${id}">Купить</button><span></span></div>`;
  } else if (tab === 'up') {
    for (const id of d.ups) {
      const u = UPGRADES[id], have = id === 'wagon' ? train.wagons >= u.max : train.up[id];
      h += `<div class="trow"><span class="ic">🔧</span><span>${u.n}<i>${u.d}</i></span><b>${u.p} ₽</b><button data-act="buyUp" data-id="${id}" ${have ? 'disabled' : ''}>${have ? 'Есть' : 'Купить'}</button><span></span></div>`;
    }
  } else {
    const miss = Math.max(0, train.durMax - train.dur), rc = Math.ceil(miss / train.durMax * 100 * 2.5);
    h += `<div class="trow"><span class="ic">🛠️</span><span>Ремонт поезда <i>прочность ${(train.dur / train.durMax * 100).toFixed(0)}%</i></span><b>${rc} ₽</b><button data-act="svc" data-s="repair" ${miss < 1 ? 'disabled' : ''}>Починить</button><span></span></div>`;
    h += `<div class="trow"><span class="ic">🩺</span><span>Фельдшер <i>+40 здоровья</i></span><b>30 ₽</b><button data-act="svc" data-s="heal" ${S.hp >= 99 ? 'disabled' : ''}>Лечиться</button><span></span></div>`;
    h += `<div class="trow"><span class="ic">💉</span><span>Вылечить укус <i>${S.infected ? 'вы заражены' : 'вы здоровы'}</i></span><b>70 ₽</b><button data-act="svc" data-s="cure" ${S.infected ? '' : 'disabled'}>Вылечить</button><span></span></div>`;
    h += `<div class="trow"><span class="ic">🛏️</span><span>Ночлег до утра <i>+25 здоровья, горячий ужин</i></span><b>15 ₽</b><button data-act="svc" data-s="sleep">Ночевать</button><span></span></div>`;
  }
  openModal(`${st.kind === 'depot' ? 'Депо' : 'Поселение «' + st.settle + '»'} · ${st.name}`, h + '</div>');
}
function pay(p) { if (S.money < p) { notify('Не хватает денег.', 'alert'); return false; } S.money -= p; audio.coin(); return true; }
function sell(w, id, all) {
  const d = settleData(currentSettlement());
  let n = all ? S[w][id] : 1, got = 0;
  while (n-- > 0 && S[w][id]) { got += sellP(d, id); d.sold[id] = (d.sold[id] || 0) + 1; take(w, id); }
  S.money += got; audio.coin(); updateCargo(); showTrade('sell');
}
function sellUnique(uid) {
  const d = settleData(currentSettlement()), u = S.uniques.find((x) => x.uid === uid); if (!u) return;
  S.money += Math.round(u.v * d.dem.valuable * 0.85); S.uniques = S.uniques.filter((x) => x !== u); audio.coin(); updateCargo(); showTrade('sell');
}
function buy(id) {
  const d = settleData(currentSettlement());
  const to = kg('pack') + wOf(id) <= PACK_MAX ? 'pack' : nearTrain() && kg('cargo') + wOf(id) <= train.capacity ? 'cargo' : null;
  if (!to) return notify('Некуда положить.', 'alert');
  if (!pay(buyP(d, id))) return;
  add(to, id); d.stock[id]--; if (WEAPONS[id] && to === 'pack' && !S.weapon) S.weapon = id; updateCargo(); showTrade('buy');
}
function buyAmmo(a) { const d = settleData(currentSettlement()); if (pay(Math.round(AMMO[a].v * 13 * Math.max(0.8, d.dem.weapon)))) { S.ammo[a] = (S.ammo[a] || 0) + 10; showTrade('buy'); } }
function buyFuel(l) {
  const d = settleData(currentSettlement());
  if (train.fuel > train.fuelMax - 10) return notify('Бак полный.', 'me');
  const a = Math.min(l, train.fuelMax - train.fuel);
  if (pay(Math.round(a * 1.1 * d.dem.fuel))) { train.fuel += a; updateCargo(); showTrade('buy'); }
}
function buyUp(id) {
  const u = UPGRADES[id];
  if (!pay(u.p)) return;
  if (id === 'wagon') train.wagons++;
  else { train.up[id] = true; if (id === 'armor') train.dur += 50; }
  const sv = train.save(); buildTrain(sv); updateCargo();
  notify(`Установлено: ${u.n}`, 'good'); showTrade('up');
}
function service(s) {
  if (s === 'repair') { const miss = train.durMax - train.dur, rc = Math.ceil(miss / train.durMax * 100 * 2.5); if (pay(rc)) train.dur = train.durMax; }
  if (s === 'heal' && pay(30)) S.hp = Math.min(100, S.hp + 40);
  if (s === 'cure' && pay(70)) S.infected = false;
  if (s === 'sleep' && pay(15)) { if (S.time > 7) S.day++; S.time = 7; S.hp = Math.min(100, S.hp + 25); S.food = Math.min(100, S.food + 30); notify('Утро. Можно в путь.', 'radio'); }
  showTrade('svc');
}

// ---------------- интерфейс
function updateHud() {
  const bar = (sel, v, low) => { const el = $(sel); el.querySelector('u').style.width = clamp(v, 0, 100) + '%'; el.classList.toggle('low', v < low); };
  bar('#sHp', S.hp, 30); bar('#sFood', S.food, 20); bar('#sFuel', train.fuel / train.fuelMax * 100, 15); bar('#sDur', train.dur / train.durMax * 100, 30);
  $('#sHp').classList.toggle('inf', S.infected);
  const wName = { clear: 'ясно', cloudy: 'пасмурно', rain: 'дождь', fog: 'туман', snow: 'снег' }[S.weather.type];
  const nx = world.nextStations(train.s + 100, 1)[0];
  $('#info').textContent = `${hhmm()} · ${wName}${nx ? ` · ${nx.name} ${((nx.s - train.s) / 1000).toFixed(1)} км` : ''}`;
  const cab = player.mode === 'cab' && !player.busy;
  $('#cabHud').hidden = !cab; $('#footHud').hidden = cab || player.busy;
  $('#bCam').hidden = !cab;
  if (cab) {
    $('#km .handle').style.top = ((1 - train.pos / 15) * 100) + '%'; $('#km .handle span').textContent = train.pos;
    $('#kr .handle').style.top = (train.brake / 5 * 100) + '%'; $('#kr .handle span').textContent = BRAKE_NAMES[train.brake];
    $('#krHint').textContent = BRAKE_HINT[train.brake];
    document.querySelectorAll('#rev button').forEach((b) => b.classList.toggle('on', +b.dataset.rev === train.rev));
    const eb = $('#bEngine'); eb.textContent = train.engine ? 'СТОП' : train.starting > 0 ? '…' : 'ПУСК'; eb.classList.toggle('on', !train.engine);
    $('#bRB').classList.toggle('alert', train.vigAlert);
    $('#spd').textContent = Math.abs(train.kmh).toFixed(0);
    $('#tm').textContent = train.TM.toFixed(1); $('#tc').textContent = train.TC.toFixed(1);
    lamp('#lD', train.engine); lamp('#lB', train.slip); lamp('#lR', train.vigAlert && Math.floor(performance.now() / 300) % 2 === 0);
    lamp('#lT', train.TC > 0.3); lamp('#lS', train.sanding);
  }
  const W = S.weapon ? WEAPONS[S.weapon] : null;
  const wtxt = W ? `${W.n}<small>${S.ammo[W.ammo] || 0}</small>` : 'нет<small>оружия</small>';
  $('#bWeapon').innerHTML = wtxt; $('#bWeapon2').innerHTML = wtxt;
  let hint = '';
  if (S.tut === 0 && cab) {
    if (!train.engine) hint = 'Нажмите ПУСК — запуск дизеля';
    else if (train.rev !== 1) hint = 'Реверсор — «В» (вперёд)';
    else if (train.brake > 1) hint = 'Кран машиниста (слева) — в II';
    else if (train.TC > 0.4) hint = 'Ждите отпуска тормозов: ТЦ → 0';
    else if (train.pos < 3) hint = 'Контроллер (справа) — вверх на 3–5';
  }
  $('#hint').textContent = hint; $('#hint').hidden = !hint;
  contextActions();
}
function lamp(sel, on) { $(sel).classList.toggle('on', !!on); }
let ctxKey = '';
function contextActions() {
  const out = [];
  const B = (a, label, extra = '', cls = '') => out.push(`<button class="act ${cls}" data-act="${a}" ${extra}>${label}</button>`);
  if (!player.busy && !task) {
    const st = currentSettlement();
    if (player.mode === 'cab') {
      if (Math.abs(train.v) < 0.4) B('exit', 'Выйти');
      if (st) B('trade', 'Торговля', '', 'gold');
    } else if (player.mode === 'roof') {
      trainSpots().forEach((sp, i) => { if (sp.kind === 'ladder' && Math.abs(player.off - sp.top) < 1.6 && (player.d >= 0 ? 1 : -1) === sp.f) B('down', 'Спуститься', `data-i="${i}"`); });
    } else {
      trainSpots().forEach((sp, i) => {
        const d = spotPos(sp).distanceTo(player.pos);
        if (sp.kind === 'door' && d < 2.4) B('enter', 'В кабину', '', 'gold');
        if (sp.kind === 'ladder' && d < 1.8) B('up', 'На крышу', `data-i="${i}"`);
      });
      if (st) B('trade', 'Торговля', '', 'gold');
      for (const o of world.obstacles.values()) { const p = worldPos(o.s, 0); if (p.distanceTo(player.pos) < 6) B('clear', 'Разобрать завал', `data-id="${o.id}"`); }
      const cand = [];
      for (const L of world.loot.values()) {
        if (world.looted.has(L.id)) continue;
        const d = Math.hypot(L.x - player.pos.x, L.z - player.pos.z);
        if (d < 4) cand.push([d, L]);
      }
      cand.sort((a, b) => a[0] - b[0]);
      for (const [, L] of cand.slice(0, 2)) B('loot', 'Обыскать: ' + esc(L.label), `data-id="${L.id}"`);
      if (!out.length) {
        let best = null, bd = 45;
        for (const L of world.loot.values()) { if (world.looted.has(L.id)) continue; const d = Math.hypot(L.x - player.pos.x, L.z - player.pos.z); if (d < bd) { bd = d; best = L; } }
        if (best) out.push(`<div class="farhint">${esc(best.label)} · ${bd.toFixed(0)} м</div>`);
      }
    }
  }
  const k = out.join('');
  if (k !== ctxKey) { ctxKey = k; $('#ctx').innerHTML = k; }
}
const dc = $('#dc'), dx = dc.getContext('2d');
function sizeDash() { const r = dc.getBoundingClientRect(); dc.width = Math.max(1, r.width * devicePixelRatio); dc.height = Math.max(1, r.height * devicePixelRatio); }
function drawDash() {
  audio.engine(train.rpm, train.pos / 15, train.engine);
  if (audio.ctx) {
    const dropping = train.brake >= 4 && train.TM > 0.2;
    audio.set(audio.hiss, dropping ? (train.brake === 5 ? 0.35 : 0.12) : train.brake === 0 && train.TM < 5.5 ? 0.08 : 0);
    audio.set(audio.wind, Math.min(0.25, Math.abs(train.v) / 120));
    audio.set(audio.slipS, train.slip ? 0.15 : 0);
  }
  if ($('#cabHud').hidden) return;
  if (dc.width < 10) sizeDash();
  const W = dc.width, H = dc.height; if (W < 10) return;
  dx.clearRect(0, 0, W, H);
  const cx = W / 2, cy = H * 0.56, r = Math.min(W, H) * 0.44, a0 = Math.PI * 0.75, span = Math.PI * 1.5;
  dx.lineWidth = r * 0.13; dx.lineCap = 'butt';
  dx.strokeStyle = 'rgba(235,226,200,0.15)'; dx.beginPath(); dx.arc(cx, cy, r, a0, a0 + span); dx.stroke();
  const v = clamp(Math.abs(train.kmh) / 120, 0, 1);
  dx.strokeStyle = train.kmh > 95 ? '#d8402c' : '#e7b630'; dx.beginPath(); dx.arc(cx, cy, r, a0, a0 + span * v); dx.stroke();
  dx.strokeStyle = 'rgba(235,226,200,0.6)'; dx.lineWidth = 2;
  for (let i = 0; i <= 12; i++) { const a = a0 + span * i / 12, k = i % 2 ? 0.86 : 0.76; dx.beginPath(); dx.moveTo(cx + Math.cos(a) * r * k, cy + Math.sin(a) * r * k); dx.lineTo(cx + Math.cos(a) * r * 0.93, cy + Math.sin(a) * r * 0.93); dx.stroke(); }
}

// ---------------- загрузка
const TEX = ['red_brick_03', 'white_bricks', 'concrete_panels', 'yellow_plaster', 'wood_trunk_wall', 'wood_plank_wall', 'corrugated', 'rusty_metal_02',
  'sparse_grass', 'withered_grass', 'gravel_floor_02', 'worn_asphalt', 'rough_wood', 'shutter', 'green_metal_rust', 'snow_02', 'grey_plaster'];
function loadTextures(prog) {
  return new Promise((res) => {
    const loader = new THREE.TextureLoader(); let n = 0;
    const maxAniso = renderer.capabilities.getMaxAnisotropy();
    for (const name of TEX) {
      const t = loader.load(`assets/tex/${name}.jpg`, () => { n++; prog(n / TEX.length); if (n === TEX.length) res(); }, undefined, () => { n++; if (n === TEX.length) res(); });
      t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = Math.min(4, maxAniso);
      T[name] = t;
    }
  });
}
function showTitle() { $('#title').hidden = false; $('#bCont').hidden = !store.get(SAVE); }
async function boot() {
  resize(); bindUi(); showTitle();
  requestAnimationFrame(frame);
  let a = 0, b = 0; const pr = () => ($('#loadbar u').style.width = ((a * 0.4 + b * 0.6) * 100) + '%');
  await Promise.all([loadTextures((k) => { a = k; pr(); }), loadChars((k) => { b = k; pr(); })]);
  player = new Player(scene);
  S = newState(12345); buildTrain(null); setupWorld(); train.place(0); player.mode = 'cab';
  orbit.yaw = 0.9; orbit.h = 4; S.time = 18.6;
  $('#title').classList.add('ready');
}
addEventListener('error', (e) => { const el = $('#err'); if (el) { el.hidden = false; el.textContent = 'Ошибка: ' + e.message; } });
addEventListener('unhandledrejection', (e) => { const el = $('#err'); if (el) { el.hidden = false; el.textContent = 'Ошибка загрузки: ' + ((e.reason && e.reason.message) || e.reason); } });
boot();
window.__dbg = () => ({ S, train, world, zombies, player, task });
if ('serviceWorker' in navigator && location.protocol === 'https:' && !location.hostname.endsWith('claude.ai')) navigator.serviceWorker.register('sw.js').catch(() => {});
