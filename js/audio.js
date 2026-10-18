// Весь звук синтезируется — никаких файлов.
export class Audio {
  constructor() { this.ctx = null; this.on = true; }
  init() {
    if (this.ctx) { this.ctx.resume && this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const c = this.ctx = new AC();
    this.master = c.createGain(); this.master.gain.value = 0.7; this.master.connect(c.destination);
    // шумовой буфер
    const len = c.sampleRate * 2, buf = c.createBuffer(1, len, c.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    this.noise = buf;
    // дизель: две пилы + шум через фильтр
    this.eng = c.createGain(); this.eng.gain.value = 0;
    const lp = c.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 380; lp.Q.value = 2;
    this.o1 = c.createOscillator(); this.o1.type = 'sawtooth';
    this.o2 = c.createOscillator(); this.o2.type = 'square';
    const g2 = c.createGain(); g2.gain.value = 0.35;
    this.o1.connect(lp); this.o2.connect(g2); g2.connect(lp);
    this.engLp = lp;
    lp.connect(this.eng); this.eng.connect(this.master);
    this.o1.start(); this.o2.start();
    // шипение тормоза и ветер
    this.hiss = this.loopNoise('highpass', 2500); this.wind = this.loopNoise('bandpass', 500);
    this.slipS = this.loopNoise('bandpass', 1400);
    // тифон
    this.horn = c.createGain(); this.horn.gain.value = 0;
    const hf = c.createBiquadFilter(); hf.type = 'lowpass'; hf.frequency.value = 1800;
    for (const f of [311, 370]) { const o = c.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f; o.connect(hf); o.start(); }
    hf.connect(this.horn); this.horn.connect(this.master);
  }
  loopNoise(type, freq) {
    const c = this.ctx, s = c.createBufferSource(); s.buffer = this.noise; s.loop = true;
    const f = c.createBiquadFilter(); f.type = type; f.frequency.value = freq;
    const g = c.createGain(); g.gain.value = 0;
    s.connect(f); f.connect(g); g.connect(this.master); s.start();
    return g;
  }
  set(g, v, t = 0.08) { if (this.ctx && g) g.gain.setTargetAtTime(this.on ? v : 0, this.ctx.currentTime, t); }
  engine(rpm, load, on) {
    if (!this.ctx) return;
    const f = 18 + rpm / 1000 * 38;
    this.o1.frequency.setTargetAtTime(f, this.ctx.currentTime, 0.1);
    this.o2.frequency.setTargetAtTime(f * 1.5, this.ctx.currentTime, 0.1);
    this.engLp.frequency.setTargetAtTime(240 + load * 500 + rpm * 0.2, this.ctx.currentTime, 0.1);
    this.set(this.eng, on ? 0.16 + load * 0.22 : rpm > 50 ? 0.08 : 0, 0.15);
  }
  burst(dur, freq, type, vol, when = 0, q = 1) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const s = c.createBufferSource(); s.buffer = this.noise;
    const f = c.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f); f.connect(g); g.connect(this.master);
    s.start(t, Math.random()); s.stop(t + dur + 0.05);
  }
  tone(freq, dur, type = 'sine', vol = 0.2, when = 0, slide = 0) {
    if (!this.ctx || !this.on) return;
    const c = this.ctx, t = c.currentTime + when;
    const o = c.createOscillator(); o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), t + dur);
    const g = c.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.master); o.start(t); o.stop(t + dur + 0.05);
  }
  // перестук: стык рельсов каждые 25 м, пары тележек
  clack(v, offsets) {
    if (v < 1) return;
    const vol = Math.min(0.5, 0.1 + v / 60);
    for (const o of offsets) this.burst(0.07, 180, 'lowpass', vol, o / v, 1.5);
  }
  shot(kind) {
    const k = { pistol: [0.14, 1600, 0.5], smg: [0.09, 1800, 0.4], rifle: [0.16, 1200, 0.6], shotgun: [0.3, 800, 0.8], sniper: [0.45, 700, 0.9], turret: [0.12, 1100, 0.35] }[kind] || [0.15, 1200, 0.5];
    this.burst(k[0], k[1], 'lowpass', k[2]); this.burst(0.03, 4000, 'highpass', k[2] * 0.6);
  }
  groan(vol) { const f = 70 + Math.random() * 60; this.tone(f, 0.9, 'sawtooth', 0.06 * vol, 0, -25); this.burst(0.6, 400 + Math.random() * 300, 'bandpass', 0.05 * vol, 0, 4); }
  scream() { this.tone(900, 1.2, 'sawtooth', 0.12, 0, -500); this.burst(1.0, 2000, 'bandpass', 0.15, 0, 2); }
  splat() { this.burst(0.25, 300, 'lowpass', 0.6); this.tone(60, 0.2, 'sine', 0.4); }
  thud() { this.burst(0.2, 150, 'lowpass', 0.5); }
  beep() { for (let i = 0; i < 3; i++) this.tone(1000, 0.12, 'square', 0.08, i * 0.25); }
  alarm() { for (let i = 0; i < 4; i++) { this.tone(700, 0.18, 'square', 0.1, i * 0.4); this.tone(500, 0.18, 'square', 0.1, i * 0.4 + 0.2); } }
  starter() { this.burst(2.5, 600, 'bandpass', 0.25, 0, 3); this.tone(40, 3, 'sawtooth', 0.15, 0, 20); }
  click() { this.burst(0.03, 3000, 'highpass', 0.15); }
  coin() { this.tone(1200, 0.1, 'triangle', 0.12); this.tone(1600, 0.15, 'triangle', 0.12, 0.08); }
}
