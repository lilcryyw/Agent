import * as THREE from '../vendor/three.module.min.js';
import { makeLoco, makeBoxcar, makeTank, LOCO_LEN, BOX_LEN, TANK_LEN } from './models.js';
import { worldPos, clamp, mulberry32 } from './util.js';

export const BRAKE_NAMES = ['I', 'II', 'III', 'IV', 'V', 'VI'];
export const BRAKE_HINT = ['Зарядка', 'Поездное', 'Перекрыша', 'Перекрыша без питания', 'Служебное', 'Экстренное'];
const LOCO_MASS = 138000, G = 9.81;
const _a = new THREE.Vector3(), _b = new THREE.Vector3();

export class Train {
  constructor(scene) {
    this.scene = scene;
    this.s = 40; this.v = 0;
    this.pos = 0; this.rev = 0; this.brake = 2;
    this.TM = 3.6; this.TC = 3.2; this.GR = 6.2;
    this.engine = false; this.starting = 0; this.rpm = 0; this.F = 0;
    this.slip = false; this.sanding = false;
    this.fuel = 650; this.dur = 100;
    this.up = {}; this.wagons = 1; this.cargoKg = 0;
    this.vigT = 70; this.vigAlert = false; this.vigLeft = 0; this.vigOn = true;
    this.events = [];
    this.cars = [];
    this.rng = mulberry32(1347);
  }
  get fuelMax() { return 1000 + (this.up.tank ? 800 : 0); }
  get durMax() { return this.up.armor ? 150 : 100; }
  get capacity() { return 60 + 400 * this.wagons; }
  get kmh() { return this.v * 3.6; }
  get length() { return this.cars.reduce((a, c) => a + c.len + 0.6, 0); }
  get sRear() { return this.s - this.length; }
  mass() { return LOCO_MASS + this.wagons * 24000 + (this.up.tank ? 28000 : 0) + this.cargoKg + this.fuel * 0.84; }

  build() {
    for (const c of this.cars) { this.scene.remove(c.g); }
    this.cars = [];
    const loco = makeLoco('1347');
    this.loco = loco;
    this.cars.push({ g: loco.g, wheels: loco.wheels, len: LOCO_LEN, kind: 'loco' });
    if (this.up.tank) { const t = makeTank(this.rng); this.cars.push({ g: t.g, wheels: t.wheels, len: TANK_LEN, kind: 'tank' }); }
    for (let i = 0; i < this.wagons; i++) { const b = makeBoxcar(this.rng, [0xb0705a, 0x9a6a5a, 0xa87a62][i % 3]); this.cars.push({ g: b.g, wheels: b.wheels, len: BOX_LEN, kind: 'box' }); }
    for (const c of this.cars) this.scene.add(c.g);
    for (const k of ['plow', 'armor', 'light', 'turret']) loco.up[k].visible = !!this.up[k];
    this.place(0);
  }

  // положение вагонов по кривой
  place(dt) {
    let off = 0;
    const turn = this.v * dt / 0.525;
    for (const c of this.cars) {
      const sc = this.s - off - c.len / 2, bl = c.len / 2 - 2.6;
      worldPos(sc + bl, 0, 0, _a); worldPos(sc - bl, 0, 0, _b);
      c.g.position.set((_a.x + _b.x) / 2, 0.64, (_a.z + _b.z) / 2);
      c.g.rotation.y = Math.atan2(-(_a.x - _b.x), -(_a.z - _b.z));
      for (const w of c.wheels) w.rotation.x -= turn;
      c.s0 = this.s - off; c.s1 = this.s - off - c.len;
      off += c.len + 0.6;
    }
  }

  startEngine() {
    if (this.engine || this.starting > 0) return;
    if (this.fuel <= 0) { this.events.push(['msg', 'Нет топлива — дизель не запустится']); return; }
    this.starting = 3.2; this.events.push(['start']);
  }
  stopEngine() { this.engine = false; this.starting = 0; this.pos = 0; }

  pressVigilance() { this.vigAlert = false; this.vigT = 50 + Math.random() * 40; }

