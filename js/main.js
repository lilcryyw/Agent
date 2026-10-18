import * as THREE from '../vendor/three.module.min.js';
import { T, rngOf, R, RI, pick, wpick, clamp, lerp, worldPos, toTrack, frameAt } from './util.js';
import { World, ZONE_DENSITY, ZONE_NAMES } from './world.js';
import { Train, BRAKE_NAMES, BRAKE_HINT } from './train.js';
import { Zombies, ZTYPES } from './zombies.js';
import { makeHuman } from './models.js';
import { Audio } from './audio.js';
import { ITEMS, CAT_NAMES, WEAPONS, AMMO, LOOT, WAGON_CARGO, LOOT_TIME, UPGRADES, makeUnique } from './data.js';

const $ = (s) => document.querySelector(s);
const SAVE = 'mp_save_v1', SAFE = 'mp_safe_v1', OPTS = 'mp_opts_v1';
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

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  sizeDash();
}
addEventListener('resize', resize);

// звёзды и осадки
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
// трассеры и кровь
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
let S = null, world = null, train = null, zombies = new Zombies(scene);
let running = false, paused = true, camMode = 'chase';
const orbit = { yaw: 0.35, h: 8, dist: 19 }, look = { yaw: 0, pitch: -0.04 };
let looter = { active: false, pos: new THREE.Vector3() };
const looterMesh = makeHuman({ skin: 0xe0b89a, shirt: 0x3a4a2a, pants: 0x2a2a30, hat: 0x2a2a2a });
let fireCd = 0, spawnT = 1, saveT = 10, hudT = 0, turretCd = 0, arrivedK = -1, warnedK = -1, guardT = 0;
const camPos = new THREE.Vector3(), camLook = new THREE.Vector3();

function newState(seed) {
  return {
    v: 1, seed, time: 7.3, day: 1, hp: 100, food: 85, infected: false, money: 150,
    inv: { tushenka: 3, voda: 2, bint: 2, pm: 1, kanistra: 1 }, uniques: [], ammo: { p9: 36, p12: 0, p545: 0, p762: 0 }, weapon: 'pm',
    kills: 0, found: 0, looted: [], cleared: [], settle: {}, visited: [], weather: { type: 'cloudy', t: 5 }, maxS: 0, tut: false,
  };
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
  buildTrain(null);
  setupWorld();
  updateCargo();
  start();
  toast('Депо «Узловая». Город пал. Впереди — тысячи километров пути.', 'big');
}
function snapshot() {
  S.looted = [...world.looted]; S.cleared = [...world.cleared]; S.train = train.save();
  return JSON.parse(JSON.stringify(S));
}
function saveGame() { if (S && running) store.set(SAVE, snapshot()); }
function loadGame(o) {
  S = Object.assign(newState(o.seed), o);
  buildTrain(o.train);
  setupWorld();
  updateCargo();
  start();
}
function start() {
  running = true; paused = false; looter.active = false; lootPending = null;
  orbit.yaw = 0.35; orbit.h = 8; orbit.dist = 19; camMode = 'chase';
  $('#title').hidden = true; $('#hud').hidden = false; closeModal(); resize();
  audio.init();
  try { navigator.wakeLock && navigator.wakeLock.request('screen').catch(() => {}); } catch (e) { /* нет */ }
}

// ---------------- груз
function itemW(id) { return ITEMS[id] ? ITEMS[id].w : 0; }
function cargoKg() {
  let w = 0; for (const [id, q] of Object.entries(S.inv)) w += itemW(id) * q;
  for (const u of S.uniques) w += u.w; return w;
}
function updateCargo() { train.cargoKg = cargoKg(); }
function addItem(id, q = 1) { S.inv[id] = (S.inv[id] || 0) + q; }
function takeItem(id, q = 1) { S.inv[id] -= q; if (S.inv[id] <= 0) delete S.inv[id]; if (WEAPONS[id] && !S.inv[id] && S.weapon === id) S.weapon = ownedWeapons()[0] || null; }
function ownedWeapons() { return Object.keys(WEAPONS).filter((w) => S.inv[w] > 0); }

// ---------------- сообщения
function toast(text, cls = '') {
  const d = document.createElement('div'); d.className = 'msg ' + cls; d.textContent = text;
  const log = $('#log'); log.prepend(d);
  while (log.children.length > 4) log.lastChild.remove();
  setTimeout(() => d.classList.add('out'), cls === 'big' ? 5500 : 3500);
  setTimeout(() => d.remove(), cls === 'big' ? 6200 : 4200);
}
function hurtFlash(k = 1) { const h = $('#hurt'); h.style.opacity = Math.min(0.85, 0.35 * k + 0.2); clearTimeout(h._t); h._t = setTimeout(() => (h.style.opacity = 0), 160); }

// ---------------- игровой контекст для зомби
const zctx = {
  train: null, looter: null, cam: camera.position,
  groundH(s, d) {
    if (Math.abs(d) < 2.2) return 0.4;
    const st = world.nearestStation(s);
    if (Math.abs(st.s - s) < st.len / 2 && d * st.side > 1.95 && d * st.side < 6.5) return 1.1;
    return 0;
  },
  hurtTrain(d) { if (!running) return; train.dur -= d; if (d > 1.5) { audio.thud(); hurtFlash(0.4); } if (train.dur <= 0) gameOver('Поезд разбит. Зомби взяли его штурмом.'); },
  hurtPlayer(d, outside) {
    if (!running) return;
    S.hp -= d * (outside ? 1 : 0.6); hurtFlash(1); audio.thud();
    if (outside && !S.infected && Math.random() < 0.1) { S.infected = true; toast('Вас укусили! Нужны антибиотики.', 'bad'); }
    if (S.hp <= 0) gameOver(outside ? 'Вы погибли на вылазке.' : 'Зомби ворвались в кабину.');
  },
  onKill(z, how) { S.kills++; },
  sound(kind, z, dist) { if (kind === 'groan') audio.groan(1 - dist / 45); else if (kind === 'splat') audio.splat(); },
  scream(z) {
    audio.scream(); toast('Крикун созывает мертвецов!', 'bad');
    const r = Math.random, p = z.h.root.position;
    for (let i = 0; i < RI(r, 4, 8); i++) { const a = r() * 6.28, d = R(r, 25, 60); zombies.spawn(r() < 0.4 ? 'runner' : 'walker', p.x + Math.cos(a) * d, p.z + Math.sin(a) * d, train.s / 1000, r); }
  },
};

