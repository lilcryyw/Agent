// Игрок: кабина, земля, крыша поезда. Бег, присед, шаги, оружие в руках.
import * as THREE from '../vendor/three.module.min.js';
import { Char } from './chars.js';
import { worldPos, frameAt, toTrack, clamp, boxAt, cylGeo, merge, C, P } from './util.js';

const _t = {}, _v = new THREE.Vector3(), _f = {}, _a = new THREE.Vector3(), _b = new THREE.Vector3();
const METAL = P(0x2a2d30, 50), WOOD = C(0x6a3a1a), BLACK = C(0x151515);
function gunMesh(kind) {
  const g = new THREE.Group();
  const add = (geo, m) => g.add(new THREE.Mesh(geo, m));
  const bar = (r, len, x, y, z) => cylGeo(r, r, len, 8, 1).rotateX(Math.PI / 2).translate(x, y, z);
  if (kind === 'pm') {
    add(boxAt(0.03, 0.035, 0.17, 0, 0.02, -0.07, 1), METAL); add(boxAt(0.028, 0.1, 0.045, 0, -0.04, 0.0, 1, 0), BLACK);
  } else if (kind === 'toz') {
    add(merge([bar(0.012, 0.42, 0.012, 0.02, -0.3), bar(0.012, 0.42, -0.012, 0.02, -0.3)]), METAL);
    add(merge([boxAt(0.045, 0.06, 0.16, 0, 0.0, -0.02, 1), boxAt(0.04, 0.09, 0.2, 0, -0.04, 0.14, 1)]), WOOD);
  } else if (kind === 'bizon') {
    add(merge([boxAt(0.045, 0.06, 0.32, 0, 0.02, -0.08, 1), bar(0.009, 0.14, 0, 0.03, -0.3)]), METAL);
    add(bar(0.025, 0.24, 0, -0.035, -0.14), BLACK); add(boxAt(0.03, 0.09, 0.04, 0, -0.04, 0.02, 1), BLACK);
  } else if (kind === 'ak' || kind === 'svd') {
    const L = kind === 'svd' ? 0.55 : 0.38;
    add(merge([boxAt(0.05, 0.065, 0.3, 0, 0.02, -0.06, 1), bar(0.011, L, 0, 0.035, -0.21 - L / 2)]), METAL);
    add(merge([boxAt(0.055, 0.05, 0.16, 0, 0.025, -0.28, 1), boxAt(0.04, 0.08, 0.26, 0, 0.0, 0.2, 1)]), WOOD);
    if (kind === 'ak') { const m = new THREE.Mesh(boxAt(0.028, 0.16, 0.05, 0, -0.08, 0, 1), C(0x3a2a1a)); m.position.set(0, -0.0, -0.08); m.rotation.x = -0.35; g.add(m); }
    else { add(bar(0.02, 0.24, 0, 0.1, -0.06), BLACK); add(boxAt(0.028, 0.12, 0.05, 0, -0.06, -0.1, 1), BLACK); }
    add(boxAt(0.03, 0.08, 0.04, 0, -0.04, 0.03, 1), BLACK);
  }
  return g;
}

