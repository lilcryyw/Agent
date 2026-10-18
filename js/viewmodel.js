// Оружие в руках при виде от первого лица: свой маленький сцена+камера поверх основной картинки.
import * as THREE from '../vendor/three.module.min.js';
import { packGeo, PACK_MAT } from './packs.js';

// модель из пака, длина в метрах, хват левой руки (доля длины от рукояти к стволу), позиция в кадре
const GUNS = {
  pm:    { m: 'Pistol_2', len: 0.17, left: 0, pos: [0.14, -0.14, -0.42] },
  toz:   { m: 'Shotgun_SawedOff', len: 0.58, left: 0.55, pos: [0.13, -0.15, -0.36] },
  bizon: { m: 'AssaultRifle_1', len: 0.62, left: 0.5, pos: [0.13, -0.15, -0.34] },
  ak:    { m: 'AssaultRifle_2', len: 0.88, left: 0.55, pos: [0.13, -0.15, -0.3] },
  svd:   { m: 'SniperRifle_6', len: 1.2, left: 0.45, pos: [0.13, -0.15, -0.28] },
};
const SKIN = new THREE.MeshStandardMaterial({ color: 0xc89878, roughness: 0.7 });
const GLOVE = new THREE.MeshStandardMaterial({ color: 0x2a2622, roughness: 0.9 });
const SLEEVE = new THREE.MeshStandardMaterial({ color: 0x3c4434, roughness: 0.95 });
const _y = new THREE.Vector3(0, 1, 0), _v = new THREE.Vector3();

