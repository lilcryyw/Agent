// Игрок: кабина, земля, крыша поезда. Переходы — с анимацией подъёма.
import * as THREE from '../vendor/three.module.min.js';
import { Char } from './chars.js';
import { worldPos, frameAt, toTrack, clamp, boxAt, merge, C } from './util.js';

const _t = {}, _v = new THREE.Vector3(), _f = {};
export class Player {
  constructor(scene) {
    this.ch = new Char('soldier', 'clean');
    this.root = this.ch.root; scene.add(this.root); this.root.visible = false;
    this.mode = 'cab';              // cab | ground | roof
    this.pos = new THREE.Vector3();
    this.yaw = 0; this.off = -12; this.d = 0;
    this.tween = null; this.aimT = 0; this.aimDir = new THREE.Vector3(0, 0, -1);
    this.moving = 0;
    // оружие в руке
    const gun = new THREE.Mesh(merge([boxAt(0.06, 0.1, 0.55, 0, 0, -0.18, 1), boxAt(0.05, 0.16, 0.06, 0, -0.1, -0.02, 1)]), C(0x1a1a1a));
    this.gun = gun;
    const hand = this.ch.bones.RightHand;
    if (hand) {
      hand.add(gun); this.root.updateMatrixWorld(true);
      const s = hand.getWorldScale(_v); gun.scale.set(1 / s.x, 1 / s.y, 1 / s.z);
      gun.rotation.set(Math.PI / 2, 0, 0); gun.position.set(0, 0.08 / s.y, 0.02 / s.y);
    }
  }
  get onGround() { return this.mode === 'ground' && !this.tween; }
  get busy() { return !!this.tween; }

  // переход: путь из точек (в координатах поезда или мира), затем новый режим
  climb(path, mode, dur, train) {
    this.tween = { path, mode, dur, t: 0 };
    this.root.visible = true;
  }

  roofY(train, off) {
    let o = 0;
    for (const c of train.cars) {
      const a = -o, b = -o - c.len;
      if (off <= a + 0.3 && off >= b - 0.3) {
        const local = -(off - (a - c.len / 2));            // смещение от центра вагона к хвосту
        if (c.kind === 'loco') return local > -3.9 && local < 7.1 ? 5.8 : 5.49;
        return c.kind === 'tank' ? 5.15 : 5.79;
      }
      o += c.len + 0.6;
    }
    return 5.5;
  }
  trainPoint(train, off, d, y, out = new THREE.Vector3()) {
    worldPos(train.s + off, d, 0, out); out.y = y; return out;
  }

  update(dt, inp, train, world, groundH) {
    const ch = this.ch;
    if (this.tween) {
      const T = this.tween; T.t += dt;
      const k = Math.min(1, T.t / T.dur), n = T.path.length - 1, seg = Math.min(n - 1, Math.floor(k * n)), lk = k * n - seg;
      const A = T.path[seg], Bp = T.path[seg + 1];
      const pa = A.rel ? this.trainPoint(train, A.off, A.d, A.y, new THREE.Vector3()) : A.p;
      const pb = Bp.rel ? this.trainPoint(train, Bp.off, Bp.d, Bp.y, new THREE.Vector3()) : Bp.p;
      this.pos.lerpVectors(pa, pb, lk);
      const dx = pb.x - pa.x, dz = pb.z - pa.z;
      if (Math.hypot(dx, dz) > 0.3) this.yaw = Math.atan2(-dx, -dz);
      ch.play(Math.abs(pb.y - pa.y) > 0.5 ? 'walk' : 'walk', 0.2, 0.8);
      if (k >= 1) {
        this.tween = null; this.mode = T.mode;
        if (T.mode === 'roof') { toTrack(this.pos.x, this.pos.z, _t); this.off = _t.s - train.s; this.d = clamp(_t.d, -1.15, 1.15); }
        if (T.mode === 'cab') this.root.visible = false;
      }
    } else if (this.mode === 'ground' || this.mode === 'roof') {
      const m = Math.min(1, Math.hypot(inp.jx, inp.jy));
      const cy = inp.camYaw, fx = -Math.sin(cy), fz = -Math.cos(cy), rx = Math.cos(cy), rz = -Math.sin(cy);
      let mx = 0, mz = 0;
      if (m > 0.12) { mx = fx * inp.jy + rx * inp.jx; mz = fz * inp.jy + rz * inp.jx; const l = Math.hypot(mx, mz); mx /= l; mz /= l; }
      const run = m > 0.85, sp = m > 0.12 ? (run ? 5.0 : 1.2 + m * 1.6) * (inp.slow ? 0.6 : 1) : 0;
      this.moving = sp;
      if (this.mode === 'ground') {
        this.pos.x += mx * sp * dt; this.pos.z += mz * sp * dt;
        toTrack(this.pos.x, this.pos.z, _t);
        let s = _t.s, d = _t.d;
        // не проходить сквозь поезд
        if (s < train.s + 0.6 && s > train.sRear - 0.6 && Math.abs(d) < 1.8) d = d >= 0 ? 1.8 : -1.8;
        const c = world.collide(s, d, 0.4); s = c.s; d = c.d;
        worldPos(s, d, 0, this.pos); this.pos.y = groundH(s, d);
      } else {
        frameAt(train.s + this.off, _f);
        const Fx = -Math.sin(_f.yaw), Fz = -Math.cos(_f.yaw);
        this.off = clamp(this.off + (mx * Fx + mz * Fz) * sp * dt, -(train.length - 1.0), -1.2);
        this.d = clamp(this.d + (mx * _f.nx + mz * _f.nz) * sp * dt, -1.15, 1.15);
        this.trainPoint(train, this.off, this.d, this.roofY(train, this.off), this.pos);
      }
      if (sp > 0 && this.aimT <= 0) this.yaw = turn(this.yaw, Math.atan2(-mx, -mz), dt * 10);
      ch.play(sp === 0 ? 'idle' : run ? 'run' : 'walk', 0.25, sp === 0 ? 1 : run ? 1.1 : Math.max(0.6, sp / 1.7));
    }
    if (this.aimT > 0) { this.aimT -= dt; this.yaw = turn(this.yaw, Math.atan2(-this.aimDir.x, -this.aimDir.z), dt * 18); }
    this.root.position.copy(this.pos);
    this.root.rotation.y = this.yaw;
    if (this.root.visible) {
      ch.update(dt);
      // оружие наизготовку
      const w = this.aimT > 0 ? 1 : this.moving > 3 ? 0 : 0.55;
      if (w > 0) {
        this.root.updateMatrixWorld(true);
        const d = this.aimT > 0 ? this.aimDir : _v.set(-Math.sin(this.yaw), -0.25, -Math.cos(this.yaw)).normalize();
        ch.aim('RightArm', 'RightForeArm', d, w); ch.aim('RightForeArm', 'RightHand', d, w);
        ch.aim('LeftArm', 'LeftForeArm', d, w * 0.8); ch.aim('LeftForeArm', 'LeftHand', d, w * 0.6);
      }
    }
  }
}
function turn(a, b, k) { let d = b - a; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return a + d * Math.min(1, k); }