export class Player {
  constructor(scene) {
    this.ch = new Char('soldier', 'clean');
    this.root = this.ch.root; scene.add(this.root); this.root.visible = false;
    this.mode = 'cab';
    this.pos = new THREE.Vector3();
    this.yaw = 0; this.off = -12; this.d = 0;
    this.tween = null; this.aimT = 0; this.aimDir = new THREE.Vector3(0, 0, -1);
    this.moving = 0; this.crouch = false; this.run = false; this.crouchK = 0; this.stepAcc = 0; this.stam = 100;
    this.onStep = null;
    this.hand = this.ch.bones.RightHand;
    this.root.updateMatrixWorld(true);
    this.handS = this.hand ? this.hand.getWorldScale(new THREE.Vector3()).x : 1;
    this.weapon = null;
  }
  get onGround() { return this.mode === 'ground' && !this.tween; }
  get busy() { return !!this.tween; }
  setWeapon(id) {
    if (id === this.weapon || !this.hand) return;
    if (this.gun) this.hand.remove(this.gun);
    this.weapon = id; this.gun = null;
    if (!id) return;
    const g = gunMesh(id), s = 1 / this.handS;
    g.scale.setScalar(s); g.rotation.set(Math.PI / 2, 0, 0); g.position.set(0, 0.08 * s, 0.02 * s);
    this.hand.add(g); this.gun = g;
  }
  climb(path, mode, dur) { this.tween = { path, mode, dur, t: 0, st: 0 }; this.root.visible = true; this.crouch = false; }
  roofY(train, off, d = 0) {
    let o = 0;
    for (const c of train.cars) {
      const a = -o, b = -o - c.len;
      if (off <= a + 0.3 && off >= b - 0.3) {
        const local = -(off - (a - c.len / 2));
        return c.roofY(local, d) + 0.64;
      }
      o += c.len + 0.6;
    }
    return 5.5;
  }
  trainPoint(train, off, d, y, out = new THREE.Vector3()) { worldPos(train.s + off, d, 0, out); out.y = y; return out; }

