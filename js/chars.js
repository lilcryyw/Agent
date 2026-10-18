// Персонажи: зомби (Infected City Man, CC0, анимации Mixamo) и выжившие (Mixamo из примеров three.js).
import * as THREE from '../vendor/three.module.min.js';
import { GLTFLoader } from '../vendor/addons/GLTFLoader.js';
import * as SkeletonUtils from '../vendor/addons/SkeletonUtils.js';

const BASES = {};      // zombie, soldier, woman
const VARIANTS = {};   // 'база:вариант' -> материалы
const ONCE = new Set(['death', 'hit', 'scream']);
const boneName = (n) => n.replace('mixamorig:', '').replace('mixamorig', '').replace('CityDeadOutfit', '');

export async function loadChars(onProgress) {
  const L = new GLTFLoader();
  let done = 0;
  const one = async (url) => { const g = await L.loadAsync(url); done++; onProgress && onProgress(done / 3); return g; };
  const [zom, sol, wom] = await Promise.all([one('assets/models/zombie.glb'), one('assets/models/soldier.glb'), one('assets/models/woman.glb')]);
  BASES.zombie = prep(zom.scene);
  BASES.zombie.clips = Object.fromEntries(zom.animations.map((a) => [a.name, a]));
  BASES.soldier = prep(sol.scene);
  BASES.woman = prep(wom.scene);
  const get = (n) => sol.animations.find((a) => a.name === n);
  const strip = (c) => new THREE.AnimationClip(c.name, c.duration, c.tracks.filter((t) => t.name.endsWith('.quaternion')));
  const hum = { idle: strip(get('Idle')), walk: strip(get('Walk')), run: strip(get('Run')) };
  BASES.soldier.clips = hum; BASES.woman.clips = hum;
  makeVariants();
}

// нормируем рост до 1,8 м и разворачиваем лицом к −Z
function prep(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const h = box.max.y - box.min.y;
  const bones = {};
  scene.traverse((o) => { if (o.isBone) bones[boneName(o.name)] = o; });
  const foot = bones.LeftFoot.getWorldPosition(new THREE.Vector3()), toe = bones.LeftToeBase.getWorldPosition(new THREE.Vector3());
  const mats = [];
  scene.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; if (!mats.includes(o.material)) mats.push(o.material); } });
  return { scene, scale: 1.8 / h, minY: box.min.y, flip: toe.z > foot.z, mats };
}

// ---------- варианты окраски зомби: перекраска текстуры на холсте
function recolor(tex, kind) {
  const img = tex && tex.image;
  if (!img) return tex;
  const S = Math.min(1024, img.width || 1024), c = document.createElement('canvas'); c.width = c.height = S;
  const x = c.getContext('2d'); x.drawImage(img, 0, 0, S, S);
  const d = x.getImageData(0, 0, S, S), p = d.data;
  const P = { base: [1.35, 1.25, 1.2, 0], pale: [1.7, 1.7, 1.6, 0.35], burnt: [0.75, 0.62, 0.55, 0.2], frozen: [1.35, 1.6, 1.95, 0.55], green: [1.25, 1.55, 1.1, 0.3] }[kind];
  for (let i = 0; i < p.length; i += 4) {
    const l = p[i] * 0.3 + p[i + 1] * 0.59 + p[i + 2] * 0.11;
    for (let k = 0; k < 3; k++) p[i + k] = Math.min(255, (p[i + k] * (1 - P[3]) + l * P[3]) * P[k]);
  }
  x.putImageData(d, 0, 0);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.flipY = tex.flipY; t.anisotropy = 2;
  return t;
}
function makeVariants() {
  for (const kind of ['base', 'pale', 'burnt', 'frozen', 'green']) {
    VARIANTS['zombie:' + kind] = BASES.zombie.mats.map((m) => {
      const n = m.clone(); n.map = recolor(m.map, kind); n.roughness = kind === 'frozen' ? 0.5 : 0.8; return n;
    });
  }
  for (const b of ['soldier', 'woman']) VARIANTS[b + ':clean'] = BASES[b].mats.map((m) => new THREE.MeshStandardMaterial({ map: m.map || null, color: m.map ? 0xffffff : 0x202326, roughness: 0.8 }));
}

const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _q = new THREE.Quaternion(), _wq = new THREE.Quaternion(), _pq = new THREE.Quaternion();
export class Char {
  constructor(base, variant = 'base', scale = [1, 1, 1]) {
    const B = BASES[base];
    this.base = base;
    this.root = new THREE.Group();
    const model = SkeletonUtils.clone(B.scene);
    const mats = VARIANTS[base + ':' + variant] || VARIANTS[base + ':' + (base === 'zombie' ? 'base' : 'clean')];
    model.traverse((o) => {
      if (o.isMesh) {
        const k = B.mats.indexOf(o.userData._srcMat || o.material);
        o.material = mats[k >= 0 ? k : 0] || mats[0];
        o.frustumCulled = false; o.castShadow = true;
      }
    });
    this.inner = new THREE.Group();
    this.inner.add(model);
    const s = B.scale;
    model.scale.multiplyScalar(s);
    model.position.y = -B.minY * s;
    if (B.flip) model.rotation.y = Math.PI;
    this.inner.scale.set(scale[0], scale[1], scale[2]);
    this.root.add(this.inner);
    this.bones = {};
    model.traverse((o) => { if (o.isBone) this.bones[boneName(o.name)] = o; });
    this.mixer = new THREE.AnimationMixer(model);
    this.act = {};
    for (const [k, c] of Object.entries(B.clips)) {
      const a = this.mixer.clipAction(c);
      if (ONCE.has(k)) { a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; }
      this.act[k] = a;
    }
    this.cur = null; this.play('idle', 0);
    this.model = model;
  }
  has(name) { return !!this.act[name]; }
  play(name, fade = 0.25, speed = 1, restart = false) {
    const a = this.act[name] || this.act.walk;
    a.timeScale = speed;
    if (this.cur === name && !restart) return;
    const prev = this.cur ? this.act[this.cur] : null;
    a.reset().setEffectiveWeight(1).play();
    if (prev && prev !== a && fade > 0) prev.crossFadeTo(a, fade, false); else if (prev && prev !== a) prev.stop();
    this.cur = name;
  }
  done() { const a = this.act[this.cur]; return !a || !a.isRunning(); }
  // повернуть кость так, чтобы она смотрела в мировом направлении dir
  aim(boneName, childName, dir, w) {
    const b = this.bones[boneName], c = this.bones[childName];
    if (!b || !c || !b.parent) return;
    b.getWorldPosition(_a); c.getWorldPosition(_b);
    _b.sub(_a).normalize();
    _q.setFromUnitVectors(_b, dir);
    b.getWorldQuaternion(_wq); _q.multiply(_wq);
    b.parent.getWorldQuaternion(_pq);
    _q.premultiply(_pq.invert());
    b.quaternion.slerp(_q, w);
    b.updateMatrixWorld(true);
  }
  update(dt) { this.mixer.update(dt); }
}
export function charsReady() { return !!BASES.zombie; }
