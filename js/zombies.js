import * as THREE from '../vendor/three.module.min.js';
import { makeHuman } from './models.js';
import { toTrack, worldPos, frameAt, pick, R, wpick, clamp } from './util.js';

export const ZTYPES = {
  walker:   { n: 'Ходок', hp: 40, sp: [0.9, 1.5], dmg: 4, tdmg: 0.6, w: 10, minKm: 0 },
  worker:   { n: 'Путеец', hp: 50, sp: [1.0, 1.4], dmg: 4, tdmg: 0.6, w: 1.5, minKm: 0, vest: true },
  runner:   { n: 'Бегун', hp: 30, sp: [4.2, 5.4], dmg: 3, tdmg: 0.4, w: 3, minKm: 2 },
  fat:      { n: 'Толстяк', hp: 170, sp: [0.6, 0.9], dmg: 8, tdmg: 3, w: 1.5, minKm: 4, scale: [1.55, 1.05, 1.5], trainHit: 4 },
  screamer: { n: 'Крикун', hp: 35, sp: [1.8, 2.4], dmg: 3, tdmg: 0.4, w: 0.8, minKm: 5 },
  soldier:  { n: 'Солдат', hp: 100, sp: [1.1, 1.5], dmg: 6, tdmg: 1, w: 1.2, minKm: 7, helmet: true },
  frozen:   { n: 'Обмороженный', hp: 70, sp: [0.7, 1.1], dmg: 5, tdmg: 0.8, w: 0, minKm: 0, winter: 4 },
  giant:    { n: 'Громила', hp: 520, sp: [1.4, 1.8], dmg: 16, tdmg: 7, w: 0.25, minKm: 18, scale: [1.6, 1.6, 1.6], trainHit: 12 },
};
const SKIN = [0x9aab8a, 0xa8b098, 0x8a9a7a, 0xb0a890, 0x98a088];
const SHIRT = [0x3a4048, 0x4a3a2a, 0x1f3a8a, 0x5a2a2a, 0x6a6a5a, 0x2a2a2a, 0x7a6a8a, 0x4a5a32, 0xd8d8d0, 0x8a5a3a];
const PANTS = [0x2a2a2a, 0x2a3048, 0x3a3a2a, 0x4a3a2a, 0x1f2a5a];
const _t = {}, _v = new THREE.Vector3();

export class Zombies {
  constructor(scene) { this.scene = scene; this.list = []; }
  get alive() { let n = 0; for (const z of this.list) if (z.state !== 'dead' && z.state !== 'fly') n++; return n; }

  pickType(r, km, season) {
    const list = [];
    for (const [k, t] of Object.entries(ZTYPES)) {
      let w = km >= t.minKm ? t.w : 0;
      if (t.winter) w = season === 'winter' ? t.winter : 0;
      if (k === 'runner') w *= 1 + km / 30;
      if (w > 0) list.push([k, w]);
    }
    return wpick(r, list);
  }

  spawn(type, x, z, km, r) {
    const t = ZTYPES[type];
    const look = {
      skin: type === 'frozen' ? 0xb8d0e0 : pick(r, SKIN),
      shirt: type === 'soldier' ? 0x4a5a32 : type === 'frozen' ? 0x8a9aa8 : pick(r, SHIRT),
      pants: type === 'soldier' ? 0x3a4a2a : pick(r, PANTS),
      eyes: type === 'frozen' ? 0x60c0ff : type === 'giant' ? 0xffaa00 : 0xff3020,
      helmet: t.helmet, scale: t.scale,
      stripes: t.vest ? 0xff7a1a : (r() < 0.12 ? 0xf0f0f0 : null),
      hat: type === 'walker' && r() < 0.15 ? 0x4a4038 : null,
      sleeve: r() < 0.2 ? false : true,
    };
    const h = makeHuman(look);
    h.root.position.set(x, 0, z);
    this.scene.add(h.root);
    const hpMul = 1 + km / 120;
    const zb = { type, t, h, hp: t.hp * hpMul, max: t.hp * hpMul, sp: R(r, t.sp[0], t.sp[1]), phase: r() * 6, state: 'walk',
      atk: 0, groan: 2 + r() * 8, screamed: false, vel: null, deadT: 0, off: 0, side: 1, size: t.scale ? t.scale[1] : 1 };
    this.list.push(zb);
    return zb;
  }

