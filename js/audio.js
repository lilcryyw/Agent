// Звук: настоящие записи (Red Library — CC0, Archive.org; OpenGameArt CC0; Kenney CC0).
// Поезд собран из слоёв: дизель, колёса, кабина, скрежет колодок, визг гребней, воздух.
const LIST = {
  // зомби
  z_moan: [1, 6], z_growl: [1, 10], z_grunt: [0, 4], z_mmoan: [0, 3], z_attack: [1, 3], z_scream: null, z_death: [1, 2], z_step: [0, 5], z_drag: [0, 2],
  // шаги
  st_grass: [0, 3], st_concrete: [0, 5], st_snow: [0, 5], st_wood: [0, 3], st_metal: [0, 5], st_gravel: [0, 5],
  // оружие
  g_pm: [0, 2], g_bizon: null, g_toz: null, g_ak: null, g_rifle: null, g_svd: null, g_turret: null, g_reload: null, g_cock: null, g_empty: null,
  // удары, тела
  hit_metal: [0, 2], clank: [0, 5], flesh: [1, 3], impact: [0, 2], punch: [0, 3], body_fall: [0, 1], smash_wood: null, smash_metal: null, breath: [0, 2],
  // быт
  cloth: [1, 4], coins: null, drop: null, eat: [1, 3], drink: [1, 2], bottle: null, rummage: null, door_handle: null, door_slam: null, door_slide: null,
  // поезд
  diesel_idle: null, cab_ride: null, train_pass: null, brake_squeal: null, air_loop: null,
  horn: null, coupling: null, stop_hiss: null, air_release: null, brake_apply: null, air_emerg: null, clack: null, clack2: null,
  // природа
  wind: null, wind_cold: null, rain: null, thunder: null, birds: null, owl: null,
};
const FILES = [];
for (const [k, v] of Object.entries(LIST)) if (v) for (let i = v[0]; i <= v[1]; i++) FILES.push(k + i); else FILES.push(k);
const LOOPS = ['diesel_idle', 'cab_ride', 'train_pass', 'brake_squeal', 'air_loop', 'wind', 'wind_cold', 'rain', 'birds', 'rummage'];