function armMesh(from, to, glove) {
  // предплечье от кисти (from) к локтю (to) + кисть
  const g = new THREE.Group();
  const dir = _v.copy(to).sub(from), len = dir.length(); dir.normalize();
  const sl = new THREE.Mesh(new THREE.CapsuleGeometry(0.042, len, 4, 10), SLEEVE);
  sl.position.copy(from).addScaledVector(dir, len / 2 + 0.05); sl.quaternion.setFromUnitVectors(_y, dir); g.add(sl);
  const cuff = new THREE.Mesh(new THREE.CylinderGeometry(0.046, 0.046, 0.04, 12), SLEEVE);
  cuff.position.copy(from).addScaledVector(dir, 0.06); cuff.quaternion.copy(sl.quaternion); g.add(cuff);
  const hand = new THREE.Mesh(new THREE.SphereGeometry(0.042, 12, 8), glove ? GLOVE : SKIN);
  hand.scale.set(0.9, 0.8, 1.35); hand.position.copy(from); hand.quaternion.copy(sl.quaternion); g.add(hand);
  return g;
}
function flashTex() {
  const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d');
  const gr = x.createRadialGradient(32, 32, 0, 32, 32, 32);
  gr.addColorStop(0, 'rgba(255,250,220,1)'); gr.addColorStop(0.25, 'rgba(255,200,90,0.9)'); gr.addColorStop(1, 'rgba(255,120,20,0)');
  x.fillStyle = gr; x.beginPath();
  for (let i = 0; i < 16; i++) { const a = i / 16 * Math.PI * 2, r = i % 2 ? 12 : 32; x.lineTo(32 + Math.cos(a) * r, 32 + Math.sin(a) * r); }
  x.fill();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export class ViewModel {
  constructor() {
    this.scene = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(55, 1, 0.01, 5);
    this.hemi = new THREE.HemisphereLight(0xdfe8f0, 0x5a5048, 1.2); this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xfff2dc, 1.6); this.sun.position.set(0.5, 1, 0.3); this.scene.add(this.sun);
    this.holder = new THREE.Group(); this.scene.add(this.holder);
    this.flash = new THREE.Sprite(new THREE.SpriteMaterial({ map: flashTex(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    this.flash.visible = false; this.scene.add(this.flash);
    this.cur = null; this.models = {};
    this.t = 0; this.kick = 0; this.dip = 0; this.flashT = 0; this.swayX = 0; this.swayY = 0; this.lastYaw = null; this.lastPitch = null;
    this.muzzle = new THREE.Vector3();
  }
  build(id) {
    if (this.models[id]) return this.models[id];
    const G = GUNS[id]; if (!G) return null;
    const geo = packGeo(G.m, { rotY: Math.PI / 2 });
    geo.computeBoundingBox();
    const bb = geo.boundingBox, s = G.len / (bb.max.z - bb.min.z);
    const root = new THREE.Group();
    const gun = new THREE.Mesh(geo, PACK_MAT); gun.scale.setScalar(s); root.add(gun);
    // правая рука на рукояти, левая — на цевье (или поддерживает пистолет)
    const grip = new THREE.Vector3(0, -0.03, 0.02);
    root.add(armMesh(grip, new THREE.Vector3(0.11, -0.2, 0.36), true));
    const lz = bb.min.z * s * G.left;
    const lh = G.left ? new THREE.Vector3(-0.01, -0.025, lz) : new THREE.Vector3(-0.035, -0.05, 0.03);
    root.add(armMesh(lh, new THREE.Vector3(-0.22, -0.24, lz * 0.3 + 0.35), true));
    root.userData.muzzle = new THREE.Vector3(0, bb.max.y * s * 0.62, bb.min.z * s - 0.02);
    root.visible = false; this.holder.add(root);
    return (this.models[id] = root);
  }
  set(id) {
    if (id === this.cur) return;
    if (this.cur && this.models[this.cur]) this.models[this.cur].visible = false;
    this.cur = id; const m = id && this.build(id);
    if (m) { m.visible = true; this.dip = 1; }
  }
  fire(strength = 1) { this.kick = Math.min(1.4, this.kick + strength); this.flashT = 0.05; this.flash.material.rotation = Math.random() * 6.28; }
  // dt; moving 0..1; running; look — {yaw,pitch}; dayK — освещённость
  update(dt, o) {
    const m = this.cur && this.models[this.cur];
    this.holder.visible = !!m && o.show;
    if (!m) return;
    const G = GUNS[this.cur];
    this.t += dt * (o.running ? 11 : 7.5) * Math.min(1, o.moving);
    const amp = Math.min(1, o.moving) * (o.running ? 1.8 : 1);
    if (this.lastYaw !== null) {
      let dy = o.yaw - this.lastYaw; if (dy > Math.PI) dy -= Math.PI * 2; if (dy < -Math.PI) dy += Math.PI * 2;
      this.swayX += (Math.max(-0.05, Math.min(0.05, dy * 0.6)) - this.swayX) * Math.min(1, dt * 10);
      this.swayY += (Math.max(-0.04, Math.min(0.04, (o.pitch - this.lastPitch) * 0.6)) - this.swayY) * Math.min(1, dt * 10);
    }
    this.lastYaw = o.yaw; this.lastPitch = o.pitch;
    this.kick = Math.max(0, this.kick - dt * 7); this.dip = Math.max(0, this.dip - dt * 3);
    const run = o.running ? 1 : 0;
    this.runK = (this.runK || 0) + (run - (this.runK || 0)) * Math.min(1, dt * 6);
    const k = this.kick, d = this.dip * this.dip;
    this.holder.position.set(
      G.pos[0] + Math.sin(this.t) * 0.012 * amp + this.swayX * 0.4 - this.runK * 0.02,
      G.pos[1] - Math.abs(Math.cos(this.t)) * 0.012 * amp - d * 0.25 - this.runK * 0.05 + this.swayY * 0.4 - (o.crouch ? 0.01 : 0),
      G.pos[2] + k * 0.05);
    this.holder.rotation.set(k * 0.12 - this.runK * 0.35 + d * 0.6, this.swayX * 1.2 + this.runK * 0.5, -this.swayX * 0.6 - this.runK * 0.2);
    this.hemi.intensity = 0.25 + 0.9 * o.dayK; this.sun.intensity = 0.2 + 1.4 * o.dayK;
    this.flashT -= dt;
    this.flash.visible = this.flashT > 0;
    if (this.flash.visible) {
      this.holder.updateMatrixWorld(true);
      this.flash.position.copy(m.userData.muzzle).applyMatrix4(this.holder.matrixWorld);
      this.flash.scale.setScalar(this.cur === 'pm' ? 0.09 : 0.16);
    }
  }
  // точка дула в координатах основной камеры (для трассера)
  muzzleWorld(camera, out) {
    const m = this.cur && this.models[this.cur];
    if (!m) return out.set(0.1, -0.1, -0.5).applyMatrix4(camera.matrixWorld);
    this.holder.updateMatrixWorld(true);
    return out.copy(m.userData.muzzle).applyMatrix4(this.holder.matrixWorld).applyMatrix4(camera.matrixWorld);
  }
  render(renderer, aspect) {
    if (!this.holder.visible) return;
    if (this.cam.aspect !== aspect) { this.cam.aspect = aspect; this.cam.updateProjectionMatrix(); }
    const ac = renderer.autoClear; renderer.autoClear = false;
    renderer.clearDepth(); renderer.render(this.scene, this.cam);
    renderer.autoClear = ac;
  }
}
