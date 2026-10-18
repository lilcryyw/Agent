import * as THREE from '../vendor/three.module.min.js';
import { Char } from './chars.js';
import { toTrack, worldPos, frameAt, pick, R, wpick, clamp } from './util.js';

// base — тело, v — текстура, sc — пропорции, anim — походка
export const ZTYPES = {
  walker:   { n: 'Ходок', hp: 40, sp: [0.8, 1.4], dmg: 4, tdmg: 0.6, w: 10, minKm: 0, base: ['soldier', 'woman'], v: ['rot', 'rot2'] },
  worker:   { n: 'Путеец', hp: 50, sp: [0.9, 1.3], dmg: 4, tdmg: 0.6, w: 1.5, minKm: 0, base: ['soldier'], v: ['rot2'] },
  runner:   { n: 'Бегун', hp: 30, sp: [4.0, 5.2], dmg: 3, tdmg: 0.4, w: 3, minKm: 2, base: ['woman', 'soldier'], v: ['rot'], run: true },
  fat:      { n: 'Толстяк', hp: 170, sp: [0.6, 0.85], dmg: 8, tdmg: 3, w: 1.5, minKm: 4, base: ['soldier'], v: ['rot'], sc: [1.45, 1.0, 1.35], trainHit: 4 },
  screamer: { n: 'Крикун', hp: 35, sp: [1.8, 2.4], dmg: 3, tdmg: 0.4, w: 0.8, minKm: 5, base: ['woman'], v: ['rot2'], run: true },
  soldier:  { n: 'Солдат', hp: 100, sp: [1.0, 1.4], dmg: 6, tdmg: 1, w: 1.2, minKm: 7, base: ['soldier'], v: ['rot'] },
  frozen:   { n: 'Обмороженный', hp: 70, sp: [0.7, 1.0], dmg: 5, tdmg: 0.8, w: 0, minKm: 0, winter: 4, base: ['soldier', 'woman'], v: ['frozen'] },
  giant:    { n: 'Громила', hp: 520, sp: [1.3, 1.7], dmg: 16, tdmg: 7, w: 0.25, minKm: 18, base: ['soldier'], v: ['burnt'], sc: [1.55, 1.55, 1.55], trainHit: 12 },
};
const _t = {}, _v = new THREE.Vector3(), _d = new THREE.Vector3(), _up = new THREE.Vector3(0, 1, 0);
const MAXZ = 34;

export class Zombies {
  constructor(scene) { this.scene = scene; this.list = []; this.frame = 0; }
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

  spawn(type, x, z, km, r, home) {
    if (this.list.length >= MAXZ) {
      const i = this.list.findIndex((q) => q.state === 'dead');
      if (i < 0) return null; this.remove(i);
    }
    const t = ZTYPES[type];
    const ch = new Char(pick(r, t.base), pick(r, t.v), t.sc || [1, 1, 1]);
    ch.root.position.set(x, 0, z);
    this.scene.add(ch.root);
    const hpMul = 1 + km / 120;
    const zb = { type, t, h: ch, hp: t.hp * hpMul, max: t.hp * hpMul, sp: R(r, t.sp[0], t.sp[1]), phase: r() * 6, state: 'walk',
      atk: 0, groan: 2 + r() * 8, screamed: false, vel: null, deadT: 0, off: 0, side: 1, size: t.sc ? t.sc[1] : 1, lod: 0 };
    zb.home = home || { x, z }; zb.alert = 0;
    ch.mixer.setTime(r() * 2);
    this.list.push(zb);
    return zb;
  }

  hit(z, dmg, head) {
    if (z.state === 'dead' || z.state === 'fly') return false;
    z.hunt = true;
    z.hp -= dmg * (head ? 2.2 : 1);
    z.flinch = 0.25;
    if (z.hp <= 0) { this.kill(z); return true; }
    return false;
  }
  kill(z, fling) {
    z.h.mixer.stopAllAction();
    if (fling) { z.state = 'fly'; z.vel = fling; z.deadT = 0; }
    else { z.state = 'dead'; z.deadT = 0; z.fall = 0; }
  }