// ---------------- игровой цикл
let last = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  if (running && !paused) step(dt);
  if (train) { updateCamera(dt); renderer.render(scene, camera); }
  hudT -= dt; if (running && hudT <= 0) { hudT = 0.1; updateHud(); }
  if (running) drawDash();
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
  if (looter.active) { train.pos = 0; }
  train.update(dt, E);
  for (const ev of train.events.splice(0)) {
    if (ev[0] === 'msg') toast(ev[1]);
    else if (ev[0] === 'alarm') { toast(ev[1], 'bad'); audio.alarm(); }
    else if (ev[0] === 'vig') audio.beep();
    else if (ev[0] === 'start') audio.starter();
  }
  if (!S.tut && train.kmh > 15) { S.tut = true; toast('Поехали! Стреляйте касанием по зомби. Останавливайтесь у домов, чтобы обыскать их.', 'big'); }
  // завалы на пути
  for (const o of world.obstacles.values()) {
    if (o.s - 1.6 < train.s && o.s > train.s - 3) {
      if (train.kmh > 15) {
        const dmg = { tree: 10, car: 16, barricade: 22 }[o.type] * (train.up.plow ? 0.3 : 1) * Math.min(2, train.kmh / 30);
        zctx.hurtTrain(dmg); train.v *= 0.55; audio.thud(); audio.splat();
        toast(`Протаранили: ${o.label.toLowerCase()} (−${dmg.toFixed(0)}% прочности)`, 'bad');
        world.removeObstacle(o);
      } else if (train.v > 0) {
        train.v = 0; train.s = o.s - 1.6; train.F = 0; toast(`Путь перекрыт: ${o.label.toLowerCase()}. Нужно расчистить.`, 'bad');
      }
      break;
    }
  }
  // стыки рельсов
  const j0 = Math.floor(prevS / 25), j1 = Math.floor(train.s / 25);
  if (j0 !== j1 && train.v > 1) {
    const back = train.s - j1 * 25;
    audio.clack(train.v, AXLES.filter((a) => a < 40 && a > back).map((a) => a - back));
  }
  world.update(train.s);
  // время, погода
  const hrs = dt / 40;
  S.time += hrs; if (S.time >= 24) { S.time -= 24; S.day++; }
  S.weather.t -= hrs;
  if (S.weather.t <= 0) newWeather(E.season);
  if (E.season === 'winter' && S.weather.type === 'rain') S.weather.type = 'snow';
  if (E.season !== 'winter' && S.weather.type === 'snow') S.weather.type = 'rain';
  // потребности
  S.food = Math.max(0, S.food - dt * 0.06);
  if (S.food <= 0) { S.hp -= dt * 0.25; if (S.hp <= 0) return gameOver('Вы умерли от голода.'); }
  if (S.infected) { S.hp -= dt * 0.12; if (S.hp <= 0) return gameOver('Инфекция взяла своё.'); }
  if (S.food > 60 && !S.infected) S.hp = Math.min(100, S.hp + dt * 0.04);
  // зомби
  spawn(dt);
  zctx.train = train; zctx.looter = looter.active ? looter : null;
  zombies.update(dt, zctx);
  guards(dt);
  turret(dt);
  updateLooter(dt);
  fx(dt);
  // станции
  const st = world.nearestStation(train.s);
  if (st.settle && st.k !== warnedK && st.s - train.s < 1200 && st.s - train.s > 300) { warnedK = st.k; toast(`Впереди ${st.kind === 'depot' ? 'депо' : `поселение «${st.settle}»`} — станция ${st.name}. Там торгуют и чинят.`, 'good'); }
  if (Math.abs(train.v) < 0.05 && Math.abs(st.s - train.s) < st.len / 2 + 40 && arrivedK !== st.k) {
    arrivedK = st.k;
    if (!S.visited.includes(st.name)) S.visited.push(st.name);
    toast((st.settle ? 'Поселение «' + st.settle + '», ' : 'Станция ') + st.name, 'good');
    if (st.settle) store.set(SAFE, snapshot());
  }
  S.maxS = Math.max(S.maxS, train.s);
  saveT -= dt; if (saveT <= 0) { saveT = 15; saveGame(); }
}
// расстояния осей от головы поезда (для перестука)
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
  spawnT -= dt; if (spawnT > 0) return; spawnT = 0.8;
  const zone = world.zoneAt(train.s + 60), km = train.s / 1000;
  const night = S.time < 5.5 || S.time > 21;
  const dens = ZONE_DENSITY[zone] * (night ? 1.6 : 1) * (S.weather.type === 'fog' ? 1.25 : 1);
  const want = Math.min(44, Math.round(dens * 24 * (1 + km / 150)));
  if (zombies.alive >= want || zone === 'settlement' || train.s < 400) return;
  const r = Math.random, n = RI(r, 1, Math.min(6, 2 + Math.floor(km / 15)));
  let s, d;
  if (Math.abs(train.v) < 1) {
    if (looter.active && r() < 0.6) { toTrack(looter.pos.x, looter.pos.z, _tt); s = _tt.s + R(r, -60, 60); d = _tt.d + (r() < 0.5 ? -1 : 1) * R(r, 25, 60); }
    else { s = train.s + R(r, -130, 140); d = (r() < 0.5 ? -1 : 1) * R(r, 18, 75); }
  } else { s = train.s + R(r, 70, 280); d = (r() < 0.5 ? -1 : 1) * R(r, 6, 90); }
  if (world.zoneAt(s) === 'settlement') return;
  const season = world.seasonAt(s);
  for (let i = 0; i < n; i++) {
    const p = worldPos(s + R(r, -8, 8), d + R(r, -8, 8));
    zombies.spawn(zombies.pickType(r, km, season), p.x, p.z, km, r);
  }
}
const _tt = {};
// охрана поселений отстреливает мертвецов
function guards(dt) {
  guardT -= dt; if (guardT > 0) return; guardT = 0.7;
  for (const z of zombies.list) {
    if (z.state === 'dead' || z.state === 'fly') continue;
    toTrack(z.h.root.position.x, z.h.root.position.z, _tt);
    if (world.zoneAt(_tt.s) === 'settlement' && Math.random() < 0.5) { zombies.kill(z); if (Math.random() < 0.6) audio.shot('rifle'); break; }
  }
}
// пулемёт на крыше
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