  hit(z, dmg, head) {
    if (z.state === 'dead' || z.state === 'fly') return false;
    z.hp -= dmg * (head ? 2.2 : 1);
    z.h.body.position.x = 0.04;
    if (z.hp <= 0) { this.kill(z); return true; }
    return false;
  }
  kill(z, fling) {
    if (fling) {
      z.state = 'fly'; z.vel = fling; z.deadT = 0;
    } else { z.state = 'dead'; z.deadT = 0; }
  }

  // главный цикл: движение, атаки, столкновения с поездом
  update(dt, c) {
    const tr = c.train, sF = tr.s, sR = tr.sRear, v = tr.v;
    for (let i = this.list.length - 1; i >= 0; i--) {
      const z = this.list[i], p = z.h.root.position;
      toTrack(p.x, p.z, _t);
      const zs = _t.s, zd = _t.d;
      if (z.state === 'dead' || z.state === 'fly') {
        z.deadT += dt;
        if (z.state === 'fly') {
          z.vel.y -= 9.8 * dt; p.addScaledVector(z.vel, dt);
          z.h.body.rotation.x += dt * 8; z.h.body.rotation.z += dt * 3;
          if (p.y <= 0 && z.vel.y < 0) { p.y = 0; z.state = 'dead'; z.h.body.rotation.set(-Math.PI / 2, 0, 0); z.h.body.position.y = 0.2; }
        } else {
          z.h.body.rotation.x = Math.max(-Math.PI / 2, z.h.body.rotation.x - dt * 5);
          z.h.body.position.y = Math.max(0.1, 0.25 * (-z.h.body.rotation.x / (Math.PI / 2)));
        }
        if (z.deadT > 7 || zs < sR - 150) this.remove(i);
        continue;
      }
      if (zs < sR - 130 || zs > sF + 450 || Math.abs(zd) > 280) { this.remove(i); continue; }
      z.h.body.position.x *= 0.8;
      z.groan -= dt;
      if (z.groan <= 0) { z.groan = 4 + Math.random() * 9; const dist = Math.hypot(p.x - c.cam.x, p.z - c.cam.z); if (dist < 45) c.sound('groan', z, dist); }
      if (z.state === 'attack') {
        // висит на поезде
        if (z.onLooter) {
          const L = c.looter;
          if (!L || !L.active) { z.state = 'walk'; z.onLooter = false; }
          else {
            z.atk -= dt; this.anim(z, dt, 2.5, true);
            if (z.atk <= 0) { z.atk = 1.1; c.hurtPlayer(z.t.dmg, true); }
            const lp = L.pos; if (Math.hypot(lp.x - p.x, lp.z - p.z) > 1.4) { z.state = 'walk'; z.onLooter = false; }
            continue;
          }
        } else {
          const s = sF + z.off;
          worldPos(s, z.side * 1.85, 0, _v); p.set(_v.x, z.off > -tr.cars[0].len ? 0.9 : 0.9, _v.z);
          frameAt(s, _t); z.h.root.rotation.y = _t.yaw - z.side * Math.PI / 2 + Math.PI;
          this.anim(z, dt, 2.5, true);
          z.atk -= dt;
          if (z.atk <= 0) {
            z.atk = 1;
            c.hurtTrain(z.t.tdmg * (tr.up.armor ? 0.5 : 1));
            if (z.off > -8 && !c.looter?.active) c.hurtPlayer(z.t.dmg * 0.45, false);
          }
          if (Math.abs(v) > 6 && Math.random() < dt * (Math.abs(v) > 12 ? 0.9 : 0.35)) {
            const f = new THREE.Vector3(z.side * 3, 3, 0);
            if (Math.abs(v) > 10) { this.kill(z, f); c.onKill(z, 'fall'); } else { z.state = 'walk'; p.y = 0; worldPos(s, z.side * 3.5, 0, _v); p.set(_v.x, 0, _v.z); }
          }
          continue;
        }
      }
      // выбор цели
      let tx, tz, toLooter = false;
      const L = c.looter;
      if (L && L.active && Math.hypot(L.pos.x - p.x, L.pos.z - p.z) < 55) { tx = L.pos.x; tz = L.pos.z; toLooter = true; }
      else if (zs > sF + 2 && zs < sF + 180) { worldPos(zs - 3, clamp(zd, -0.4, 0.4), 0, _v); tx = _v.x; tz = _v.z; }
      else { const ts = clamp(zs, sR + 1, sF - 1); worldPos(ts, Math.sign(zd || 1) * 1.9, 0, _v); tx = _v.x; tz = _v.z; }
      const dx = tx - p.x, dz = tz - p.z, dist = Math.hypot(dx, dz);
      // крикун зовёт остальных
      if (z.type === 'screamer' && !z.screamed && Math.hypot(p.x - c.cam.x, p.z - c.cam.z) < 40) { z.screamed = true; c.scream(z); }
      if (dist > 0.6) {
        const step = Math.min(dist, z.sp * dt);
        p.x += dx / dist * step; p.z += dz / dist * step;
        z.h.root.rotation.y = Math.atan2(-dx, -dz);
        this.anim(z, dt, z.sp, false);
      } else this.anim(z, dt, 0.5, false);
      p.y = c.groundH(zs, zd);
      if (toLooter && dist < 1.1) { z.state = 'attack'; z.onLooter = true; z.atk = 0.5; continue; }
      // поезд рядом: столкновение спереди или зацеп сбоку
      const inFront = zs > sF - 1 && zs < sF + 1.2 + Math.max(0, v) * dt * 2 && Math.abs(zd) < 1.9;
      if (inFront && v > 2.5) {
        const sp = v;
        const dmg = (z.t.trainHit || 0.6) * Math.min(1.5, sp / 18) * (tr.up.plow ? 0.12 : 1);
        c.hurtTrain(dmg);
        frameAt(sF, _t);
        const side = zd >= 0 ? 1 : -1;
        this.kill(z, new THREE.Vector3(_t.nx * side * (2 + sp * 0.3) - _t.nz * 0, 2 + sp * 0.35, -sp * 0.7 + _t.nz * side * 2));
        c.onKill(z, 'train'); c.sound('splat', z, 5);
        continue;
      }
      if (Math.abs(v) < 6 && zs < sF + 0.5 && zs > sR - 0.5 && Math.abs(zd) < 2.6 && Math.abs(zd) > 0.8) {
        z.state = 'attack'; z.off = zs - sF; z.side = zd >= 0 ? 1 : -1; z.atk = 0.6;
      } else if (Math.abs(v) < 2.5 && inFront) {
        z.state = 'attack'; z.off = -0.5; z.side = zd >= 0 ? 1 : -1; z.atk = 0.6;
      }
    }
  }
  anim(z, dt, speed, attack) {
    z.phase += dt * speed * 3.2;
    const h = z.h, s = Math.sin(z.phase);
    h.lL.rotation.x = s * 0.6; h.rL.rotation.x = -s * 0.6;
    if (attack) { h.lA.rotation.x = -1.6 + Math.sin(z.phase * 2.5) * 0.7; h.rA.rotation.x = -1.6 - Math.sin(z.phase * 2.5) * 0.7; }
    else { h.lA.rotation.x = -1.35 + s * 0.15; h.rA.rotation.x = -1.25 - s * 0.15; }
    h.body.rotation.z = Math.sin(z.phase * 0.5) * 0.06;
  }
  remove(i) {
    const z = this.list[i];
    this.scene.remove(z.h.root);
    this.list.splice(i, 1);
  }
  clear() { for (let i = this.list.length - 1; i >= 0; i--) this.remove(i); }
}