  update(dt, env) {
    const mass = this.mass();
    // дизель
    if (this.starting > 0) { this.starting -= dt; if (this.starting <= 0) { this.engine = true; this.events.push(['msg', 'Дизель запущен']); } }
    if (this.engine && this.fuel <= 0) { this.fuel = 0; this.engine = false; this.pos = 0; this.events.push(['msg', 'Топливо кончилось — дизель заглох!']); }
    const rpmT = this.engine ? 350 + this.pos * 43.3 : this.starting > 0 ? 160 : 0;
    this.rpm += (rpmT - this.rpm) * Math.min(1, dt * 1.3);
    const pw = this.up.engine ? 1.15 : 1, k = this.pos / 15;
    let Ft = 0;
    if (this.engine && this.rev !== 0 && this.pos > 0) {
      const vv = Math.max(Math.abs(this.v), 2.2);
      Ft = Math.min(300e3 * k * pw, 2.2e6 * k * pw / vv) * clamp((this.rpm - 300) / 400, 0.2, 1);
    }
    this.F += clamp(Ft - this.F, -220e3 * dt, 80e3 * dt);
    if (this.F < 0) this.F = 0;
    const adh = (env.mu + (this.sanding ? 0.09 : 0)) * LOCO_MASS * G;
    this.slip = this.F > adh && Math.abs(this.v) < 25;
    const Fdrive = this.slip ? adh * 0.55 : this.F;
    if (this.engine) this.fuel = Math.max(0, this.fuel - (0.012 + 0.8 * Math.pow(k, 1.4) * (this.up.engine ? 0.8 : 1)) * dt);
    // компрессор и пневматика
    if (this.engine) this.GR = Math.min(9.0, this.GR + 0.35 * dt); else this.GR = Math.max(0, this.GR - 0.004 * dt);
    this.brakeUpdate(dt);
    const Fb = (this.TC / 3.8) * mass * 1.15;
    const Rr = mass * G * (0.0012 + 0.00005 * Math.abs(this.v)) + 7 * this.v * this.v;
    // движение
    const Fd = Fdrive * this.rev, Fres = Rr + Fb;
    if (this.v === 0) {
      if (Math.abs(Fd) > Fres) this.v += (Fd - Math.sign(Fd) * Fres) / mass * dt;
    } else {
      const nv = this.v + (Fd - Math.sign(this.v) * Fres) / mass * dt;
      this.v = Math.sign(nv) !== Math.sign(this.v) && Math.sign(Fd) !== Math.sign(nv) ? 0 : nv;
    }
    this.s += this.v * dt;
    // КЛУБ: ограничение скорости
    const lim = this.rev < 0 ? 20 : 100;
    if (Math.abs(this.kmh) > lim + 3 && this.brake < 5) { this.brake = 5; this.pos = 0; this.events.push(['alarm', `КЛУБ: превышение ${lim} км/ч — экстренное торможение`]); }
    // бдительность
    if (this.vigOn && Math.abs(this.v) > 0.5) {
      if (!this.vigAlert) { this.vigT -= dt; if (this.vigT <= 0) { this.vigAlert = true; this.vigLeft = 8; this.events.push(['vig']); } }
      else { this.vigLeft -= dt; if (this.vigLeft <= 0) { this.vigAlert = false; this.vigT = 60; this.brake = 5; this.pos = 0; this.events.push(['alarm', 'Не подтверждена бдительность — сработал ЭПК']); } }
    } else if (!this.vigOn) this.vigAlert = false;
    this.place(dt);
  }

  brakeUpdate(dt) {
    const p = this.brake;
    let tm = this.TM;
    const feed = Math.max(0, this.GR - 0.3);
    if (p === 0) tm = Math.min(Math.min(5.6, feed), tm + 1.6 * dt);
    else if (p === 1) { const tgt = Math.min(5.0, feed); tm += clamp(tgt - tm, -0.15 * dt, 0.6 * dt); }
    else if (p === 2) tm -= 0.002 * dt;
    else if (p === 3) tm -= 0.01 * dt;
    else if (p === 4) tm = Math.max(0, tm - 0.28 * dt);
    else tm = Math.max(0, tm - 2.4 * dt);
    this.TM = Math.max(0, tm);
    const target = clamp((5.0 - this.TM) * 2.5, 0, 3.8);
    if (target > this.TC) this.TC = Math.min(target, this.TC + (p === 5 ? 2.6 : 0.7) * dt);
    else this.TC = Math.max(target, this.TC - (p === 0 ? 0.9 : 0.35) * dt);
  }

  save() {
    return { s: this.s, v: this.v, pos: this.pos, rev: this.rev, brake: this.brake, TM: this.TM, TC: this.TC, GR: this.GR, engine: this.engine,
      fuel: this.fuel, dur: this.dur, up: this.up, wagons: this.wagons };
  }
  load(o) { Object.assign(this, o); this.F = 0; this.rpm = this.engine ? 350 : 0; }
}
