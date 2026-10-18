// Звук: настоящие записи (OpenGameArt CC0, Kenney CC0, Wikimedia Commons) + немного синтеза для сигналов пульта.
const LIST = {
  z_moan: [1, 6], z_growl: [1, 10], z_attack: [1, 3], z_scream: null, z_death: [1, 2],
  st_grass: [0, 3], st_concrete: [0, 3], st_snow: [0, 3], st_wood: [0, 3], st_metal: [0, 3], st_gravel: [0, 3],
  g_pm: null, g_bizon: null, g_toz: null, g_ak: null, g_svd: null, g_turret: null, g_reload: null, g_reload2: null, g_cock: null, g_empty: null,
  hit_metal: [0, 2], flesh: [1, 3], body_fall: null, clack: null, clack2: null, smash_wood: null, smash_metal: null,
  cloth: [1, 4], coins: null, drop: null, latch: null, door_open: null, door_close: null, eat: [1, 3], drink: [1, 2], bottle: null,
  horn: null, hiss: [1, 2], engine: null, rumble: null, wind: null, crows: null,
};
const FILES = [];
for (const [k, v] of Object.entries(LIST)) if (v) for (let i = v[0]; i <= v[1]; i++) FILES.push(k + i); else FILES.push(k);

export class Audio {
  constructor() { this.ctx = null; this.on = true; this.raw = {}; this.buf = {}; this.voices = 0; }
  // скачать заранее (до касания экрана декодировать нельзя)
  preload(base = 'assets/sfx/') {
    this.loading = Promise.all(FILES.map((f) => fetch(base + f + '.mp3').then((r) => (r.ok ? r.arrayBuffer() : null)).then((b) => { if (b) this.raw[f] = b; }).catch(() => {})));
    return this.loading;
  }
  init() {
    if (this.ctx) { if (this.ctx.state !== 'running') this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const c = this.ctx = new AC();
    this.comp = c.createDynamicsCompressor(); this.comp.threshold.value = -14; this.comp.ratio.value = 4;
    this.master = c.createGain(); this.master.gain.value = 0.9;
    this.master.connect(this.comp); this.comp.connect(c.destination);
    // шумовой буфер для синтеза
    const len = c.sampleRate * 2, nb = c.createBuffer(1, len, c.sampleRate), d = nb.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    this.noise = nb;
    this.hissN = this.loopNoise('highpass', 2500);
    this.slipS = this.loopNoise('bandpass', 1400);
    // низкий синтезированный «пульс» дизеля поверх записи
    this.puls = c.createGain(); this.puls.gain.value = 0;
    const lp = c.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 160;
    this.po = c.createOscillator(); this.po.type = 'sawtooth'; this.po.connect(lp); lp.connect(this.puls); this.puls.connect(this.master); this.po.start();
    const decode = () => Promise.all(Object.entries(this.raw).map(([k, b]) => new Promise((res) => {
      try { c.decodeAudioData(b.slice(0), (x) => { this.buf[k] = x; res(); }, () => res()); } catch (e) { res(); }
    }))).then(() => this.startLoops());
    (this.loading || Promise.resolve()).then(decode);
  }
  startLoops() {
    this.eng = this.loop('engine'); this.rum = this.loop('rumble'); this.wnd = this.loop('wind');
  }
  loop(name) {
    const b = this.buf[name]; if (!b) return null;
    const s = this.ctx.createBufferSource(); s.buffer = b; s.loop = true;
    const g = this.ctx.createGain(); g.gain.value = 0;
    s.connect(g); g.connect(this.master); s.start(0, Math.random() * b.duration);
    return { s, g };
  }
  loopNoise(type, freq) {
    const c = this.ctx, s = c.createBufferSource(); s.buffer = this.noise; s.loop = true;
    const f = c.createBiquadFilter(); f.type = type; f.frequency.value = freq;
    const g = c.createGain(); g.gain.value = 0;
    s.connect(f); f.connect(g); g.connect(this.master); s.start();
    return g;
  }
  set(g, v, t = 0.08) { if (this.ctx && g) (g.gain || g).setTargetAtTime(this.on ? v : 0, this.ctx.currentTime, t); }
  // слушатель — камера
  listen(p, f) {
    if (!this.ctx) return;
    const L = this.ctx.listener, t = this.ctx.currentTime;
    if (L.positionX) {
      L.positionX.setValueAtTime(p.x, t); L.positionY.setValueAtTime(p.y, t); L.positionZ.setValueAtTime(p.z, t);
      L.forwardX.setValueAtTime(f.x, t); L.forwardY.setValueAtTime(f.y, t); L.forwardZ.setValueAtTime(f.z, t);
      L.upX.setValueAtTime(0, t); L.upY.setValueAtTime(1, t); L.upZ.setValueAtTime(0, t);
    } else { L.setPosition(p.x, p.y, p.z); L.setOrientation(f.x, f.y, f.z, 0, 1, 0); }
  }
  // проиграть запись; name — база, вариант выбирается случайно
  play(name, o = {}) {
    if (!this.ctx || !this.on) return null;
    const v = LIST[name];
    const key = v ? name + (v[0] + Math.floor(Math.random() * (v[1] - v[0] + 1))) : name;
    const b = this.buf[key]; if (!b) return null;
    if (this.voices > 28 && !o.must) return null;
    const c = this.ctx, s = c.createBufferSource(); s.buffer = b;
    s.playbackRate.value = (o.rate || 1) * (o.vary ? 1 + (Math.random() - 0.5) * o.vary : 1);
    const g = c.createGain(); g.gain.value = o.vol ?? 1;
    let out = g;
    if (o.pos) {
      const pn = c.createPanner(); pn.panningModel = 'equalpower'; pn.distanceModel = 'inverse'; pn.refDistance = o.ref || 3; pn.maxDistance = 120; pn.rolloffFactor = o.roll || 1.3;
      if (pn.positionX) { pn.positionX.value = o.pos.x; pn.positionY.value = o.pos.y + 1.2; pn.positionZ.value = o.pos.z; } else pn.setPosition(o.pos.x, o.pos.y + 1.2, o.pos.z);
      g.connect(pn); out = pn;
    }
    s.connect(g); out.connect(this.master);
    this.voices++; s.onended = () => { this.voices--; };
    s.start(c.currentTime + (o.delay || 0));
    return { s, g };
  }
  // ---- поезд
  engine(rpm, load, on) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    if (this.eng) {
      this.eng.s.playbackRate.setTargetAtTime(0.45 + rpm / 1000 * 0.75, t, 0.25);
      this.set(this.eng.g, on ? 0.35 + load * 0.45 : rpm > 60 ? 0.2 : 0, 0.3);
    }
    this.po.frequency.setTargetAtTime(14 + rpm / 1000 * 30, t, 0.2);
    this.set(this.puls, on ? 0.06 + load * 0.12 : 0, 0.3);
  }
  rolling(v) {
    if (!this.ctx) return;
    const a = Math.abs(v);
    if (this.rum) { this.rum.s.playbackRate.setTargetAtTime(0.7 + Math.min(a, 28) / 28 * 0.6, this.ctx.currentTime, 0.4); this.set(this.rum.g, Math.min(0.55, a / 30), 0.4); }
  }
  ambience(wind, speed) { if (this.wnd) this.set(this.wnd.g, Math.min(0.45, wind * 0.25 + Math.abs(speed) / 90), 0.8); }
  clack(v, offsets) {
    if (v < 1) return;
    const vol = Math.min(0.9, 0.2 + v / 30);
    for (const o of offsets) this.play(Math.random() < 0.5 ? 'clack' : 'clack2', { vol, rate: 0.85 + Math.random() * 0.15, delay: o / v });
  }
  hornOn() {
    if (!this.ctx || this.hornV) return;
    const b = this.buf.horn; if (!b) return;
    const s = this.ctx.createBufferSource(); s.buffer = b; s.loop = true; s.loopStart = 0.9; s.loopEnd = 2.6;
    const g = this.ctx.createGain(); g.gain.value = this.on ? 0.8 : 0;
    s.connect(g); g.connect(this.master); s.start();
    this.hornV = { s, g };
  }
  hornOff() {
    if (!this.hornV) return;
    const { s, g } = this.hornV, t = this.ctx.currentTime;
    g.gain.setTargetAtTime(0, t, 0.12); s.stop(t + 0.8); this.hornV = null;
  }
  // ---- выстрелы и прочее
  shot(kind) {
    const map = { pistol: 'g_pm', smg: 'g_bizon', rifle: 'g_ak', shotgun: 'g_toz', sniper: 'g_svd', turret: 'g_turret' };
    if (!this.play(map[kind] || 'g_pm', { vol: 0.9, vary: 0.06, must: true })) this.burst(0.15, 1200, 'lowpass', 0.5);
  }
  burst(dur, freq, type, vol, when = 0, q = 1) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const s = c.createBufferSource(); s.buffer = this.noise;
    const f = c.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f); f.connect(g); g.connect(this.master); s.start(t, Math.random()); s.stop(t + dur + 0.05);
  }
  tone(freq, dur, type = 'sine', vol = 0.2, when = 0, slide = 0) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const o = c.createOscillator(); o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), t + dur);
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.master); o.start(t); o.stop(t + dur + 0.05);
  }
  groan(vol, pos, runner) { this.play(runner || Math.random() < 0.4 ? 'z_growl' : 'z_moan', { pos, vol: 0.9 * vol + 0.3, vary: 0.15 }); }
  scream(pos) { this.play('z_scream', { pos, vol: 1.2, ref: 8, must: true }); }
  splat(pos) { this.play('flesh', { pos, vol: 1, vary: 0.1 }); this.play('hit_metal', { vol: 0.5, rate: 0.7 }); }
  thud() { this.play('hit_metal', { vol: 0.7, vary: 0.2 }); }
  beep() { for (let i = 0; i < 3; i++) this.tone(1000, 0.12, 'square', 0.08, i * 0.25); }
  alarm() { for (let i = 0; i < 4; i++) { this.tone(700, 0.18, 'square', 0.1, i * 0.4); this.tone(500, 0.18, 'square', 0.1, i * 0.4 + 0.2); } }
  starter() { this.burst(2.5, 600, 'bandpass', 0.25, 0, 3); this.tone(40, 3, 'sawtooth', 0.15, 0, 20); this.play('latch', { vol: 0.6 }); }
  click() { if (!this.play('latch', { vol: 0.35, rate: 1.6 })) this.burst(0.03, 3000, 'highpass', 0.15); }
  coin() { if (!this.play('coins', { vol: 0.7 })) { this.tone(1200, 0.1, 'triangle', 0.12); this.tone(1600, 0.15, 'triangle', 0.12, 0.08); } }
}