export class Audio {
  constructor() { this.ctx = null; this.on = true; this.raw = {}; this.buf = {}; this.voices = 0; this.L = {}; this.ready = false; }
  preload(base = 'assets/sfx/') {
    this.loading = Promise.all(FILES.map((f) => fetch(base + f + '.mp3').then((r) => (r.ok ? r.arrayBuffer() : null)).then((b) => { if (b) this.raw[f] = b; }).catch(() => {})));
    return this.loading;
  }
  init() {
    // iPhone: играть даже при выключенном звонке (переключатель «бесшумно»)
    try { if (navigator.audioSession) navigator.audioSession.type = 'playback'; } catch (e) { /* старый iOS */ }
    if (this.ctx) { if (this.ctx.state !== 'running') this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const c = this.ctx = new AC();
    this.comp = c.createDynamicsCompressor(); this.comp.threshold.value = -8; this.comp.ratio.value = 2.5; this.comp.attack.value = 0.01; this.comp.release.value = 0.3;
    this.master = c.createGain(); this.master.gain.value = this.on ? 0.9 : 0;
    this.master.connect(this.comp); this.comp.connect(c.destination);
    const len = c.sampleRate, nb = c.createBuffer(1, len, c.sampleRate), d = nb.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    this.noise = nb;
    // на старых iPhone без audioSession — «разбудить» звук тихим тегом <audio>
    if (!navigator.audioSession) {
      try { const a = document.createElement('audio'); a.src = 'data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjI5LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAABAAADQgD///////////////////////////////////////////8AAAA5TEFNRTMuMTAwAZYAAAAAAAAAABQ4JAMGQgAAOAAAA0LeZ8a4AAAAAAAAAAAAAAAAAAAA'; a.loop = true; a.volume = 0.01; a.play().catch(() => {}); this.keep = a; } catch (e) { /* нет */ }
    }
    const unlock = () => { if (c.state !== 'running') c.resume(); };
    addEventListener('touchend', unlock, { passive: true }); addEventListener('click', unlock);
    const decode = () => Promise.all(Object.entries(this.raw).map(([k, b]) => new Promise((res) => {
      try { c.decodeAudioData(b.slice(0), (x) => { this.buf[k] = x; res(); }, () => res()); } catch (e) { res(); }
    }))).then(() => { for (const n of LOOPS) this.L[n] = this.loop(n); this.ready = true; });
    (this.loading || Promise.resolve()).then(decode);
  }
  loop(name) {
    const b = this.buf[name]; if (!b) return null;
    const s = this.ctx.createBufferSource(); s.buffer = b; s.loop = true;
    const g = this.ctx.createGain(); g.gain.value = 0;
    s.connect(g); g.connect(this.master); s.start(0, Math.random() * b.duration);
    return { s, g };
  }
  lv(name, vol, rate, t = 0.25) {
    const l = this.L[name]; if (!l || !this.ctx) return;
    const now = this.ctx.currentTime;
    l.g.gain.setTargetAtTime(Math.max(0, vol), now, t);
    if (rate) l.s.playbackRate.setTargetAtTime(rate, now, t);
  }
  setOn(on) { this.on = on; if (this.master) this.master.gain.value = on ? 0.9 : 0; }
  listen(p, f) {
    if (!this.ctx) return;
    const L = this.ctx.listener, t = this.ctx.currentTime;
    if (L.positionX) {
      L.positionX.setValueAtTime(p.x, t); L.positionY.setValueAtTime(p.y, t); L.positionZ.setValueAtTime(p.z, t);
      L.forwardX.setValueAtTime(f.x, t); L.forwardY.setValueAtTime(f.y, t); L.forwardZ.setValueAtTime(f.z, t);
      L.upX.setValueAtTime(0, t); L.upY.setValueAtTime(1, t); L.upZ.setValueAtTime(0, t);
    } else { L.setPosition(p.x, p.y, p.z); L.setOrientation(f.x, f.y, f.z, 0, 1, 0); }
  }
  play(name, o = {}) {
    if (!this.ctx || !this.on) return null;
    const v = LIST[name];
    const key = v ? name + (v[0] + Math.floor(Math.random() * (v[1] - v[0] + 1))) : name;
    const b = this.buf[key]; if (!b) return null;
    if (this.voices > 32 && !o.must) return null;
    const c = this.ctx, s = c.createBufferSource(); s.buffer = b;
    s.playbackRate.value = (o.rate || 1) * (o.vary ? 1 + (Math.random() - 0.5) * o.vary : 1);
    const g = c.createGain(); g.gain.value = o.vol ?? 1;
    let out = g;
    if (o.pos) {
      const pn = c.createPanner(); pn.panningModel = 'equalpower'; pn.distanceModel = 'inverse'; pn.refDistance = o.ref || 3; pn.maxDistance = 150; pn.rolloffFactor = o.roll || 1.2;
      if (pn.positionX) { pn.positionX.value = o.pos.x; pn.positionY.value = o.pos.y + 1.2; pn.positionZ.value = o.pos.z; } else pn.setPosition(o.pos.x, o.pos.y + 1.2, o.pos.z);
      g.connect(pn); out = pn;
    }
    s.connect(g); out.connect(this.master);
    this.voices++; s.onended = () => { this.voices--; };
    s.start(c.currentTime + (o.delay || 0));
    return { s, g };
  }

  // ---- поезд: вызывается каждый кадр. Слоёв мало, чтобы не было «каши»:
  // мотор (главный), качение (одно), стук на стыках — отдельными щелчками, тормоза и воздух — только когда работают.
  // t: { v, rpm, load, on, starting, TC, dTM, view: 'cab'|'chase'|'foot'|'inside', dist }
  train(t) {
    if (!this.ready) return;
    const v = Math.abs(t.v), out = t.view === 'foot' || t.view === 'chase';
    const near = t.view === 'foot' ? Math.max(0.06, Math.min(1, 10 / (t.dist + 2))) : t.view === 'inside' ? 0.35 : t.view === 'chase' ? 0.8 : 1;
    // мотор: нагрузка — громкость, обороты — высота (в умеренных пределах)
    const dRate = t.on ? 0.9 + Math.min(1, t.rpm / 1000) * 0.32 : t.starting ? 0.55 + t.starting * 0.35 : 0.9;
    const dVol = t.on ? 0.38 + t.load * 0.42 : t.starting ? 0.3 * t.starting : 0;
    this.lv('diesel_idle', dVol * near, dRate, 0.4);
    // качение: в кабине — запись из кабины, снаружи — проходящий поезд
    const roll = Math.min(1, v / 22);
    this.lv('cab_ride', !out ? roll * 0.42 * (t.view === 'inside' ? 1.3 : 1) : 0, 0.92 + roll * 0.12, 0.6);
    this.lv('train_pass', out ? roll * 0.7 * near : 0, 0.92 + roll * 0.12, 0.6);
    // колодки визжат только при торможении на малой скорости
    const sq = t.TC > 1.0 && v > 0.3 && v < 9 ? Math.min(0.45, (t.TC - 1) / 2.8 * 0.5) * Math.min(1, v / 1.2) : 0;
    this.lv('brake_squeal', sq * Math.min(1, near * 1.4), 1, 0.2);
    // воздух из тормозной магистрали — пока кран в положении торможения
    this.lv('air_loop', t.dTM < -0.08 && t.view !== 'foot' ? Math.min(0.45, -t.dTM * 0.35) : 0, 1, 0.12);
  }
  ambience(o) {
    if (!this.ready) return;
    const out = o.outside ? 1 : 0.3;
    this.lv('wind', (o.windK * 0.16 + Math.min(0.18, o.speed / 120)) * out * (o.winter ? 0.4 : 1), 1, 1.5);
    this.lv('wind_cold', o.winter ? (0.1 + o.windK * 0.12) * out : 0, 1, 1.5);
    this.lv('rain', o.rain ? 0.35 * out : 0, 1, 1.5);
    this.lv('birds', o.birds && o.outside ? 0.1 : 0, 1, 3);
    this.lv('rummage', o.searching ? 0.6 : 0, 1, 0.2);
  }
  // ---- события поезда
  hornOn() {
    if (!this.ctx || this.hornV) return;
    const b = this.buf.horn; if (!b) return;
    const s = this.ctx.createBufferSource(); s.buffer = b; s.loop = true; s.loopStart = 0.7; s.loopEnd = Math.min(b.duration - 0.6, 2.6);
    const g = this.ctx.createGain(); g.gain.value = this.on ? 1 : 0;
    s.connect(g); g.connect(this.master); s.start();
    this.hornV = { s, g };
  }
  hornOff() {
    if (!this.hornV) return;
    const { s, g } = this.hornV, t = this.ctx.currentTime;
    g.gain.setTargetAtTime(0, t, 0.15); s.stop(t + 1); this.hornV = null;
  }
  clack(v, offsets, vol = 1) {
    if (v < 1) return;
    const k = Math.min(0.7, 0.18 + v / 40) * vol;
    for (const o of offsets) this.play(Math.random() < 0.5 ? 'clack' : 'clack2', { vol: k, rate: 0.85 + Math.random() * 0.1, delay: o / v });
  }
  couplers(n, vol = 1) { for (let i = 0; i < n; i++) this.play('clank', { vol: vol * (1 - i * 0.12), rate: 0.75 + Math.random() * 0.2, delay: i * 0.35 + Math.random() * 0.1 }); }
  // ---- оружие и прочее
  shot(kind) {
    const map = { pistol: 'g_pm', smg: 'g_bizon', rifle: 'g_ak', shotgun: 'g_toz', sniper: 'g_svd', turret: 'g_turret' };
    this.play(map[kind] || 'g_pm', { vol: 0.95, vary: 0.05, must: true });
  }
  tone(freq, dur, type = 'sine', vol = 0.2, when = 0, slide = 0) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const o = c.createOscillator(); o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), t + dur);
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.master); o.start(t); o.stop(t + dur + 0.05);
  }
  burst(dur, freq, type, vol, when = 0) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const s = c.createBufferSource(); s.buffer = this.noise;
    const f = c.createBiquadFilter(); f.type = type; f.frequency.value = freq;
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f); f.connect(g); g.connect(this.master); s.start(t); s.stop(t + dur + 0.05);
  }
  // голоса зомби: не больше одного стона за ~1,3 с, иначе сливаются в гул
  groan(vol, pos, runner) {
    const now = this.ctx ? this.ctx.currentTime : 0;
    if (now - (this.lastGroan || 0) < 1.3) return;
    this.lastGroan = now;
    const pool = runner ? ['z_growl', 'z_grunt'] : ['z_moan', 'z_mmoan', 'z_growl'];
    this.play(pool[Math.floor(Math.random() * pool.length)], { pos, vol: 0.55 * vol + 0.25, vary: 0.12, ref: 4 });
  }
  zstep(pos) {
    const now = this.ctx ? this.ctx.currentTime : 0;
    if (now - (this.lastZStep || 0) < 0.16) return;
    this.lastZStep = now;
    this.play(Math.random() < 0.15 ? 'z_drag' : 'z_step', { pos, vol: 0.5, vary: 0.15, ref: 2 });
  }
  scream(pos) { this.play('z_scream', { pos, vol: 1.2, ref: 8, must: true }); }
  splat(pos) { this.play('flesh', { pos, vol: 1, vary: 0.1 }); this.play('clank', { pos, vol: 0.7, rate: 0.8 }); }
  thud() { this.play('clank', { vol: 0.7, vary: 0.2 }); }
  beep() { for (let i = 0; i < 3; i++) this.tone(1000, 0.12, 'square', 0.08, i * 0.25); }
  alarm() { for (let i = 0; i < 4; i++) { this.tone(700, 0.18, 'square', 0.1, i * 0.4); this.tone(500, 0.18, 'square', 0.1, i * 0.4 + 0.2); } }
  starter() { this.play('door_handle', { vol: 0.5, rate: 0.8 }); this.play('air_release', { vol: 0.35, rate: 1.3, delay: 0.4 }); }
  click() { this.play('door_handle', { vol: 0.25, rate: 2.2 }); }
  notch() { this.play('door_handle', { vol: 0.28, rate: 1.7, vary: 0.1 }); }
  coin() { this.play('coins', { vol: 0.7 }); }
}