  update(dt, inp, train, world, groundH) {
    const ch = this.ch;
    if (this.tween) {
      const T = this.tween; T.t += dt;
      const k = Math.min(1, T.t / T.dur), n = T.path.length - 1, seg = Math.min(n - 1, Math.floor(k * n)), lk = k * n - seg;
      const A = T.path[seg], Bp = T.path[seg + 1];
      const pa = A.rel ? this.trainPoint(train, A.off, A.d, A.y, _a) : _a.copy(A.p);
      const pb = Bp.rel ? this.trainPoint(train, Bp.off, Bp.d, Bp.y, _b) : _b.copy(Bp.p);
      this.pos.lerpVectors(pa, pb, lk);
      const dx = pb.x - pa.x, dz = pb.z - pa.z, vert = Math.abs(pb.y - pa.y) > 0.6;
      if (Math.hypot(dx, dz) > 0.3 && !vert) this.yaw = Math.atan2(-dx, -dz);
      ch.play('walk', 0.2, vert ? 0.6 : 0.9);
      T.st += dt; if (T.st > (vert ? 0.4 : 0.45)) { T.st = 0; this.onStep && this.onStep(vert ? 'metal' : 'auto', 0.8); }
      if (k >= 1) {
        this.tween = null; this.mode = T.mode;
        if (T.mode === 'roof' || T.mode === 'inside') { toTrack(this.pos.x, this.pos.z, _t); this.off = _t.s - train.s; this.d = clamp(_t.d, -1.15, 1.15); }
        if (T.mode === 'cab') this.root.visible = false;
      }
    } else if (this.mode === 'ground' || this.mode === 'roof' || this.mode === 'inside') {
      const m = Math.min(1, Math.hypot(inp.jx, inp.jy));
      const cy = inp.camYaw, fx = -Math.sin(cy), fz = -Math.cos(cy), rx = Math.cos(cy), rz = -Math.sin(cy);
      let mx = 0, mz = 0;
      if (m > 0.12) { mx = fx * inp.jy + rx * inp.jx; mz = fz * inp.jy + rz * inp.jx; const l = Math.hypot(mx, mz); mx /= l; mz /= l; }
      const running = this.run && !this.crouch && m > 0.12 && this.stam > 1;
      let sp = 0;
      if (m > 0.12) sp = running ? 5.2 : this.crouch ? 0.6 + m * 0.7 : 0.9 + m * 1.9;
      if (inp.slow) sp *= 0.65;
      this.stam = clamp(this.stam + (running ? -14 : 9) * dt, 0, 100);
      if (this.stam <= 1 && this.run) this.run = false;
      this.moving = sp; this.running = running;
      if (this.mode === 'ground') {
        this.pos.x += mx * sp * dt; this.pos.z += mz * sp * dt;
        toTrack(this.pos.x, this.pos.z, _t);
        let s = _t.s, d = _t.d, moved = false;
        if (s < train.s + 0.6 && s > train.sRear - 0.6 && Math.abs(d) < 1.8) { d = d >= 0 ? 1.8 : -1.8; moved = true; }
        const c = world.collide(s, d, 0.4); if (c.hit) { s = c.s; d = c.d; moved = true; }
        if (moved) worldPos(s, d, 0, this.pos);
        this.pos.y = groundH(s, d);
      } else if (this.mode === 'inside') {
        frameAt(train.s + this.off, _f);
        const Fx = -Math.sin(_f.yaw), Fz = -Math.cos(_f.yaw);
        const r = train.insideCollide(this.off + (mx * Fx + mz * Fz) * sp * dt, this.d + (mx * _f.nx + mz * _f.nz) * sp * dt);
        this.off = clamp(r.off, -(train.length - 0.8), -0.5); this.d = r.d;
        const ci = train.carAt(this.off);
        this.trainPoint(train, this.off, this.d, ((ci && ci.c.floor) || 1.3) + 0.64, this.pos);
      } else {
        frameAt(train.s + this.off, _f);
        const Fx = -Math.sin(_f.yaw), Fz = -Math.cos(_f.yaw);
        this.off = clamp(this.off + (mx * Fx + mz * Fz) * sp * dt, -(train.length - 1.0), -1.2);
        this.d = clamp(this.d + (mx * _f.nx + mz * _f.nz) * sp * dt, -1.15, 1.15);
        this.trainPoint(train, this.off, this.d, this.roofY(train, this.off, this.d), this.pos);
      }
      if (sp > 0 && this.aimT <= 0) this.yaw = turn(this.yaw, Math.atan2(-mx, -mz), dt * 10);
      // шаги
      if (sp > 0) {
        this.stepAcc += sp * dt;
        const stride = running ? 1.35 : this.crouch ? 0.55 : 0.75;
        if (this.stepAcc > stride) { this.stepAcc = 0; this.onStep && this.onStep(this.mode === 'roof' ? 'metal' : 'auto', running ? 1 : this.crouch ? 0.35 : 0.7); }
      }
      ch.play(sp === 0 ? 'idle' : running ? 'run' : 'walk', 0.25, sp === 0 ? 1 : running ? 1.1 : Math.max(0.5, sp / 1.6));
    }
    this.crouchK += ((this.crouch && !this.tween && this.mode !== 'cab' ? 1 : 0) - this.crouchK) * Math.min(1, dt * 8);
    if (this.aimT > 0) { this.aimT -= dt; this.yaw = turn(this.yaw, Math.atan2(-this.aimDir.x, -this.aimDir.z), dt * 18); }
    this.root.position.copy(this.pos);
    this.root.rotation.y = this.yaw;
    if (this.root.visible) {
      ch.update(dt);
      const k = this.crouchK;
      ch.inner.position.y = -0.33 * k;
      this.root.updateMatrixWorld(true);
      const fw = _v.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
      if (k > 0.02) {
        const thigh = _a.copy(fw).multiplyScalar(0.9).add(new THREE.Vector3(0, -0.5, 0)).normalize();
        const shin = _b.copy(fw).multiplyScalar(-0.3).add(new THREE.Vector3(0, -1, 0)).normalize();
        for (const s of ['Left', 'Right']) { ch.aim(s + 'UpLeg', s + 'Leg', thigh, k * 0.85); ch.aim(s + 'Leg', s + 'Foot', shin, k * 0.85); }
      }
      // оружие наизготовку
      const w = this.aimT > 0 ? 1 : this.running ? 0 : 0.55;
      if (w > 0 && this.weapon) {
        const d = this.aimT > 0 ? this.aimDir : _a.set(fw.x, -0.25, fw.z).normalize();
        ch.aim('RightArm', 'RightForeArm', d, w); ch.aim('RightForeArm', 'RightHand', d, w);
        ch.aim('LeftArm', 'LeftForeArm', d, w * 0.8); ch.aim('LeftForeArm', 'LeftHand', d, w * 0.6);
      }
    }
  }
}
function turn(a, b, k) { let d = b - a; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return a + d * Math.min(1, k); }