// ---------------- вылазки
function cabDoor(side) { return worldPos(train.s - 6.3, side * 2.0); }
function sortie(kind, obj) {
  if (looter.active) return;
  const side = kind === 'loot' ? (obj.d >= 0 ? 1 : -1) : 1;
  const home = cabDoor(side);
  const tgt = kind === 'loot' ? new THREE.Vector3(obj.x, 0, obj.z) : worldPos(obj.s - 2.2, 1.0);
  const total = kind === 'loot' ? (LOOT_TIME[obj.type] || 6) : 8;
  looter = { active: true, kind, obj, phase: 'go', pos: home.clone(), home, tgt, t: 0, total, h: looterMesh };
  looterMesh.root.position.copy(home); scene.add(looterMesh.root);
  train.pos = 0; audio.click();
  $('#prog').hidden = false;
  $('#prog .pl').textContent = kind === 'loot' ? 'Вылазка: ' + obj.label : 'Расчистка: ' + obj.label.toLowerCase();
  toast(kind === 'loot' ? 'Прикрывайте себя огнём — зомби идут на шум.' : 'Разбираем завал. Держите мертвецов на расстоянии.');
}
function abortSortie() { if (looter.active && looter.phase !== 'back') { looter.phase = 'back'; looter.abort = true; } }
function updateLooter(dt) {
  if (!looter.active) return;
  const L = looter, h = L.h, tgt = L.phase === 'back' ? L.home : L.tgt;
  const dx = tgt.x - L.pos.x, dz = tgt.z - L.pos.z, dist = Math.hypot(dx, dz);
  if (L.phase === 'search') {
    L.t += dt; h.rA.rotation.x = -1 + Math.sin(L.t * 6) * 0.6; h.lA.rotation.x = -0.8 + Math.cos(L.t * 6) * 0.5;
    h.lL.rotation.x = h.rL.rotation.x = 0;
    if (L.t >= L.total) { L.phase = 'back'; audio.click(); }
  } else if (dist > 0.5) {
    const sp = 4.6 * (S.hp < 30 ? 0.7 : 1), st = Math.min(dist, sp * dt);
    L.pos.x += dx / dist * st; L.pos.z += dz / dist * st;
    h.root.rotation.y = Math.atan2(-dx, -dz);
    L.ph = (L.ph || 0) + dt * 14;
    h.lL.rotation.x = Math.sin(L.ph) * 0.7; h.rL.rotation.x = -Math.sin(L.ph) * 0.7;
    h.lA.rotation.x = -Math.sin(L.ph) * 0.5; h.rA.rotation.x = -1.2;
  } else if (L.phase === 'go') L.phase = 'search';
  else if (L.phase === 'back') return finishSortie();
  toTrack(L.pos.x, L.pos.z, _tt);
  L.pos.y = zctx.groundH(_tt.s, _tt.d);
  h.root.position.copy(L.pos);
  $('#prog .pb u').style.width = (100 * Math.min(1, L.t / L.total)).toFixed(0) + '%';
}
function finishSortie() {
  const L = looter; L.active = false; scene.remove(L.h.root); $('#prog').hidden = true;
  const frac = Math.min(1, L.t / L.total);
  if (L.kind === 'clear') {
    if (frac >= 1) { world.removeObstacle(L.obj); toast('Путь свободен.', 'good'); } else toast('Расчистка не закончена.');
    return;
  }
  if (frac <= 0.05) { toast('Вернулись ни с чем.'); return; }
  world.looted.add(L.obj.id);
  let items = rollLoot(L.obj);
  if (frac < 1) items = items.slice(0, Math.max(1, Math.floor(items.length * frac)));
  S.found += items.length;
  showLoot(L.obj, items);
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

// ---------------- выстрелы
const _p = new THREE.Vector3(), _o = new THREE.Vector3();
function pickZombie(sx, sy) {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  let best = null, bd = 1e9;
  for (const z of zombies.list) {
    if (z.state === 'dead' || z.state === 'fly') continue;
    _p.copy(z.h.root.position); _p.y += 1.1 * z.size;
    const wd = camera.position.distanceTo(_p);
    _p.project(camera); if (_p.z > 1) continue;
    const px = (_p.x + 1) / 2 * W, py = (1 - _p.y) / 2 * H, dd = Math.hypot(px - sx, py - sy);
    const rad = Math.max(40, 1100 * z.size / wd);
    if (dd < rad && dd < bd) { bd = dd; best = z; }
  }
  return best;
}
function shotOrigin(v) {
  if (looter.active) return v.copy(looter.pos).add(new THREE.Vector3(0, 1.4, 0));
  return train.loco.g.localToWorld(v.set(1.2, 3.8, -7.8));
}
function fire(z) {
  if (!S.weapon || fireCd > 0) return;
  const W = WEAPONS[S.weapon];
  if ((S.ammo[W.ammo] || 0) <= 0) { if (fireCd <= 0) { toast('Нет патронов ' + AMMO[W.ammo].n); audio.click(); } fireCd = 0.5; return; }
  S.ammo[W.ammo]--; fireCd = W.rate; audio.shot(W.snd);
  shotOrigin(_o);
  _p.copy(z.h.root.position); _p.y += 1.1 * z.size;
  const d3 = _o.distanceTo(_p), r = Math.random;
  const hitP = clamp(1.05 - d3 / W.range * 0.6, 0.12, 0.97);
  let dmg = 0, hits = 0;
  for (let i = 0; i < W.pellets; i++) if (r() < hitP) { hits++; dmg += W.dmg * (W.pellets > 1 ? clamp(1 - d3 / W.range * 0.7, 0.2, 1) : 1); }
  const head = hits > 0 && r() < 0.18;
  if (hits) {
    if (zombies.hit(z, dmg, head)) zctx.onKill(z);
    bleed(_p); tracer(_o, _p);
    if (head) hitMark(true);
  } else tracer(_o, _p.clone().add(new THREE.Vector3(R(r, -1.5, 1.5), R(r, -0.5, 1.2), R(r, -1.5, 1.5))));
}
function tracer(a, b) {
  const l = tracers.find((t) => !t.visible) || tracers[0];
  const p = l.geometry.attributes.position; p.setXYZ(0, a.x, a.y, a.z); p.setXYZ(1, b.x, b.y, b.z); p.needsUpdate = true;
  l.visible = true; l.userData.t = 0.06;
}
function bleed(p) {
  const pa = blood.geometry.attributes.position, u = blood.userData;
  for (let k = 0; k < 8; k++) {
    const i = u.i = (u.i + 1) % BLOOD_N;
    pa.setXYZ(i, p.x, p.y, p.z); u.v.set([R(Math.random, -2, 2), R(Math.random, 0, 3), R(Math.random, -2, 2)], i * 3); u.life[i] = 0.8;
  }
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
  if (pointer.down && !pointer.drag && S.weapon && WEAPONS[S.weapon].auto) { const z = pickZombie(pointer.x, pointer.y); if (z) fire(z); }
}

// ---------------- камера, свет, небо
const _fw = new THREE.Vector3();
function updateCamera(dt) {
  const L = train.loco.g, yaw = L.rotation.y;
  if (camMode === 'cab') {
    L.localToWorld(camPos.set(0.55, 3.9, -9.05));
    camera.position.copy(camPos);
    const a = yaw + look.yaw, p = look.pitch;
    camera.lookAt(camPos.x - Math.sin(a) * Math.cos(p) * 50, camPos.y + Math.sin(p) * 50, camPos.z - Math.cos(a) * Math.cos(p) * 50);
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
  $('#cabframe').hidden = camMode !== 'cab';
  // день и ночь
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

// ---------------- конец игры
function gameOver(why) {
  if (!running) return;
  running = false; paused = true;
  saveGame(); store.del(SAVE);
  const safe = store.get(SAFE);
  openModal('Конец пути', `<p class="lead">${why}</p>
    <div class="grid2"><div><b>${(S.maxS / 1000).toFixed(1)}</b> км пройдено</div><div><b>${S.kills}</b> зомби уничтожено</div>
    <div><b>${S.found}</b> находок</div><div><b>${S.day}</b> дн. в пути</div></div>`,
  (safe ? '<button class="pri" data-act="loadSafe">Вернуться в последнее поселение</button>' : '') + '<button data-act="new">Новый рейс</button>', true);
}

// ---------------- управление
const pointer = { down: false, drag: false, x: 0, y: 0, sx: 0, sy: 0, id: null };
canvas.addEventListener('pointerdown', (e) => {
  if (!running || paused) return;
  pointer.down = true; pointer.drag = false; pointer.id = e.pointerId;
  pointer.x = pointer.sx = e.clientX; pointer.y = pointer.sy = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => {
  if (!pointer.down || e.pointerId !== pointer.id) return;
  const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
  pointer.x = e.clientX; pointer.y = e.clientY;
  if (!pointer.drag && Math.hypot(pointer.x - pointer.sx, pointer.y - pointer.sy) > 12) pointer.drag = true;
  if (pointer.drag) {
    if (camMode === 'cab') { look.yaw = clamp(look.yaw - dx * 0.005, -1.6, 1.6); look.pitch = clamp(look.pitch - dy * 0.004, -0.6, 0.5); }
    else { orbit.yaw -= dx * 0.008; orbit.h = clamp(orbit.h + dy * 0.04, 2.5, 30); }
  }
});
const endPtr = (e) => {
  if (!pointer.down || e.pointerId !== pointer.id) return;
  if (!pointer.drag && running && !paused) { const z = pickZombie(pointer.x, pointer.y); if (z) fire(z); }
  pointer.down = false;
};
canvas.addEventListener('pointerup', endPtr); canvas.addEventListener('pointercancel', endPtr);
canvas.addEventListener('wheel', (e) => { orbit.dist = clamp(orbit.dist + e.deltaY * 0.02, 8, 45); }, { passive: true });

function locked() { if (looter.active) { toast('Машинист на вылазке — поезд стоит.'); return true; } return false; }
function setPos(p) {
  p = clamp(Math.round(p), 0, 15);
  if (p === train.pos) return;
  if (p > 0 && locked()) return;
  if (p > 0 && !train.engine) { toast('Сначала запустите дизель — кнопка ПУСК.'); return; }
  if (p > 0 && train.rev === 0) { toast('Реверсор в нуле — выберите направление «В».'); return; }
  train.pos = p; audio.click();
}
function setBrake(b) { b = clamp(Math.round(b), 0, 5); if (b !== train.brake) { train.brake = b; audio.click(); } }
function lever(el, n, get, set, invert) {
  const calc = (e) => { const r = (el.querySelector('.rail') || el).getBoundingClientRect(); const k = clamp((e.clientY - r.top) / r.height, 0, 1); return invert ? (1 - k) * (n - 1) : k * (n - 1); };
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
  // насечки
  const km = $('#km .notches'); for (let i = 15; i >= 0; i--) km.insertAdjacentHTML('beforeend', `<i>${i % 5 === 0 ? i : ''}</i>`);
  const kr = $('#kr .notches'); BRAKE_NAMES.forEach((n) => kr.insertAdjacentHTML('beforeend', `<i>${n}</i>`));
  lever($('#km'), 16, () => train.pos, (v) => setPos(v), true);
  lever($('#kr'), 6, () => train.brake, (v) => setBrake(v), false);
  hold($('#bHorn'), () => audio.set(audio.horn, 0.22, 0.03), () => audio.set(audio.horn, 0, 0.05));
  hold($('#bSand'), () => (train.sanding = true), () => (train.sanding = false));
  $('#bRB').addEventListener('click', () => { train.pressVigilance(); audio.click(); });
  $('#bEngine').addEventListener('click', () => {
    if (train.engine) { if (Math.abs(train.v) > 0.5) { toast('На ходу дизель не глушат.'); return; } train.stopEngine(); toast('Дизель остановлен.'); }
    else train.startEngine();
  });
  $('#bWeapon').addEventListener('click', () => {
    const own = ownedWeapons(); if (!own.length) { toast('Нет оружия'); return; }
    S.weapon = own[(own.indexOf(S.weapon) + 1) % own.length]; audio.click();
  });
  document.querySelectorAll('#rev button').forEach((b) => b.addEventListener('click', () => {
    const v = +b.dataset.rev;
    if (v === train.rev) return;
    if (Math.abs(train.v) > 0.05) { toast('Реверсор переключают только на стоянке.'); return; }
    if (train.pos > 0) { toast('Сначала контроллер в 0.'); return; }
    train.rev = v; audio.click();
  }));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    act(b.dataset.act, b.dataset);
  });
  document.addEventListener('gesturestart', (e) => e.preventDefault());
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveGame(); });
  addEventListener('keydown', (e) => {
    if (!running || paused) return;
    const k = e.key.toLowerCase();
    if (k === 'w' || k === 'arrowup') setPos(train.pos + 1);
    if (k === 's' || k === 'arrowdown') setPos(train.pos - 1);
    if (k >= '1' && k <= '6') setBrake(+k - 1);
    if (k === ' ') train.pressVigilance();
    if (k === 'h') audio.horn && audio.set(audio.horn, 0.22, 0.03);
  });
  addEventListener('keyup', (e) => { if (e.key.toLowerCase() === 'h' && audio.horn) audio.set(audio.horn, 0, 0.05); });
}

