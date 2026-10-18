// Персонажи: реалистичные модели (Mixamo, из примеров three.js), анимации, «гнилые» текстуры зомби.
import * as THREE from '../vendor/three.module.min.js';
import { GLTFLoader } from '../vendor/addons/GLTFLoader.js';
import * as SkeletonUtils from '../vendor/addons/SkeletonUtils.js';
import { mulberry32 } from './util.js';

const BASES = {};      // soldier, woman: { scene, height, flip }
const CLIPS = {};      // idle, walk, run (для каждой базы)
const VARIANTS = {};   // ключ -> материал

export async function loadChars(onProgress) {
  const L = new GLTFLoader();
  let done = 0;
  const one = async (name, url) => {
    const g = await L.loadAsync(url);
    done++; onProgress && onProgress(done / 2);
    return g;
  };
  const [sol, wom] = await Promise.all([one('soldier', 'assets/models/soldier.glb'), one('woman', 'assets/models/woman.glb')]);
  BASES.soldier = prep(sol.scene);
  BASES.woman = prep(wom.scene);
  const get = (n) => sol.animations.find((a) => a.name === n);
  CLIPS.soldier = { idle: get('Idle'), walk: get('Walk'), run: get('Run') };
  // у второй модели своих анимаций нет — берём клипы солдата без смещений корня
  const strip = (c) => new THREE.AnimationClip(c.name, c.duration, c.tracks.filter((t) => t.name.endsWith('.quaternion')));
  CLIPS.woman = { idle: strip(get('Idle')), walk: strip(get('Walk')), run: strip(get('Run')) };
  CLIPS.soldier = { idle: strip(get('Idle')), walk: strip(get('Walk')), run: strip(get('Run')) };
  makeVariants();
}

// нормируем рост до 1,8 м и разворачиваем лицом к −Z
function prep(scene) {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(scene);
  const h = box.max.y - box.min.y;
  const bones = {};
  scene.traverse((o) => { if (o.isBone) bones[o.name.replace('mixamorig:', '').replace('mixamorig', '')] = o; });
  const foot = bones.LeftFoot.getWorldPosition(new THREE.Vector3()), toe = bones.LeftToeBase.getWorldPosition(new THREE.Vector3());
  const facesPlusZ = toe.z > foot.z;
  scene.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; o.castShadow = false; } });
  return { scene, scale: 1.8 / h, minY: box.min.y, flip: facesPlusZ };
}

// ---------- текстуры зомби
function imgOf(mat) { return mat && mat.map && mat.map.image; }
function rotTexture(img, seed, kind) {
  const r = mulberry32(seed);
  const S = 512, c = document.createElement('canvas'); c.width = c.height = S;
  const x = c.getContext('2d');
  x.drawImage(img, 0, 0, S, S);
  const d = x.getImageData(0, 0, S, S), p = d.data;
  // трупный цвет: серо-зелёный, с пятнами
  const tint = kind === 'frozen' ? [0.62, 0.72, 0.82] : kind === 'burnt' ? [0.32, 0.28, 0.25] : [0.56, 0.62, 0.48];
  const mixK = kind === 'burnt' ? 0.75 : 0.5;
  for (let i = 0; i < p.length; i += 4) {
    const l = (p[i] * 0.3 + p[i + 1] * 0.59 + p[i + 2] * 0.11) / 255;
    const n = 0.85 + 0.3 * Math.sin(i * 0.0007 + seed) * Math.sin(i * 0.00013);
    for (let k = 0; k < 3; k++) {
      const v = (p[i + k] / 255) * (1 - mixK) + (l * 0.9 + 0.08) * tint[k] * mixK * 1.6;
      p[i + k] = Math.max(0, Math.min(255, v * 255 * n));
    }
  }
  x.putImageData(d, 0, 0);
  // грязь и трупные пятна
  for (let i = 0; i < 40; i++) {
    const cx = r() * S, cy = r() * S, rad = 6 + r() * 40;
    const g = x.createRadialGradient(cx, cy, 0, cx, cy, rad);
    const dark = kind === 'frozen' ? 'rgba(40,60,90,' : 'rgba(40,35,20,';
    g.addColorStop(0, dark + (0.25 + r() * 0.35) + ')'); g.addColorStop(1, dark + '0)');
    x.fillStyle = g; x.fillRect(cx - rad, cy - rad, rad * 2, rad * 2);
  }
  // кровь: брызги и подтёки
  if (kind !== 'frozen') for (let i = 0; i < 26; i++) {
    const cx = r() * S, cy = r() * S, rad = 3 + r() * 22;
    x.fillStyle = `rgba(${70 + r() * 50 | 0},${5 + r() * 10 | 0},${5 + r() * 10 | 0},${0.55 + r() * 0.35})`;
    x.beginPath();
    for (let a = 0; a < 6.28; a += 0.5) { const rr = rad * (0.6 + r() * 0.6); x.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr); }
    x.fill();
    for (let k = 0; k < 4; k++) { x.beginPath(); x.arc(cx + (r() - 0.5) * rad * 4, cy + (r() - 0.5) * rad * 4, 1 + r() * 3, 0, 7); x.fill(); }
    if (r() < 0.5) { x.fillRect(cx - 1.5, cy, 3, rad * (1 + r() * 3)); }
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.flipY = false; t.anisotropy = 2;
  return t;
}
function makeVariants() {
  for (const base of ['soldier', 'woman']) {
    const mats = [];
    BASES[base].scene.traverse((o) => { if (o.isMesh && !mats.includes(o.material)) mats.push(o.material); });
    BASES[base].mats = mats;
    ['rot', 'rot2', 'burnt', 'frozen'].forEach((kind, vi) => {
      VARIANTS[base + ':' + kind] = mats.map((m, mi) => {
        const img = imgOf(m);
        const map = img ? rotTexture(img, 77 + vi * 31 + mi * 7 + (base === 'woman' ? 500 : 0), kind.replace('2', '')) : null;
        return new THREE.MeshStandardMaterial({ map, color: map ? 0xffffff : 0x2a2a28, roughness: 0.85 });
      });
    });
    VARIANTS[base + ":clean"] = mats.map((m) => new THREE.MeshStandardMaterial({ map: m.map || null, color: m.map ? 0xffffff : 0x202326, roughness: 0.8 }));
  }
}

// ---------- экземпляр персонажа
const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _q = new THREE.Quaternion(), _wq = new THREE.Quaternion(), _pq = new THREE.Quaternion();
export class Char {
  constructor(base, variant, scale = [1, 1, 1]) {
    const B = BASES[base];
    this.root = new THREE.Group();
    const model = SkeletonUtils.clone(B.scene);
    const mats = VARIANTS[base + ':' + variant];
    let mi = 0; const idx = new Map();
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
    model.traverse((o) => { if (o.isBone) this.bones[o.name.replace('mixamorig:', '').replace('mixamorig', '')] = o; });
    this.mixer = new THREE.AnimationMixer(model);
    const C = CLIPS[base];
    this.act = { idle: this.mixer.clipAction(C.idle), walk: this.mixer.clipAction(C.walk), run: this.mixer.clipAction(C.run) };
    this.cur = null; this.play('idle', 0);
    this.model = model;
  }
  play(name, fade = 0.25, speed = 1) {
    const a = this.act[name];
    a.timeScale = speed;
    if (this.cur === name) return;
    const prev = this.cur ? this.act[this.cur] : null;
    a.reset().setEffectiveWeight(1).play();
    if (prev && fade > 0) prev.crossFadeTo(a, fade, false); else if (prev) prev.stop();
    this.cur = name;
  }
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
export function charsReady() { return !!BASES.soldier; }