  update(dt, c) {
    const tr = c.train, sF = tr.s, sR = tr.sRear, v = tr.v, P = c.player;
    this.frame++;
    for (let i = this.list.length - 1; i >= 0; i--) {
      const z = this.list[i], p = z.h.root.position, ch = z.h;
      toTrack(p.x, p.z, _t);
      const zs = _t.s, zd = _t.d;
      if (z.state === 'dead' || z.state === 'fly') {
        z.deadT += dt;
        if (z.state === 'fly') {
          z.vel.y -= 9.8 * dt; p.addScaledVector(z.vel, dt);
          ch.inner.rotation.x += dt * 7; ch.inner.rotation.z += dt * 3;
          if (p.y <= 0 && z.vel.y < 0) { p.y = 0; z.state = 'dead'; z.fall = 1; ch.inner.rotation.set(-Math.PI / 2, 0, 0); }
        } else {
          z.fall = Math.min(1, (z.fall || 0) + dt * 2.2);
          ch.inner.rotation.x = -Math.PI / 2 * (z.fall * z.fall);
        }
        if (z.deadT > 8 || zs < sR - 150) this.remove(i);
        continue;
      }
      if (zs < sR - 130 || zs > sF + 450 || Math.abs(zd) > 280) { this.remove(i); continue; }
      const camD = Math.hypot(p.x - c.cam.x, p.z - c.cam.z);
      z.groan -= dt;
      if (z.groan <= 0) { z.groan = 4 + Math.random() * 9; if (camD < 50) c.sound('groan', z, camD); }
      let anim = 'walk', speed = z.sp, swing = false;

      if (z.state === 'attack') {
        // висит на поезде или бьёт игрока
        if (z.onPlayer) {
          if (!P.onGround) { z.state = 'walk'; z.onPlayer = false; }
          else {
            anim = 'idle'; swing = true; z.atk -= dt;
            if (z.atk <= 0) { z.atk = 1.15; c.sound('attack', z, camD); c.hurtPlayer(z.t.dmg, true, z); }
            face(z, P.pos.x - p.x, P.pos.z - p.z);
            if (Math.hypot(P.pos.x - p.x, P.pos.z - p.z) > 1.5) { z.state = 'walk'; z.onPlayer = false; }
          }
        } else {
          const s = sF + z.off;
          worldPos(s, z.side * 1.85, 0, _v); p.set(_v.x, 0.55, _v.z);
          frameAt(s, _t); z.h.root.rotation.y = _t.yaw + z.side * Math.PI / 2;
          anim = 'idle'; swing = true; z.atk -= dt;
          if (z.atk <= 0) {
            z.atk = 1;
            c.hurtTrain(z.t.tdmg * (tr.up.armor ? 0.5 : 1)); if (Math.random() < 0.6) c.sound('bang', z, camD);
            if (z.off > -8 && P.mode === 'cab') c.hurtPlayer(z.t.dmg * 0.45, false, z);
          }
          if (Math.abs(v) > 6 && Math.random() < dt * (Math.abs(v) > 12 ? 0.9 : 0.35)) {
            frameAt(s, _t);
            const f = new THREE.Vector3(_t.nx * z.side * 3, 3, _t.nz * z.side * 3);
            if (Math.abs(v) > 10) { this.kill(z, f); c.onKill(z, 'fall'); continue; }
            z.state = 'walk'; worldPos(s, z.side * 3.5, 0, _v); p.set(_v.x, 0, _v.z);
          }
        }
      } else {
        // цель: игрок на земле рядом, иначе поезд
        let tx, tz, toPlayer = false, wander = false;
        const pd = P.onGround || P.mode === 'roof' ? Math.hypot(P.pos.x - p.x, P.pos.z - p.z) : 1e9;
        const detect = P.crouch ? 13 : P.running ? 70 : 38;
        const dS = zs > sF ? zs - sF : zs < sR ? sR - zs : 0, trainD = Math.hypot(dS, Math.abs(zd));
        if (P.onGround && (pd < detect || (z.hunt && pd < 90) || (z.alert > 0 && pd < 130))) {
          if (!z.hunt) { z.hunt = true; c.sound('notice', z, camD); }
          tx = P.pos.x; tz = P.pos.z; toPlayer = true;
        } else if (z.alert > 0 || trainD < c.trainNoise || z.hunt) {
          if (zs > sF + 2 && zs < sF + 180) { worldPos(zs - 3, clamp(zd, -0.4, 0.4), 0, _v); tx = _v.x; tz = _v.z; }
          else { const ts = clamp(zs, sR + 1, sF - 1); worldPos(ts, Math.sign(zd || 1) * 1.9, 0, _v); tx = _v.x; tz = _v.z; }
        } else {
          // ещё не заметили: бродят у своего дома
          wander = true;
          if (!z.wp || Math.hypot(z.wp.x - p.x, z.wp.z - p.z) < 0.8) { const h = z.home || p; z.wp = { x: h.x + (Math.random() - 0.5) * 16, z: h.z + (Math.random() - 0.5) * 16 }; z.wait = Math.random() * 4; }
          tx = z.wp.x; tz = z.wp.z;
        }
        if (z.alert > 0) z.alert -= dt;
        const dx = tx - p.x, dz = tz - p.z, dist = Math.hypot(dx, dz);
        if (z.type === 'screamer' && !z.screamed && toPlayer && pd < 30) { z.screamed = true; c.scream(z); }
        if (wander && z.wait > 0) { z.wait -= dt; anim = 'idle'; }
        else if (dist > 0.6) {
          const st = Math.min(dist, z.sp * dt * (z.flinch > 0 ? 0.3 : 1) * (wander ? 0.45 : 1));
          speed = z.sp * (wander ? 0.45 : 1);
          // шаги рядом слышны
          z.stepAcc = (z.stepAcc || 0) + st;
          if (z.stepAcc > (z.t.run && !wander ? 1.3 : 0.75)) { z.stepAcc = 0; if (camD < 26) c.sound('step', z, camD); }
          p.x += dx / dist * st; p.z += dz / dist * st;
          face(z, dx, dz);
          anim = z.t.run && !wander ? 'run' : 'walk';
        } else anim = 'idle';
        p.y = c.groundH(zs, zd);
        if (toPlayer && dist < 1.15) { z.state = 'attack'; z.onPlayer = true; z.atk = 0.4; }
        else {
          const inFront = zs > sF - 1 && zs < sF + 1.2 + Math.max(0, v) * dt * 2 && Math.abs(zd) < 1.9;
          if (inFront && v > 2.5) {
            const dmg = (z.t.trainHit || 0.6) * Math.min(1.5, v / 18) * (tr.up.plow ? 0.12 : 1);
            c.hurtTrain(dmg);
            frameAt(sF, _t);
            const side = zd >= 0 ? 1 : -1;
            this.kill(z, new THREE.Vector3(_t.nx * side * (2 + v * 0.3) - Math.sin(_t.yaw) * v * 0.7, 2 + v * 0.35, _t.nz * side * (2 + v * 0.3) - Math.cos(_t.yaw) * v * 0.7));
            c.onKill(z, 'train'); c.sound('splat', z, 5);
            continue;
          }
          if (Math.abs(v) < 6 && zs < sF + 0.5 && zs > sR - 0.5 && Math.abs(zd) < 2.6 && Math.abs(zd) > 0.8) { z.state = 'attack'; z.off = zs - sF; z.side = zd >= 0 ? 1 : -1; z.atk = 0.6; }
          else if (Math.abs(v) < 2.5 && inFront) { z.state = 'attack'; z.off = -0.5; z.side = zd >= 0 ? 1 : -1; z.atk = 0.6; }
        }
      }
      if (z.flinch > 0) z.flinch -= dt;
      // анимация: дальние обновляются реже
      const far = camD > 70;
      z.lod += dt;
      if (far && (this.frame + i) % 4) continue;
      const adt = far ? z.lod : dt; z.lod = 0;
      const sc = anim === 'run' ? speed / 3.6 : anim === 'walk' ? Math.max(0.45, speed / 1.5) : 1;
      ch.play(anim, 0.3, sc);
      ch.update(adt);
      if (far) continue;
      // поза зомби: руки вперёд, при атаке — удары
      z.phase += dt * (swing ? 7 : 2);
      ch.root.updateMatrixWorld(true);
      const yaw = ch.root.rotation.y;
      for (const [arm, fore, k] of [['LeftArm', 'LeftForeArm', 1], ['RightArm', 'RightForeArm', -1]]) {
        const lift = swing ? 0.25 + Math.sin(z.phase + k) * 0.55 : -0.05 + Math.sin(z.phase + k) * 0.08;
        _d.set(-Math.sin(yaw), lift, -Math.cos(yaw));
        _d.x += Math.cos(yaw) * k * -0.18; _d.z += -Math.sin(yaw) * k * -0.18;
        _d.normalize();
        ch.aim(arm, fore, _d, anim === 'run' ? 0.5 : 0.85);
      }
      const hd = ch.bones.Head; if (hd) { hd.rotation.z += Math.sin(z.phase * 0.3) * 0.25; hd.rotation.x += 0.2; }
    }
  }
  // шум (выстрел, гудок) поднимает всех вокруг
  alarm(x, z, radius) { for (const q of this.list) if (q.state !== 'dead' && Math.hypot(q.h.root.position.x - x, q.h.root.position.z - z) < radius) q.alert = 12; }
  remove(i) {
    const z = this.list[i];
    this.scene.remove(z.h.root);
    z.h.mixer.stopAllAction(); z.h.mixer.uncacheRoot(z.h.model);
    this.list.splice(i, 1);
  }
  clear() { for (let i = this.list.length - 1; i >= 0; i--) this.remove(i); }
}
function face(z, dx, dz) {
  const want = Math.atan2(-dx, -dz), cur = z.h.root.rotation.y;
  let d = want - cur; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2;
  z.h.root.rotation.y = cur + d * 0.2;
}