function act(a, ds) {
  audio.init();
  switch (a) {
    case 'continue': { const o = store.get(SAVE); if (o) loadGame(o); else newGame(); break; }
    case 'new': newGame(); break;
    case 'loadSafe': { const o = store.get(SAFE); if (o) { loadGame(o); toast('Вы снова в поселении.', 'good'); } break; }
    case 'help': showHelp(); break;
    case 'close': closeModal(); break;
    case 'inv': showInv(); break;
    case 'map': showMap(); break;
    case 'menu': showMenu(); break;
    case 'cam': camMode = camMode === 'chase' ? 'cab' : 'chase'; look.yaw = 0; look.pitch = -0.04; break;
    case 'abort': abortSortie(); break;
    case 'loot': { const L = world.loot.get(ds.id); if (L) sortie('loot', L); break; }
    case 'clear': { const o = world.obstacles.get(ds.id); if (o) sortie('clear', o); break; }
    case 'trade': showTrade('sell'); break;
    case 'tab': showTrade(ds.tab); break;
    case 'sell': sell(ds.id, ds.all === '1'); break;
    case 'sellU': sellUnique(ds.uid); break;
    case 'buy': buy(ds.id); break;
    case 'buyAmmo': buyAmmo(ds.a); break;
    case 'buyFuel': buyFuel(+ds.l); break;
    case 'buyUp': buyUp(ds.id); break;
    case 'svc': service(ds.s); break;
    case 'use': useItem(ds.id); break;
    case 'drop': takeItem(ds.id, 1); updateCargo(); showInv(); break;
    case 'dropU': S.uniques = S.uniques.filter((u) => u.uid !== ds.uid); updateCargo(); showInv(); break;
    case 'takeLoot': takeLoot(); break;
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
  if (lootPending) return toast('Сначала решите, что взять.');
  $('#modal').hidden = true; if (running) paused = false;
  saveGame();
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let lootPending = null;
function lootRow(e, i) {
  let name, w = 0, note = '';
  if (e.money) { name = `Деньги: ${e.money} ₽`; note = 'сразу'; }
  else if (e.ammo) { name = `Патроны ${AMMO[e.ammo].n} ×${e.n}`; note = 'сразу'; }
  else if (e.fuel) { name = `Солярка из цистерны: ${e.fuel} л`; note = 'в бак'; }
  else if (e.unique) { name = e.unique.n; w = e.unique.w; note = 'находка'; }
  else { const it = ITEMS[e.id]; name = it.n + (e.qty > 1 ? ' ×' + e.qty : ''); w = it.w * e.qty; note = CAT_NAMES[it.c]; }
  return `<label class="lrow"><input type="checkbox" id="lt${i}" data-i="${i}" checked><span>${esc(name)}</span><em>${note}</em><b>${w ? w.toFixed(1) + ' кг' : ''}</b></label>`;
}
function showLoot(L, items) {
  if (!items.length) { toast(`${L.label}: пусто, уже кто-то вынес.`); return; }
  lootPending = items;
  const free = train.capacity - cargoKg();
  openModal(L.label, `<p class="sub">Свободно в вагонах: <b>${free.toFixed(0)} кг</b> из ${train.capacity}</p><div class="list">${items.map(lootRow).join('')}</div>`,
    '<button data-act="takeLoot" class="pri">Забрать отмеченное</button>', true);
}
function takeLoot() {
  const items = lootPending; if (!items) return;
  const picked = [...document.querySelectorAll('.lrow input')].filter((c) => c.checked).map((c) => items[+c.dataset.i]);
  let w = 0; for (const e of picked) w += e.unique ? e.unique.w : e.id ? ITEMS[e.id].w * e.qty : 0;
  const free = train.capacity - cargoKg();
  if (w > free + 0.01) { toast(`Не влезает: нужно ${w.toFixed(0)} кг, свободно ${free.toFixed(0)} кг. Снимите отметки.`, 'bad'); return; }
  for (const e of picked) {
    if (e.money) S.money += e.money;
    else if (e.ammo) S.ammo[e.ammo] = (S.ammo[e.ammo] || 0) + e.n;
    else if (e.fuel) { const add = Math.min(e.fuel, train.fuelMax - train.fuel); train.fuel += add; toast(`В бак залито ${add.toFixed(0)} л`, 'good'); }
    else if (e.unique) S.uniques.push(e.unique);
    else { addItem(e.id, e.qty); if (WEAPONS[e.id] && !S.weapon) S.weapon = e.id; }
  }
  if (picked.length) audio.coin();
  lootPending = null; updateCargo(); closeModal();
}

function invRows() {
  const groups = {};
  for (const [id, q] of Object.entries(S.inv)) { const it = ITEMS[id]; if (!it) continue; (groups[it.c] = groups[it.c] || []).push([id, q, it]); }
  let h = '';
  for (const c of Object.keys(CAT_NAMES)) {
    if (!groups[c]) continue;
    h += `<h3>${CAT_NAMES[c]}</h3>`;
    for (const [id, q, it] of groups[c]) {
      const use = it.food ? 'Съесть' : it.hp || it.cure ? 'Принять' : it.fuel ? 'В бак' : it.repair ? 'Починить' : WEAPONS[id] ? (S.weapon === id ? 'В руках' : 'Взять') : '';
      h += `<div class="irow"><span>${esc(it.n)} <i>×${q}</i></span><em>${(it.w * q).toFixed(1)} кг</em>${use ? `<button data-act="use" data-id="${id}" ${S.weapon === id ? 'disabled' : ''}>${use}</button>` : '<span></span>'}<button class="ghost" data-act="drop" data-id="${id}">Выбросить</button></div>`;
    }
  }
  if (S.uniques.length) {
    h += `<h3>${CAT_NAMES.unique}</h3>`;
    for (const u of S.uniques) h += `<div class="irow"><span>${esc(u.n)}</span><em>${u.w} кг</em><span></span><button class="ghost" data-act="dropU" data-uid="${u.uid}">Выбросить</button></div>`;
  }
  return h || '<p class="sub">Вагоны пусты.</p>';
}
function showInv() {
  const ammo = Object.entries(AMMO).map(([k, a]) => `<span class="chip">${a.n}: <b>${S.ammo[k] || 0}</b></span>`).join('');
  openModal('Груз и снаряжение', `<p class="sub">Груз: <b>${cargoKg().toFixed(0)}</b> / ${train.capacity} кг · Деньги: <b>${S.money} ₽</b></p><div class="chips">${ammo}</div>${invRows()}`);
}
function useItem(id) {
  const it = ITEMS[id]; if (!it || !S.inv[id]) return;
  if (WEAPONS[id]) { S.weapon = id; showInv(); return; }
  if (it.food) { if (S.food >= 99) return toast('Вы сыты.'); S.food = Math.min(100, S.food + it.food); }
  else if (it.hp || it.cure) { S.hp = Math.min(100, S.hp + (it.hp || 0)); if (it.cure && S.infected) { S.infected = false; toast('Инфекция остановлена.', 'good'); } }
  else if (it.fuel) { if (train.fuel >= train.fuelMax - 1) return toast('Бак полный.'); train.fuel = Math.min(train.fuelMax, train.fuel + it.fuel); }
  else if (it.repair) { if (train.dur >= train.durMax) return toast('Поезд цел.'); train.dur = Math.min(train.durMax, train.dur + it.repair * train.durMax / 100); }
  else return;
  takeItem(id); updateCargo(); audio.click(); showInv();
}

function kindName(st) { return { depot: 'депо', halt: 'остановочный пункт', station: 'станция', town: 'город', settlement: 'поселение' }[st.kind]; }
function showMap() {
  const list = world.nextStations(train.s, 7);
  const rows = list.map((st) => {
    const d = (st.s - train.s) / 1000;
    return `<div class="srow ${st.settle ? 'safe' : ''}"><span class="dot"></span><span><b>${esc(st.name)}</b><i>${kindName(st)}${st.settle ? ' «' + esc(st.settle) + '» — торговля' : ''}</i></span><em>${d < 0 ? 'здесь' : d.toFixed(1) + ' км'}</em></div>`;
  }).join('');
  const zone = world.zoneAt(train.s), season = env().season;
  openModal('Схема участка', `<p class="sub">Сейчас: ${ZONE_NAMES[zone]}, ${{ summer: 'лето', autumn: 'осень', winter: 'зима' }[season]} · ${(train.s / 1000 + 117).toFixed(1)} км</p>
    <div class="line">${rows}</div>
    <p class="sub">Убито зомби: <b>${S.kills}</b> · Находок: <b>${S.found}</b> · Посещено станций: <b>${S.visited.length}</b> · День ${S.day}</p>`);
}
function showMenu() {
  const o = (k, n) => `<button class="tog ${opts[k] ? 'on' : ''}" data-act="opt" data-k="${k}">${n}: ${opts[k] ? 'вкл' : 'выкл'}</button>`;
  openModal('Пауза', `<div class="col">${o('sound', 'Звук')}${o('vig', 'Бдительность (кнопка РБ)')}${o('hq', 'Высокое качество графики')}
    <button data-act="help">Как управлять поездом</button></div>`, '<button data-act="quit">Выйти в главное меню</button><button class="pri" data-act="close">Продолжить</button>');
}
function showHelp() {
  openModal('Как управлять', `<ol class="help">
  <li><b>ПУСК</b> — запуск дизеля. Компрессор накачает главные резервуары (ГР).</li>
  <li><b>Реверсор</b> — «В» вперёд, «Н» назад. Переключается только на стоянке при контроллере в 0.</li>
  <li><b>Кран машиниста №395</b>: I — зарядка (быстрый отпуск), II — поездное (отпуск тормозов), III — перекрыша (держит давление), IV — перекрыша без питания, V — служебное торможение, VI — экстренное.</li>
  <li>Тормоза отпущены, когда стрелка <b>ТЦ</b> упала к нулю, а <b>ТМ</b> около 5.</li>
  <li><b>Контроллер</b> 0–15 — позиции тяги. Резко не набирайте: на мокрых рельсах, в листопад и снег колёса <b>боксуют</b> — держите <b>ПЕСОК</b>.</li>
  <li>Тормозной путь длинный: с 80 км/ч поезд проходит сотни метров. Завалы видно издалека — тормозите заранее. Свыше 15 км/ч завал таранится с повреждением.</li>
  <li><b>РБ</b> — бдительность: когда пищит и мигает, нажмите, иначе сработает экстренное торможение. Отключается в меню.</li>
  <li>Касание по зомби — выстрел. Проведите пальцем — повернуть камеру. «Вид» — из кабины.</li>
  <li>Остановитесь у дома, магазина, гаража или брошенного вагона — появится кнопка <b>Обыскать</b>. Пока вы на вылазке, зомби идут на вас.</li>
  <li>В <b>поселениях</b> торгуют: цены везде разные, а одинаковый товар скупают всё дешевле. Редкие вещи и находки ценятся.</li></ol>`, '<button class="pri" data-act="close">Понятно</button>');
}

// ---------------- торговля
const CATS = ['food', 'med', 'fuel', 'part', 'weapon', 'goods', 'valuable'];
function currentSettlement() {
  const st = world.nearestStation(train.s);
  return st.settle && Math.abs(st.s - train.s) < st.len / 2 + 80 && Math.abs(train.v) < 0.05 ? st : null;
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
  const d = settleData(st);
  const tabs = [['sell', 'Продать'], ['buy', 'Купить'], ['up', 'Улучшения'], ['svc', 'Услуги']]
    .map(([k, n]) => `<button class="tab ${k === tab ? 'on' : ''}" data-act="tab" data-tab="${k}">${n}</button>`).join('');
  let h = `<p class="sub">Деньги: <b>${S.money} ₽</b> · Здесь дорого берут: <b>${CAT_NAMES[d.dear]}</b> · Дёшево продают: <b>${CAT_NAMES[d.cheap]}</b></p><div class="tabs">${tabs}</div><div class="list">`;
  if (tab === 'sell') {
    const ids = Object.keys(S.inv).filter((id) => ITEMS[id]);
    for (const id of ids) {
      const p = sellP(d, id), sat = (d.sold[id] || 0) > 1.5;
      h += `<div class="trow"><span>${esc(ITEMS[id].n)} <i>×${S.inv[id]}</i>${sat ? '<i class="warn"> рынок завален</i>' : ''}</span><b>${p} ₽</b><button data-act="sell" data-id="${id}">Продать</button>${S.inv[id] > 1 ? `<button class="ghost" data-act="sell" data-id="${id}" data-all="1">Все</button>` : '<span></span>'}</div>`;
    }
    for (const u of S.uniques) h += `<div class="trow"><span>${esc(u.n)} <i>находка</i></span><b>${Math.round(u.v * d.dem.valuable * 0.85)} ₽</b><button data-act="sellU" data-uid="${u.uid}">Продать</button><span></span></div>`;
    if (!ids.length && !S.uniques.length) h += '<p class="sub">Продавать нечего.</p>';
  } else if (tab === 'buy') {
    const lp = Math.round(100 * 1.1 * d.dem.fuel);
    h += `<div class="trow"><span>Солярка 100 л <i>в бак: ${train.fuel.toFixed(0)}/${train.fuelMax}</i></span><b>${lp} ₽</b><button data-act="buyFuel" data-l="100">Купить</button><span></span></div>`;
    for (const a of d.ammo) h += `<div class="trow"><span>Патроны ${AMMO[a].n} ×10 <i>есть: ${S.ammo[a] || 0}</i></span><b>${Math.round(AMMO[a].v * 13 * Math.max(0.8, d.dem.weapon))} ₽</b><button data-act="buyAmmo" data-a="${a}">Купить</button><span></span></div>`;
    for (const [id, q] of Object.entries(d.stock)) if (q > 0) h += `<div class="trow"><span>${esc(ITEMS[id].n)} <i>в наличии ${q}</i></span><b>${buyP(d, id)} ₽</b><button data-act="buy" data-id="${id}">Купить</button><span></span></div>`;
  } else if (tab === 'up') {
    for (const id of d.ups) {
      const u = UPGRADES[id], have = id === 'wagon' ? train.wagons >= u.max : train.up[id];
      h += `<div class="trow"><span>${u.n}<i>${u.d}</i></span><b>${u.p} ₽</b><button data-act="buyUp" data-id="${id}" ${have ? 'disabled' : ''}>${have ? 'Есть' : 'Купить'}</button><span></span></div>`;
    }
  } else {
    const miss = Math.max(0, train.durMax - train.dur), rc = Math.ceil(miss / train.durMax * 100 * 2.5);
    h += `<div class="trow"><span>Ремонт поезда <i>прочность ${(train.dur / train.durMax * 100).toFixed(0)}%</i></span><b>${rc} ₽</b><button data-act="svc" data-s="repair" ${miss < 1 ? 'disabled' : ''}>Починить</button><span></span></div>`;
    h += `<div class="trow"><span>Фельдшер <i>+40 здоровья</i></span><b>30 ₽</b><button data-act="svc" data-s="heal" ${S.hp >= 99 ? 'disabled' : ''}>Лечиться</button><span></span></div>`;
    h += `<div class="trow"><span>Вылечить укус <i>${S.infected ? 'вы заражены' : 'вы здоровы'}</i></span><b>70 ₽</b><button data-act="svc" data-s="cure" ${S.infected ? '' : 'disabled'}>Вылечить</button><span></span></div>`;
    h += `<div class="trow"><span>Ночлег до утра <i>+25 здоровья, горячий ужин</i></span><b>15 ₽</b><button data-act="svc" data-s="sleep">Ночевать</button><span></span></div>`;
  }
  openModal(`${st.kind === 'depot' ? 'Депо' : 'Поселение «' + st.settle + '»'} · ${st.name}`, h + '</div>');
}
function pay(p) { if (S.money < p) { toast('Не хватает денег.', 'bad'); return false; } S.money -= p; audio.coin(); return true; }
function sell(id, all) {
  const d = settleData(currentSettlement());
  let n = all ? S.inv[id] : 1, got = 0;
  while (n-- > 0 && S.inv[id]) { got += sellP(d, id); d.sold[id] = (d.sold[id] || 0) + 1; takeItem(id); }
  S.money += got; audio.coin(); updateCargo(); showTrade('sell');
}
function sellUnique(uid) {
  const d = settleData(currentSettlement()), u = S.uniques.find((x) => x.uid === uid); if (!u) return;
  S.money += Math.round(u.v * d.dem.valuable * 0.85); S.uniques = S.uniques.filter((x) => x !== u); audio.coin(); updateCargo(); showTrade('sell');
}
function buy(id) {
  const d = settleData(currentSettlement());
  if (cargoKg() + ITEMS[id].w > train.capacity) return toast('Нет места в вагонах.', 'bad');
  if (!pay(buyP(d, id))) return;
  addItem(id); d.stock[id]--; if (WEAPONS[id] && !S.weapon) S.weapon = id; updateCargo(); showTrade('buy');
}
function buyAmmo(a) { const d = settleData(currentSettlement()); if (pay(Math.round(AMMO[a].v * 13 * Math.max(0.8, d.dem.weapon)))) { S.ammo[a] = (S.ammo[a] || 0) + 10; showTrade('buy'); } }
function buyFuel(l) {
  const d = settleData(currentSettlement());
  if (train.fuel > train.fuelMax - 10) return toast('Бак полный.');
  const add = Math.min(l, train.fuelMax - train.fuel);
  if (pay(Math.round(add * 1.1 * d.dem.fuel))) { train.fuel += add; updateCargo(); showTrade('buy'); }
}
function buyUp(id) {
  const u = UPGRADES[id];
  if (!pay(u.p)) return;
  if (id === 'wagon') train.wagons++;
  else { train.up[id] = true; if (id === 'armor') train.dur += 50; }
  const sv = train.save(); buildTrain(sv); computeAxles(); updateCargo();
  toast(`Установлено: ${u.n}`, 'good'); showTrade('up');
}
function service(s) {
  if (s === 'repair') { const miss = train.durMax - train.dur, rc = Math.ceil(miss / train.durMax * 100 * 2.5); if (pay(rc)) train.dur = train.durMax; }
  if (s === 'heal' && pay(30)) S.hp = Math.min(100, S.hp + 40);
  if (s === 'cure' && pay(70)) S.infected = false;
  if (s === 'sleep' && pay(15)) { if (S.time > 7) S.day++; S.time = 7; S.hp = Math.min(100, S.hp + 25); S.food = Math.min(100, S.food + 30); toast('Утро. Можно в путь.', 'good'); }
  showTrade('svc');
}

// ---------------- интерфейс
function updateHud() {
  const bar = (sel, v, lowAt) => { const el = $(sel); el.querySelector('u').style.width = clamp(v, 0, 100) + '%'; el.classList.toggle('low', v < lowAt); };
  bar('#sHp', S.hp, 30); bar('#sFood', S.food, 20);
  $('#sHp').classList.toggle('inf', S.infected);
  $('#sFuel span').textContent = train.fuel.toFixed(0) + ' л';
  $('#sFuel').classList.toggle('low', train.fuel < train.fuelMax * 0.15);
  $('#sDur span').textContent = (train.dur / train.durMax * 100).toFixed(0) + '%';
  $('#sDur').classList.toggle('low', train.dur < train.durMax * 0.3);
  $('#sMoney span').textContent = S.money;
  const hh = Math.floor(S.time), mm = Math.floor((S.time - hh) * 60);
  const wName = { clear: 'ясно', cloudy: 'пасмурно', rain: 'дождь', fog: 'туман', snow: 'снег' }[S.weather.type];
  $('#where').textContent = `День ${S.day} · ${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')} · ${wName} · ${ZONE_NAMES[world.zoneAt(train.s)]}`;
  const nx = world.nextStations(train.s + 100, 1)[0];
  if (nx) $('#next').textContent = `→ ${nx.name}${nx.settle ? ' · торговля' : ''} · ${((nx.s - train.s) / 1000).toFixed(1)} км`;
  // рычаги
  const kmH = $('#km'), kh = kmH.querySelector('.handle');
  kh.style.top = ((1 - train.pos / 15) * 100) + '%'; kh.querySelector('span').textContent = train.pos;
  const kr = $('#kr .handle'); kr.style.top = (train.brake / 5 * 100) + '%'; kr.querySelector('span').textContent = BRAKE_NAMES[train.brake];
  $('#krHint').textContent = BRAKE_HINT[train.brake];
  document.querySelectorAll('#rev button').forEach((b) => b.classList.toggle('on', +b.dataset.rev === train.rev));
  const eb = $('#bEngine'); eb.textContent = train.engine ? 'СТОП' : train.starting > 0 ? 'ПУСК…' : 'ПУСК'; eb.classList.toggle('on', !train.engine);
  const w = S.weapon ? WEAPONS[S.weapon] : null;
  $('#bWeapon').innerHTML = w ? `${w.n}<small>${S.ammo[w.ammo] || 0}</small>` : 'нет<small>оружия</small>';
  $('#bWeapon').classList.toggle('low', w && !(S.ammo[w.ammo] > 0));
  $('#bRB').classList.toggle('alert', train.vigAlert);
  lamp('#lD', train.engine); lamp('#lB', train.slip); lamp('#lR', train.vigAlert && Math.floor(performance.now() / 300) % 2 === 0);
  lamp('#lF', train.fuel < train.fuelMax * 0.15); lamp('#lT', train.TC > 0.3); lamp('#lS', train.sanding);
  // подсказка обучения и действия
  let hint = '';
  if (!S.tut) {
    if (!train.engine) hint = 'Нажмите ПУСК — запуск дизеля';
    else if (train.rev !== 1) hint = 'Реверсор — в положение «В» (вперёд)';
    else if (train.brake > 1) hint = 'Кран машиниста — в положение II (отпуск тормозов)';
    else if (train.TC > 0.4) hint = 'Ждите отпуска: стрелка ТЦ должна упасть к нулю';
    else if (train.pos < 3) hint = 'Контроллер ▲ — наберите 3–5 позицию';
    else hint = 'Разгоняйтесь. Для торможения — кран в V, затем в III';
  }
  $('#tip').textContent = hint; $('#tip').hidden = !hint || looter.active;
  actions();
}
function _side(L, right) { toTrack(L.x, L.z, _tt); const isR = _tt.d >= 0; return right ? (isR ? ' →' : '') : (isR ? '' : '← '); }
function lamp(sel, on) { $(sel).classList.toggle('on', !!on); }
let actKey = '';
function actions() {
  const out = [];
  if (!looter.active && Math.abs(train.v) < 0.05) {
    const st = currentSettlement();
    if (st) out.push(`<button class="act trade" data-act="trade">Торговля и ремонт</button>`);
    for (const o of world.obstacles.values()) if (o.s - train.s > -2 && o.s - train.s < 30) out.push(`<button class="act" data-act="clear" data-id="${o.id}">Расчистить путь</button>`);
    const cand = [];
    for (const L of world.loot.values()) {
      if (world.looted.has(L.id)) continue;
      toTrack(L.x, L.z, _tt);
      const ds = _tt.s > train.s ? _tt.s - train.s : _tt.s < train.sRear ? train.sRear - _tt.s : 0;
      const dist = Math.hypot(ds, _tt.d);
      if (dist < 50) cand.push([dist, L]);
    }
    cand.sort((a, b) => a[0] - b[0]);
    for (const [dist, L] of cand.slice(0, 3)) out.push(`<button class="act" data-act="loot" data-id="${L.id}">${_side(L)}Обыскать: ${esc(L.label)}<small>${dist.toFixed(0)} м${_side(L, 1)}</small></button>`);
  }
  const k = out.join('');
  if (k !== actKey) { actKey = k; $('#actions').innerHTML = k; }
}

// ---------------- приборная панель
const dc = $('#dc'), dx = dc.getContext('2d');
function sizeDash() { const r = dc.getBoundingClientRect(); dc.width = Math.max(1, r.width * devicePixelRatio); dc.height = Math.max(1, r.height * devicePixelRatio); }
function dial(cx, cy, r, max, step, label, needles, unit) {
  const a0 = Math.PI * 0.75, span = Math.PI * 1.5;
  dx.fillStyle = '#e9e0c6'; dx.beginPath(); dx.arc(cx, cy, r, 0, 7); dx.fill();
  dx.lineWidth = r * 0.08; dx.strokeStyle = '#2b302c'; dx.stroke();
  dx.fillStyle = '#1d1f1c'; dx.strokeStyle = '#1d1f1c'; dx.textAlign = 'center'; dx.textBaseline = 'middle';
  dx.font = `bold ${Math.round(r * 0.2)}px "PT Sans Narrow", sans-serif`;
  for (let v = 0; v <= max + 1e-6; v += step / 2) {
    const a = a0 + span * v / max, major = Math.abs(v / step - Math.round(v / step)) < 1e-6;
    dx.lineWidth = major ? r * 0.04 : r * 0.02;
    dx.beginPath(); dx.moveTo(cx + Math.cos(a) * r * (major ? 0.72 : 0.8), cy + Math.sin(a) * r * (major ? 0.72 : 0.8)); dx.lineTo(cx + Math.cos(a) * r * 0.9, cy + Math.sin(a) * r * 0.9); dx.stroke();
    if (major) dx.fillText(String(Math.round(v)), cx + Math.cos(a) * r * 0.54, cy + Math.sin(a) * r * 0.54);
  }
  dx.font = `bold ${Math.round(r * 0.18)}px "PT Sans Narrow", sans-serif`; dx.fillText(label, cx, cy + r * 0.45);
  if (unit) { dx.font = `${Math.round(r * 0.14)}px "PT Sans Narrow", sans-serif`; dx.fillText(unit, cx, cy - r * 0.32); }
  for (const [v, col] of needles) {
    const a = a0 + span * clamp(v, 0, max) / max;
    dx.strokeStyle = col; dx.lineWidth = r * 0.06; dx.lineCap = 'round';
    dx.beginPath(); dx.moveTo(cx - Math.cos(a) * r * 0.12, cy - Math.sin(a) * r * 0.12); dx.lineTo(cx + Math.cos(a) * r * 0.82, cy + Math.sin(a) * r * 0.82); dx.stroke();
  }
  dx.fillStyle = '#2b302c'; dx.beginPath(); dx.arc(cx, cy, r * 0.08, 0, 7); dx.fill();
}
function drawDash() {
  if (dc.width < 10) sizeDash();
  const W = dc.width, H = dc.height; if (W < 10) return;
  dx.clearRect(0, 0, W, H);
  const r1 = H * 0.46, r2 = H * 0.34;
  dial(r1 + 4, H / 2, r1, 120, 20, Math.abs(train.kmh).toFixed(0), [[Math.abs(train.kmh), '#c0261a']], 'км/ч');
  dial(r1 * 2 + r2 + 14, H / 2 + 2, r2, 10, 2, 'ТМ·ГР', [[train.GR, '#c0261a'], [train.TM, '#1d1f1c']]);
  dial(r1 * 2 + r2 * 3 + 22, H / 2 + 2, r2, 6, 1, 'ТЦ', [[train.TC, '#1d1f1c']]);
  // обороты дизеля
  const x0 = r1 * 2 + r2 * 4 + 32, bw = Math.max(10, W - x0 - 6);
  if (bw > 12) {
    dx.fillStyle = '#e9e0c6'; dx.font = `bold ${Math.round(H * 0.13)}px "PT Sans Narrow", sans-serif`; dx.textAlign = 'left';
    dx.fillText('ДИЗЕЛЬ ' + Math.round(train.rpm) + ' об/мин', x0, H * 0.2);
    dx.fillStyle = '#2b302c'; dx.fillRect(x0, H * 0.32, bw, H * 0.12);
    dx.fillStyle = '#e2b62a'; dx.fillRect(x0, H * 0.32, bw * clamp(train.rpm / 1000, 0, 1), H * 0.12);
    dx.fillStyle = '#e9e0c6'; dx.fillText('ТЯГА ' + (train.F / 1000).toFixed(0) + ' кН', x0, H * 0.62);
    dx.fillStyle = '#2b302c'; dx.fillRect(x0, H * 0.73, bw, H * 0.12);
    dx.fillStyle = train.slip ? '#d8402c' : '#5fc46a'; dx.fillRect(x0, H * 0.73, bw * clamp(train.F / 300e3, 0, 1), H * 0.12);
  }
  // звук
  audio.engine(train.rpm, train.pos / 15, train.engine);
  if (audio.ctx) {
    const dropping = train.brake >= 4 && train.TM > 0.2;
    audio.set(audio.hiss, dropping ? (train.brake === 5 ? 0.35 : 0.12) : train.brake === 0 && train.TM < 5.5 ? 0.08 : 0);
    audio.set(audio.wind, Math.min(0.25, Math.abs(train.v) / 120));
    audio.set(audio.slipS, train.slip ? 0.15 : 0);
  }
}

// ---------------- загрузка
const TEX = ['red_brick_03', 'white_bricks', 'concrete_panels', 'yellow_plaster', 'wood_trunk_wall', 'wood_plank_wall', 'corrugated', 'rusty_metal_02',
  'sparse_grass', 'withered_grass', 'gravel_floor_02', 'worn_asphalt', 'rough_wood', 'shutter', 'green_metal_rust', 'snow_02', 'grey_plaster'];
function loadTextures(done) {
  const loader = new THREE.TextureLoader(); let n = 0;
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  for (const name of TEX) {
    const t = loader.load(`assets/tex/${name}.jpg`, () => { n++; $('#loadbar u').style.width = (n / TEX.length * 100) + '%'; if (n === TEX.length) done(); },
      undefined, () => { n++; if (n === TEX.length) done(); });
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = Math.min(4, maxAniso);
    T[name] = t;
  }
}
function showTitle() {
  $('#title').hidden = false;
  const has = !!store.get(SAVE);
  $('#bCont').hidden = !has;
}
function boot() {
  resize(); bindUi(); showTitle();
  loadTextures(() => {
    $('#title').classList.add('ready');
    // фон заставки: мир за окном
    S = newState(12345); buildTrain(null); setupWorld(); train.place(0);
    orbit.yaw = 0.9; orbit.h = 4; S.time = 18.6;
  });
  requestAnimationFrame(frame);
}
window.addEventListener('error', (e) => { const el = $('#err'); if (el) { el.hidden = false; el.textContent = 'Ошибка: ' + e.message; } });
boot();
window.__dbg = () => ({ S, train, world, zombies, looter });
if ('serviceWorker' in navigator && location.protocol === 'https:' && !location.hostname.endsWith('claude.ai')) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
