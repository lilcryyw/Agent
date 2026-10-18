// Значки предметов: рисуются на холсте в духе советских этикеток (объём, блики, тени).
const S = 128, cache = {};
function cv() { const c = document.createElement('canvas'); c.width = c.height = S; return c; }
const lg = (x, x0, y0, x1, y1, stops) => { const g = x.createLinearGradient(x0, y0, x1, y1); stops.forEach(([o, c]) => g.addColorStop(o, c)); return g; };
const rg = (x, cx, cy, r, stops) => { const g = x.createRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 0.1, cx, cy, r); stops.forEach(([o, c]) => g.addColorStop(o, c)); return g; };
function shade(c, k) { // осветлить/затемнить #rrggbb
  const n = parseInt(c.slice(1), 16), f = (v) => Math.max(0, Math.min(255, Math.round(v * k)));
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}
function cyl(c) { return [[0, shade(c, 0.45)], [0.25, shade(c, 1.15)], [0.45, shade(c, 1.35)], [0.7, shade(c, 0.9)], [1, shade(c, 0.4)]]; }
function shadow(x, cx, w) { x.fillStyle = 'rgba(0,0,0,0.35)'; x.beginPath(); x.ellipse(cx, 116, w, 6, 0, 0, 7); x.fill(); }
function text(x, t, cx, cy, size, col, w = 60, font = 'bold') {
  x.fillStyle = col; x.textAlign = 'center'; x.textBaseline = 'middle';
  let s = size; x.font = `${font} ${s}px "Arial Narrow", Arial, sans-serif`;
  while (x.measureText(t).width > w && s > 6) { s--; x.font = `${font} ${s}px "Arial Narrow", Arial, sans-serif`; }
  x.fillText(t, cx, cy);
}
function rrect(x, a, b, w, h, r) { x.beginPath(); x.roundRect ? x.roundRect(a, b, w, h, r) : x.rect(a, b, w, h); }

const D = {
  can(x, [body, lab, t1, t2, lab2]) {
    shadow(x, 64, 34);
    x.fillStyle = lg(x, 30, 0, 98, 0, cyl(body)); rrect(x, 30, 34, 68, 78, 6); x.fill();
    x.fillStyle = lg(x, 30, 0, 98, 0, cyl(lab)); x.fillRect(30, 50, 68, 46);
    if (lab2) { x.fillStyle = lab2; x.fillRect(30, 50, 68, 7); x.fillRect(30, 89, 68, 7); }
    text(x, t1, 64, 68, 15, '#fff6e0', 62); if (t2) text(x, t2, 64, 82, 10, '#ffe9b0', 60, 'normal');
    x.fillStyle = rg(x, 64, 34, 34, [[0, '#f4f4f4'], [0.7, '#9aa0a6'], [1, '#5a6066']]); x.beginPath(); x.ellipse(64, 34, 34, 9, 0, 0, 7); x.fill();
    x.strokeStyle = '#6a7076'; x.lineWidth = 2; x.beginPath(); x.ellipse(64, 34, 29, 7, 0, 0, 7); x.stroke();
  },
  flat(x, [body, lab, t1]) { // плоская банка (килька)
    shadow(x, 64, 46);
    x.fillStyle = lg(x, 0, 60, 0, 104, [[0, shade(body, 1.3)], [1, shade(body, 0.6)]]); rrect(x, 16, 62, 96, 42, 14); x.fill();
    x.fillStyle = rg(x, 64, 62, 50, [[0, '#f0f0f0'], [1, '#7a8086']]); x.beginPath(); x.ellipse(64, 62, 48, 18, 0, 0, 7); x.fill();
    x.fillStyle = lab; x.fillRect(22, 76, 84, 20); text(x, t1, 64, 86, 12, '#fff3d8', 80);
    x.strokeStyle = '#9aa0a6'; x.lineWidth = 3; x.beginPath(); x.arc(92, 58, 6, 0, 7); x.stroke();
  },
  jar(x, [fill, lid, t1]) {
    shadow(x, 64, 32);
    x.fillStyle = lg(x, 34, 0, 94, 0, cyl(fill)); rrect(x, 34, 40, 60, 74, 12); x.fill();
    x.fillStyle = 'rgba(255,255,255,0.25)'; x.fillRect(42, 48, 6, 56);
    x.fillStyle = lg(x, 36, 0, 92, 0, cyl(lid)); rrect(x, 36, 26, 56, 16, 4); x.fill();
    if (t1) { x.fillStyle = '#f2ead2'; x.fillRect(38, 66, 52, 26); text(x, t1, 64, 79, 11, '#5a2a1a', 48); }
  },
  bottle(x, [glass, liquid, lab, t1, cap = '#c8c0a0', tall = 1]) {
    shadow(x, 64, 22);
    const top = 14 + (1 - tall) * 30;
    x.fillStyle = lg(x, 42, 0, 86, 0, cyl(glass));
    x.beginPath(); x.moveTo(56, top + 14); x.lineTo(72, top + 14); x.lineTo(72, top + 34); x.quadraticCurveTo(86, top + 44, 86, top + 60); x.lineTo(86, 112); x.lineTo(42, 112); x.lineTo(42, top + 60); x.quadraticCurveTo(42, top + 44, 56, top + 34); x.closePath(); x.fill();
    if (liquid) { x.fillStyle = liquid; x.globalAlpha = 0.45; x.fillRect(44, top + 58, 40, 52 - (top - 14) * 0.2); x.globalAlpha = 1; }
    x.fillStyle = cap; x.fillRect(55, top, 18, 16);
    if (lab) { x.fillStyle = lab; x.fillRect(42, 70, 44, 26); text(x, t1, 64, 83, 11, '#2a1a10', 40); }
    x.fillStyle = 'rgba(255,255,255,0.3)'; x.fillRect(48, top + 50, 4, 54);
  },
  jug(x, [col, t1]) {
    shadow(x, 64, 34);
    x.fillStyle = lg(x, 28, 0, 100, 0, cyl(col)); rrect(x, 28, 36, 72, 78, 14); x.fill();
    x.fillStyle = 'rgba(255,255,255,0.35)'; x.fillRect(36, 44, 8, 60);
    x.fillStyle = '#3a6ab0'; x.fillRect(56, 18, 16, 20);
    x.strokeStyle = shade(col, 0.6); x.lineWidth = 6; x.beginPath(); x.moveTo(80, 40); x.quadraticCurveTo(98, 28, 96, 50); x.stroke();
    x.fillStyle = '#f2f6fa'; x.fillRect(34, 70, 60, 22); text(x, t1, 64, 81, 12, '#1d4f8c', 56);
  },
  box(x, [col, side, t1, t2, w = 70, h = 60]) {
    const x0 = 64 - w / 2 - 6, y0 = 112 - h;
    shadow(x, 64, w / 2 + 6);
    x.fillStyle = shade(col, 1.25); x.beginPath(); x.moveTo(x0, y0); x.lineTo(x0 + 14, y0 - 12); x.lineTo(x0 + w + 14, y0 - 12); x.lineTo(x0 + w, y0); x.fill();
    x.fillStyle = side || shade(col, 0.6); x.beginPath(); x.moveTo(x0 + w, y0); x.lineTo(x0 + w + 14, y0 - 12); x.lineTo(x0 + w + 14, y0 + h - 12); x.lineTo(x0 + w, y0 + h); x.fill();
    x.fillStyle = lg(x, 0, y0, 0, y0 + h, [[0, shade(col, 1.1)], [1, shade(col, 0.85)]]); x.fillRect(x0, y0, w, h);
    text(x, t1, x0 + w / 2, y0 + h * 0.42, 13, '#fff4dc', w - 8); if (t2) text(x, t2, x0 + w / 2, y0 + h * 0.72, 9, '#ffe6b0', w - 8, 'normal');
  },
  sack(x, [col, t1]) {
    shadow(x, 64, 38);
    x.fillStyle = lg(x, 24, 0, 104, 0, cyl(col));
    x.beginPath(); x.moveTo(48, 26); x.quadraticCurveTo(64, 34, 80, 26); x.lineTo(84, 40); x.quadraticCurveTo(108, 60, 102, 108); x.quadraticCurveTo(64, 118, 26, 108); x.quadraticCurveTo(20, 60, 44, 40); x.closePath(); x.fill();
    x.strokeStyle = '#6a4a2a'; x.lineWidth = 3; x.beginPath(); x.moveTo(46, 36); x.lineTo(82, 36); x.stroke();
    for (let i = 0; i < 40; i++) { x.fillStyle = 'rgba(0,0,0,0.08)'; x.fillRect(30 + Math.random() * 68, 44 + Math.random() * 60, 2, 2); }
    if (t1) text(x, t1, 64, 80, 13, '#3a2a18', 60);
  },
  medkit(x, [col, t1]) {
    shadow(x, 64, 42);
    x.fillStyle = lg(x, 0, 40, 0, 110, [[0, shade(col, 1.15)], [1, shade(col, 0.75)]]); rrect(x, 22, 40, 84, 70, 8); x.fill();
    x.fillStyle = '#2a2a2a'; x.fillRect(52, 30, 24, 10);
    x.fillStyle = '#d02020'; x.fillRect(56, 54, 16, 42); x.fillRect(43, 67, 42, 16);
    if (t1) text(x, t1, 64, 104, 8, '#5a1010', 70);
  },
  roll(x) {
    shadow(x, 64, 30);
    x.fillStyle = lg(x, 0, 40, 0, 104, [[0, '#ffffff'], [0.5, '#e8e4d8'], [1, '#b8b0a0']]); x.fillRect(34, 46, 60, 58);
    x.fillStyle = rg(x, 34, 75, 29, [[0, '#ffffff'], [1, '#c8c0b0']]); x.beginPath(); x.ellipse(34, 75, 10, 29, 0, 0, 7); x.fill();
    x.fillStyle = '#a89880'; x.beginPath(); x.ellipse(34, 75, 4, 10, 0, 0, 7); x.fill();
    x.strokeStyle = 'rgba(0,0,0,0.08)'; for (let i = 0; i < 8; i++) { x.beginPath(); x.moveTo(40 + i * 7, 46); x.lineTo(40 + i * 7, 104); x.stroke(); }
  },
  pills(x, [col, t1]) {
    shadow(x, 64, 36);
    x.fillStyle = lg(x, 0, 30, 0, 110, [[0, '#f2f2f2'], [1, '#a8adb2']]); rrect(x, 28, 30, 72, 80, 6); x.fill();
    for (let r = 0; r < 4; r++) for (let c = 0; c < 2; c++) { x.fillStyle = rg(x, 50 + c * 28, 46 + r * 18, 7, [[0, '#ffffff'], [1, col]]); x.beginPath(); x.arc(50 + c * 28, 46 + r * 18, 7, 0, 7); x.fill(); }
    if (t1) { x.fillStyle = col; x.fillRect(28, 100, 72, 10); }
  },
  syringe(x) {
    shadow(x, 64, 40);
    x.save(); x.translate(64, 70); x.rotate(-0.6);
    x.fillStyle = lg(x, 0, -8, 0, 8, [[0, '#e8f8ff'], [1, '#9ab8c8']]); x.fillRect(-40, -8, 60, 16);
    x.fillStyle = '#40d070'; x.fillRect(-36, -5, 40, 10);
    x.fillStyle = '#555'; x.fillRect(20, -2, 30, 4); x.fillStyle = '#2a2a2a'; x.fillRect(-52, -10, 12, 20);
    x.restore(); text(x, 'Х-7', 64, 108, 14, '#40d070', 40);
  },
  jerry(x, [col]) {
    shadow(x, 64, 36);
    x.fillStyle = lg(x, 0, 30, 0, 112, [[0, shade(col, 1.2)], [1, shade(col, 0.6)]]); rrect(x, 30, 30, 68, 82, 6); x.fill();
    x.strokeStyle = shade(col, 0.55); x.lineWidth = 5; x.beginPath(); x.moveTo(36, 50); x.lineTo(92, 104); x.moveTo(92, 50); x.lineTo(36, 104); x.stroke();
    x.fillStyle = shade(col, 0.5); x.fillRect(36, 20, 30, 12); x.fillStyle = '#888'; x.fillRect(74, 18, 12, 14);
  },
  barrel(x, [col]) {
    shadow(x, 64, 36);
    x.fillStyle = lg(x, 28, 0, 100, 0, cyl(col)); rrect(x, 28, 24, 72, 90, 8); x.fill();
    x.fillStyle = 'rgba(0,0,0,0.3)'; x.fillRect(28, 50, 72, 4); x.fillRect(28, 84, 72, 4);
    x.fillStyle = rg(x, 64, 24, 36, [[0, shade(col, 1.2)], [1, shade(col, 0.5)]]); x.beginPath(); x.ellipse(64, 24, 36, 9, 0, 0, 7); x.fill();
  },
  gear(x) {
    shadow(x, 64, 38);
    x.save(); x.translate(64, 66);
    x.fillStyle = rg(x, 0, 0, 44, [[0, '#d8dce0'], [1, '#5a6066']]);
    x.beginPath(); for (let i = 0; i < 24; i++) { const a = i / 24 * Math.PI * 2, r = i % 2 ? 34 : 44; x.lineTo(Math.cos(a) * r, Math.sin(a) * r); } x.fill();
    x.fillStyle = '#2a2e32'; x.beginPath(); x.arc(0, 0, 12, 0, 7); x.fill();
    x.restore();
  },
  toolbox(x) { D.box(x, ['#b02a20', '#701a14', 'ИНСТРУМЕНТ', '', 80, 46]); x.strokeStyle = '#333'; x.lineWidth = 6; x.beginPath(); x.moveTo(44, 54); x.quadraticCurveTo(64, 34, 84, 54); x.stroke(); },
  battery(x) { D.box(x, ['#2a2a2a', '#151515', '6СТ-60', 'АККУМУЛЯТОР', 76, 54]); x.fillStyle = '#c03020'; x.fillRect(36, 40, 10, 8); x.fillStyle = '#3050c0'; x.fillRect(76, 40, 10, 8); },
  plate(x) {
    shadow(x, 64, 46);
    x.fillStyle = lg(x, 0, 0, 128, 128, [[0, '#b8bcc0'], [0.5, '#80868c'], [1, '#5a6066']]);
    x.beginPath(); x.moveTo(18, 50); x.lineTo(104, 38); x.lineTo(112, 96); x.lineTo(24, 108); x.closePath(); x.fill();
    for (let i = 0; i < 30; i++) { x.fillStyle = `rgba(${120 + Math.random() * 60},60,20,0.35)`; x.beginPath(); x.arc(24 + Math.random() * 80, 46 + Math.random() * 56, 2 + Math.random() * 6, 0, 7); x.fill(); }
  },
  coil(x, [col]) {
    shadow(x, 64, 40);
    for (let i = 0; i < 7; i++) { x.strokeStyle = shade(col, 0.7 + i * 0.08); x.lineWidth = 6; x.beginPath(); x.ellipse(64, 70, 40 - i * 3, 26 - i * 2, 0, 0, 7); x.stroke(); }
  },
  gun(x, [kind]) {
    const metal = (a, b, w, h) => { x.fillStyle = lg(x, 0, b, 0, b + h, [[0, '#6a6e72'], [0.5, '#2c2f32'], [1, '#141618']]); x.fillRect(a, b, w, h); };
    const wood = (pts) => { x.fillStyle = lg(x, 0, 50, 0, 100, [[0, '#a8683a'], [1, '#5a3218']]); x.beginPath(); pts.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath(); x.fill(); };
    shadow(x, 64, 50);
    if (kind === 'pm') { metal(30, 46, 66, 16); x.fillStyle = '#2a2420'; x.beginPath(); x.moveTo(40, 62); x.lineTo(56, 62); x.lineTo(52, 100); x.lineTo(34, 100); x.fill(); metal(56, 62, 10, 10); }
    else if (kind === 'toz') { metal(40, 50, 80, 7); metal(40, 58, 80, 7); wood([[8, 62], [44, 54], [48, 70], [30, 74], [12, 86]]); }
    else if (kind === 'bizon') { metal(24, 52, 80, 12); metal(104, 55, 16, 4); x.fillStyle = '#1a1a1a'; x.fillRect(40, 64, 56, 12); x.fillRect(36, 64, 10, 28); metal(6, 54, 20, 6); }
    else if (kind === 'ak') {
      wood([[6, 58], [32, 54], [32, 68], [10, 80]]); metal(30, 52, 50, 14); wood([[80, 54], [100, 54], [100, 64], [80, 64]]); metal(100, 56, 24, 4);
      x.fillStyle = '#2a2420'; x.beginPath(); x.moveTo(58, 66); x.lineTo(70, 66); x.quadraticCurveTo(74, 86, 82, 98); x.lineTo(70, 102); x.quadraticCurveTo(62, 86, 58, 66); x.fill();
      x.fillStyle = '#2a2420'; x.fillRect(40, 66, 8, 18);
    } else if (kind === 'svd') {
      wood([[4, 58], [30, 52], [40, 52], [40, 70], [28, 70], [20, 64], [8, 82]]); metal(38, 54, 50, 10); wood([[86, 52], [104, 52], [104, 62], [86, 62]]); metal(102, 56, 24, 3);
      metal(48, 40, 34, 8); x.fillStyle = '#88b0d0'; x.fillRect(80, 41, 4, 6); x.fillStyle = '#1a1a1a'; x.fillRect(60, 64, 8, 22);
    }
  },
  samovar(x) {
    shadow(x, 64, 36);
    const br = [[0, '#6a4210'], [0.3, '#f0c060'], [0.5, '#fff0b0'], [0.75, '#c08a2a'], [1, '#5a3a10']];
    x.fillStyle = lg(x, 30, 0, 98, 0, br); x.beginPath(); x.ellipse(64, 66, 34, 30, 0, 0, 7); x.fill();
    x.fillRect(48, 92, 32, 12); x.fillRect(40, 104, 48, 8); x.fillRect(54, 22, 20, 18);
    x.strokeStyle = '#3a2408'; x.lineWidth = 5; x.beginPath(); x.moveTo(30, 60); x.lineTo(20, 52); x.moveTo(98, 60); x.lineTo(108, 52); x.stroke();
    x.fillStyle = '#5a3a10'; x.fillRect(90, 74, 18, 5);
  },
  garmon(x) {
    shadow(x, 64, 48);
    x.fillStyle = '#7a1a14'; x.fillRect(14, 36, 26, 72); x.fillRect(88, 36, 26, 72);
    for (let i = 0; i < 8; i++) { x.fillStyle = i % 2 ? '#2a2a2a' : '#e0d0a0'; x.fillRect(40 + i * 6, 40, 6, 64); }
    for (let r = 0; r < 4; r++) { x.fillStyle = '#f0e8d0'; x.beginPath(); x.arc(27, 48 + r * 16, 4, 0, 7); x.fill(); x.beginPath(); x.arc(101, 48 + r * 16, 4, 0, 7); x.fill(); }
  },
  ikona(x) {
    shadow(x, 64, 40);
    x.fillStyle = lg(x, 0, 0, 128, 128, [[0, '#ffe080'], [0.5, '#b8862a'], [1, '#6a4a10']]); x.fillRect(24, 18, 80, 96);
    x.fillStyle = '#3a2010'; x.fillRect(32, 26, 64, 80);
    x.fillStyle = rg(x, 64, 50, 18, [[0, '#ffe8a0'], [1, '#b8862a']]); x.beginPath(); x.arc(64, 50, 16, 0, 7); x.fill();
    x.fillStyle = '#d8b088'; x.beginPath(); x.ellipse(64, 54, 8, 10, 0, 0, 7); x.fill();
    x.fillStyle = '#7a1a14'; x.beginPath(); x.moveTo(44, 106); x.quadraticCurveTo(64, 60, 84, 106); x.fill();
  },
  watch(x) {
    shadow(x, 64, 30);
    x.fillStyle = '#4a2a18'; x.fillRect(52, 10, 24, 108);
    x.fillStyle = rg(x, 64, 64, 32, [[0, '#ffffff'], [0.85, '#c0c4c8'], [1, '#6a7076']]); x.beginPath(); x.arc(64, 64, 30, 0, 7); x.fill();
    x.fillStyle = '#f4ecd8'; x.beginPath(); x.arc(64, 64, 24, 0, 7); x.fill();
    x.strokeStyle = '#1a1a1a'; x.lineWidth = 3; x.beginPath(); x.moveTo(64, 64); x.lineTo(64, 46); x.moveTo(64, 64); x.lineTo(76, 70); x.stroke();
    text(x, 'ПОБЕДА', 64, 78, 7, '#7a1a14', 30);
  },
  medal(x) {
    shadow(x, 64, 24);
    x.fillStyle = '#b8a8a0'; x.beginPath(); x.moveTo(44, 14); x.lineTo(84, 14); x.lineTo(80, 50); x.lineTo(48, 50); x.fill();
    x.fillStyle = '#1d4f8c'; x.fillRect(58, 14, 4, 36); x.fillRect(66, 14, 4, 36);
    x.fillStyle = rg(x, 64, 80, 28, [[0, '#ffffff'], [0.7, '#b0b4b8'], [1, '#5a6066']]); x.beginPath(); x.arc(64, 80, 28, 0, 7); x.fill();
    x.fillStyle = '#c02020'; x.beginPath(); for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 8 : 18; x.lineTo(64 + Math.cos(a) * r, 80 + Math.sin(a) * r); } x.fill();
  },
  radio(x) {
    D.box(x, ['#5a3a24', '#3a2414', '', '', 84, 56]);
    x.fillStyle = '#c8c0a8'; x.fillRect(28, 62, 40, 36); for (let i = 0; i < 7; i++) { x.fillStyle = '#5a4a3a'; x.fillRect(30, 64 + i * 5, 36, 2); }
    x.fillStyle = '#e8dcb0'; x.fillRect(72, 64, 22, 12); x.fillStyle = '#d02020'; x.fillRect(80, 64, 2, 12);
    x.fillStyle = '#2a2a2a'; x.beginPath(); x.arc(82, 90, 6, 0, 7); x.fill(); text(x, 'ОКЕАН', 48, 104, 8, '#f0e0b0', 36);
  },
  kassetnik(x) { D.box(x, ['#3a3a3a', '#1a1a1a', '', '', 88, 46]); x.fillStyle = '#c8c8c8'; x.fillRect(30, 76, 40, 22); x.fillStyle = '#2a2a2a'; x.beginPath(); x.arc(42, 87, 6, 0, 7); x.arc(58, 87, 6, 0, 7); x.fill(); x.fillStyle = '#888'; x.beginPath(); x.arc(86, 86, 10, 0, 7); x.fill(); },
  plastinka(x) {
    shadow(x, 64, 44);
    x.fillStyle = rg(x, 64, 62, 48, [[0, '#3a3a3a'], [1, '#0a0a0a']]); x.beginPath(); x.arc(64, 62, 48, 0, 7); x.fill();
    x.strokeStyle = 'rgba(255,255,255,0.07)'; for (let r = 18; r < 46; r += 3) { x.beginPath(); x.arc(64, 62, r, 0, 7); x.stroke(); }
    x.fillStyle = '#c02020'; x.beginPath(); x.arc(64, 62, 15, 0, 7); x.fill(); text(x, 'МЕЛОДИЯ', 64, 62, 6, '#fff', 26);
  },
  zenit(x) {
    shadow(x, 64, 44);
    x.fillStyle = lg(x, 0, 40, 0, 96, [[0, '#4a4a4a'], [1, '#121212']]); rrect(x, 18, 44, 92, 50, 6); x.fill();
    x.fillStyle = '#c0c4c8'; x.fillRect(18, 44, 92, 8); x.fillStyle = '#2a2a2a'; x.fillRect(50, 30, 28, 16);
    x.fillStyle = rg(x, 64, 74, 22, [[0, '#6a8aa8'], [0.4, '#1a2a3a'], [1, '#000']]); x.beginPath(); x.arc(64, 74, 20, 0, 7); x.fill();
    text(x, 'ЗЕНИТ', 64, 37, 8, '#e0e0e0', 26);
  },
  matreshka(x) {
    shadow(x, 64, 26);
    x.fillStyle = lg(x, 38, 0, 90, 0, cyl('#c82020')); x.beginPath(); x.ellipse(64, 84, 28, 30, 0, 0, 7); x.ellipse(64, 44, 20, 22, 0, 0, 7); x.fill();
    x.fillStyle = '#f2d8b8'; x.beginPath(); x.ellipse(64, 46, 12, 13, 0, 0, 7); x.fill();
    x.fillStyle = '#f0c020'; x.beginPath(); x.arc(64, 88, 12, 0, 7); x.fill();
    x.fillStyle = '#c02020'; x.beginPath(); x.arc(59, 50, 2, 0, 7); x.arc(69, 50, 2, 0, 7); x.fill();
  },
  hohloma(x) {
    shadow(x, 64, 46);
    x.fillStyle = lg(x, 0, 50, 0, 110, [[0, '#2a1a10'], [1, '#0a0605']]); x.beginPath(); x.moveTo(18, 56); x.quadraticCurveTo(64, 140, 110, 56); x.fill();
    x.fillStyle = rg(x, 64, 56, 46, [[0, '#ffd060'], [1, '#c08020']]); x.beginPath(); x.ellipse(64, 56, 46, 12, 0, 0, 7); x.fill();
    x.fillStyle = '#c02020'; for (let i = 0; i < 5; i++) { x.beginPath(); x.arc(36 + i * 14, 80 - Math.abs(i - 2) * 4, 5, 0, 7); x.fill(); }
  },
  coins(x) { shadow(x, 64, 40); for (let i = 0; i < 6; i++) { x.fillStyle = rg(x, 48 + (i % 3) * 16, 80 - Math.floor(i / 3) * 18, 18, [[0, '#fff2c0'], [1, '#a07020']]); x.beginPath(); x.ellipse(48 + (i % 3) * 16, 84 - Math.floor(i / 3) * 18 - i * 2, 16, 8, 0, 0, 7); x.fill(); } text(x, '15 коп.', 64, 108, 10, '#e8d090', 50); },
  chain(x) { shadow(x, 64, 36); x.strokeStyle = '#e8c050'; x.lineWidth = 4; for (let i = 0; i < 16; i++) { const a = i / 16 * Math.PI * 2; x.beginPath(); x.ellipse(64 + Math.cos(a) * 34, 64 + Math.sin(a) * 30, 5, 3, a, 0, 7); x.stroke(); } x.fillStyle = '#ffd860'; x.beginPath(); x.arc(64, 98, 7, 0, 7); x.fill(); },
  globus(x) { shadow(x, 64, 30); x.fillStyle = '#5a3a24'; x.fillRect(50, 100, 28, 10); x.fillStyle = rg(x, 64, 58, 38, [[0, '#9ad0f0'], [1, '#1d5a8c']]); x.beginPath(); x.arc(64, 58, 36, 0, 7); x.fill(); x.fillStyle = '#c84020'; x.beginPath(); x.ellipse(70, 46, 22, 12, 0.2, 0, 7); x.fill(); text(x, 'СССР', 70, 46, 9, '#fff', 30); },
  chess(x) { shadow(x, 64, 46); for (let r = 0; r < 6; r++) for (let c = 0; c < 6; c++) { x.fillStyle = (r + c) % 2 ? '#3a2414' : '#e8d0a0'; x.fillRect(22 + c * 14, 30 + r * 13, 14, 13); } x.fillStyle = '#f8f8f0'; x.beginPath(); x.arc(50, 40, 6, 0, 7); x.fill(); x.fillStyle = '#1a1a1a'; x.beginPath(); x.arc(78, 80, 6, 0, 7); x.fill(); },
  balalayka(x) { shadow(x, 64, 36); x.fillStyle = lg(x, 30, 0, 98, 0, cyl('#c88a40')); x.beginPath(); x.moveTo(64, 50); x.lineTo(100, 112); x.lineTo(28, 112); x.closePath(); x.fill(); x.fillStyle = '#4a2a14'; x.fillRect(60, 6, 8, 50); x.fillStyle = '#1a1a1a'; x.beginPath(); x.arc(64, 92, 7, 0, 7); x.fill(); },
  valenki(x) { shadow(x, 64, 44); x.fillStyle = lg(x, 0, 20, 0, 112, [[0, '#9a9890'], [1, '#5a5850']]); x.beginPath(); x.moveTo(30, 18); x.lineTo(60, 18); x.lineTo(60, 96); x.lineTo(104, 96); x.quadraticCurveTo(110, 112, 96, 112); x.lineTo(30, 112); x.closePath(); x.fill(); },
  ushanka(x) { shadow(x, 64, 44); x.fillStyle = rg(x, 64, 56, 44, [[0, '#7a6050'], [1, '#2a1a10']]); x.beginPath(); x.ellipse(64, 56, 40, 30, 0, Math.PI, 0); x.fill(); x.fillStyle = '#5a4030'; x.fillRect(20, 56, 88, 16); x.fillRect(20, 60, 18, 44); x.fillRect(90, 60, 18, 44); x.fillStyle = '#c02020'; x.beginPath(); x.arc(64, 64, 5, 0, 7); x.fill(); },
  gasmask(x) { shadow(x, 64, 36); x.fillStyle = rg(x, 64, 60, 44, [[0, '#7a8a6a'], [1, '#2a3a24']]); x.beginPath(); x.ellipse(64, 60, 38, 46, 0, 0, 7); x.fill(); x.fillStyle = rg(x, 46, 50, 12, [[0, '#a8c8d8'], [1, '#2a3a44']]); x.beginPath(); x.arc(46, 50, 12, 0, 7); x.arc(82, 50, 12, 0, 7); x.fill(); x.fillStyle = '#3a3a3a'; x.beginPath(); x.arc(64, 92, 14, 0, 7); x.fill(); },
  binokl(x) { shadow(x, 64, 46); for (const cx of [42, 86]) { x.fillStyle = lg(x, cx - 16, 0, cx + 16, 0, cyl('#3a3a3a')); x.fillRect(cx - 16, 40, 32, 60); x.fillStyle = rg(x, cx, 100, 14, [[0, '#6a8aa8'], [1, '#000']]); x.beginPath(); x.ellipse(cx, 100, 15, 6, 0, 0, 7); x.fill(); } x.fillStyle = '#2a2a2a'; x.fillRect(58, 54, 12, 20); },
  saw(x) { shadow(x, 64, 50); x.fillStyle = '#e07020'; rrect(x, 14, 48, 52, 44, 8); x.fill(); x.fillStyle = lg(x, 0, 60, 0, 80, [[0, '#e0e4e8'], [1, '#6a7076']]); x.fillRect(66, 62, 52, 16); x.fillStyle = '#2a2a2a'; x.fillRect(22, 36, 30, 12); },
  generator(x) { D.box(x, ['#c04020', '#802a14', 'ГЕНЕРАТОР', '220 В', 84, 58]); },
  book(x, [col, t1]) { D.box(x, [col, '#f0e8d0', t1, '', 62, 80]); },
  packet(x, [col, t1]) { shadow(x, 64, 30); x.fillStyle = lg(x, 36, 0, 92, 0, cyl(col)); x.beginPath(); x.moveTo(36, 20); x.lineTo(92, 20); x.lineTo(96, 112); x.lineTo(32, 112); x.fill(); x.fillStyle = '#f8f0d8'; x.fillRect(40, 54, 48, 34); text(x, t1, 64, 71, 11, '#2a5a1a', 44); },
  torch(x) { shadow(x, 64, 46); x.save(); x.translate(64, 70); x.rotate(-0.4); x.fillStyle = lg(x, 0, -12, 0, 12, cyl('#3a3a3a')); x.fillRect(-46, -10, 70, 20); x.fillStyle = '#5a5a5a'; x.fillRect(24, -16, 22, 32); x.fillStyle = rg(x, 46, 0, 14, [[0, '#ffffe0'], [1, '#c0b060']]); x.beginPath(); x.ellipse(46, 0, 5, 14, 0, 0, 7); x.fill(); x.restore(); },
  candles(x) { shadow(x, 64, 36); for (let i = 0; i < 3; i++) { x.fillStyle = lg(x, 38 + i * 20, 0, 50 + i * 20, 0, cyl('#f0e8c8')); x.fillRect(38 + i * 20, 46 - i * 6, 14, 66 + i * 6); x.fillStyle = '#ffb020'; x.beginPath(); x.ellipse(45 + i * 20, 36 - i * 6, 4, 8, 0, 0, 7); x.fill(); } },
  matches(x) { D.box(x, ['#f0d040', '#b09020', 'СПИЧКИ', 'Балабаново', 70, 40]); },
  salo(x) { shadow(x, 64, 44); x.fillStyle = lg(x, 0, 50, 0, 100, [[0, '#f8f0e8'], [1, '#d8c8b8']]); rrect(x, 20, 50, 88, 46, 8); x.fill(); x.fillStyle = '#c88068'; x.fillRect(20, 66, 88, 8); x.fillStyle = '#7a4a2a'; x.fillRect(20, 50, 88, 6); },
  cup(x, [col, t1]) { shadow(x, 64, 34); x.fillStyle = lg(x, 30, 0, 98, 0, cyl(col)); x.beginPath(); x.moveTo(28, 36); x.lineTo(100, 36); x.lineTo(90, 112); x.lineTo(38, 112); x.fill(); x.fillStyle = '#e8e0d0'; x.beginPath(); x.ellipse(64, 36, 36, 8, 0, 0, 7); x.fill(); text(x, t1, 64, 76, 13, '#fff', 54); },
  cig(x) { D.box(x, ['#e8e0c8', '#a89880', 'ПАПИРОСЫ', 'БЕЛОМОРКАНАЛ', 72, 56]); x.fillStyle = '#1d4f8c'; x.fillRect(26, 74, 72, 6); },
  envelope(x, [t1]) { shadow(x, 64, 46); x.fillStyle = lg(x, 0, 30, 0, 100, [[0, '#f4ecd8'], [1, '#c8bca0']]); x.fillRect(16, 34, 96, 66); x.strokeStyle = '#a89878'; x.lineWidth = 2; x.beginPath(); x.moveTo(16, 34); x.lineTo(64, 70); x.lineTo(112, 34); x.stroke(); x.fillStyle = '#c02020'; x.fillRect(92, 40, 14, 16); if (t1) text(x, t1, 54, 88, 9, '#3a2a1a', 60, 'italic'); },
  photo(x) { shadow(x, 64, 42); x.fillStyle = '#f0ece0'; x.fillRect(24, 22, 80, 92); x.fillStyle = lg(x, 0, 30, 0, 96, [[0, '#a89880'], [1, '#4a3a2a']]); x.fillRect(30, 28, 68, 66); x.fillStyle = '#d8c8a8'; for (const cx of [48, 64, 80]) { x.beginPath(); x.arc(cx, 56, 7, 0, 7); x.fill(); x.fillRect(cx - 8, 64, 16, 30); } },
  key(x) { shadow(x, 64, 36); x.strokeStyle = '#c8a040'; x.lineWidth = 8; x.beginPath(); x.arc(40, 60, 16, 0, 7); x.stroke(); x.fillStyle = '#c8a040'; x.fillRect(54, 56, 54, 8); x.fillRect(92, 64, 8, 14); x.fillRect(102, 64, 6, 10); x.fillStyle = '#f0e8c8'; x.fillRect(22, 86, 40, 18); },
  map(x) { shadow(x, 64, 46); x.fillStyle = '#e8dcb8'; x.beginPath(); x.moveTo(16, 30); x.lineTo(46, 22); x.lineTo(82, 30); x.lineTo(112, 22); x.lineTo(112, 102); x.lineTo(82, 110); x.lineTo(46, 102); x.lineTo(16, 110); x.fill(); x.strokeStyle = '#4a8a3a'; x.lineWidth = 3; x.beginPath(); x.moveTo(20, 90); x.bezierCurveTo(50, 40, 80, 100, 108, 40); x.stroke(); x.strokeStyle = '#c02020'; x.beginPath(); x.moveTo(70, 56); x.lineTo(82, 68); x.moveTo(82, 56); x.lineTo(70, 68); x.stroke(); },
  badge(x) { shadow(x, 64, 26); x.fillStyle = rg(x, 64, 64, 30, [[0, '#ffe080'], [1, '#a07020']]); x.beginPath(); x.arc(64, 64, 28, 0, 7); x.fill(); x.fillStyle = '#c02020'; x.beginPath(); x.arc(64, 64, 20, 0, 7); x.fill(); text(x, 'ГТО', 64, 64, 12, '#ffe080', 30); },
  ration(x) { D.box(x, ['#4a5a32', '#2a3a1a', 'ИРП', 'паёк суточный', 76, 54]); },
  money(x) { shadow(x, 64, 44); for (let i = 0; i < 3; i++) { x.fillStyle = ['#c8a070', '#a8c088', '#d8a8a0'][i]; x.fillRect(22 + i * 6, 40 + i * 10, 80, 40); x.strokeStyle = 'rgba(0,0,0,0.2)'; x.strokeRect(22 + i * 6, 40 + i * 10, 80, 40); } text(x, '100 ₽', 70, 80, 14, '#3a2a1a', 50); },
  ammo(x, [col]) { shadow(x, 64, 40); for (let i = 0; i < 5; i++) { const cx = 34 + i * 15; x.fillStyle = lg(x, cx - 6, 0, cx + 6, 0, cyl(col)); x.fillRect(cx - 6, 56, 12, 50); x.fillStyle = lg(x, cx - 5, 0, cx + 5, 0, cyl('#b87333')); x.beginPath(); x.moveTo(cx - 6, 56); x.lineTo(cx - 6, 44); x.quadraticCurveTo(cx, 28, cx + 6, 44); x.lineTo(cx + 6, 56); x.fill(); } },
};

// рецепт для каждого предмета
const R = {
  tushenka: ['can', ['#8a8f96', '#b8282a', 'ТУШЁНКА', 'говяжья', '#e8c040']], sgush: ['can', ['#8a8f96', '#2a6ac0', 'СГУЩЁНКА', 'молоко цельное', '#f4f4f4']],
  suhari: ['packet', ['#c8a060', 'СУХАРИ']], grechka: ['box', ['#c87830', null, 'ГРЕЧКА', '1 кг', 62, 74]], kilka: ['flat', ['#9aa0a6', '#c03020', 'КИЛЬКА']],
  lapsha: ['cup', ['#e8a020', 'ЛАПША']], kartoshka: ['sack', ['#a88a5a', 'КАРТОФЕЛЬ']], varenye: ['jar', ['#7a1a2a', '#c8c8c8', 'ВАРЕНЬЕ']],
  med_honey: ['jar', ['#e0a020', '#c8c8c8', 'МЁД']], salo: ['salo', []], voda: ['jug', ['#a8d0f0', 'ВОДА 5 л']], syhpay: ['ration', []],
  griby: ['jar', ['#6a5030', '#c8c8c8', 'ГРИБЫ']], kvas: ['bottle', ['#4a2a10', '#4a2a10', '#e8c070', 'КВАС', '#c02020', 0.9]],
  kompot: ['jar', ['#b04060', '#d0d0d0', 'КОМПОТ']], sok: ['box', ['#e07020', null, 'СОК', 'яблочный', 50, 72]],
  limonad: ['bottle', ['#7ab060', '#e8f0a0', '#f0e060', 'БУРАТИНО', '#d02020', 0.9]], mineralka: ['bottle', ['#4a8a5a', '#d0f0e0', '#f4f4f4', 'НАРЗАН', '#3a6a9a', 0.95]],
  bint: ['roll', []], zelenka: ['bottle', ['#2a6a3a', '#1a8a3a', '#f4f4f4', 'ЗЕЛЁНКА', '#d8d8d8', 0.55]], aptechka: ['medkit', ['#f4f4f0', 'АПТЕЧКА']],
  antibio: ['pills', ['#e0c020', 1]], obezbol: ['pills', ['#d06060', 1]], spirt: ['bottle', ['#d8e8f0', '#f0f8ff', '#f4f4f4', 'СПИРТ', '#888', 0.8]], x7: ['syringe', []],
  kanistra: ['jerry', ['#b02a20']], bochka: ['barrel', ['#2a5a9a']], zapchasti: ['gear', []], instrument: ['toolbox', []], akkum: ['battery', []],
  maslo: ['can', ['#2a2a2a', '#d0a020', 'М-10', 'масло моторное', '#2a2a2a']], list: ['plate', []], kabel: ['coil', ['#c87840']],
  pm: ['gun', ['pm']], toz: ['gun', ['toz']], bizon: ['gun', ['bizon']], ak: ['gun', ['ak']], svd: ['gun', ['svd']],
  vodka: ['bottle', ['#e0ecf0', '#f4f8ff', '#f4ecd0', 'ВОДКА', '#c8a030', 1]], sigarety: ['cig', []], spichki: ['matches', []], svechi: ['candles', []],
  sol: ['packet', ['#d8d8d8', 'СОЛЬ']], sahar: ['packet', ['#f0f0f0', 'САХАР']], batareyki: ['battery', []], semena: ['packet', ['#7ab040', 'СЕМЕНА']],
  fonar: ['torch', []], valenki: ['valenki', []], ushanka: ['ushanka', []], protivogaz: ['gasmask', []], binokl: ['binokl', []], benzopila: ['saw', []],
  generator: ['generator', []], kniga: ['book', ['#7a1a14', 'ВОЙНА И МИР']], samovar: ['samovar', []], garmon: ['garmon', []], ikona: ['ikona', []],
  chasy: ['watch', []], medal: ['medal', []], radio: ['radio', []], kassetnik: ['kassetnik', []], plastinka: ['plastinka', []], zenit: ['zenit', []],
  matreshka: ['matreshka', []], hohloma: ['hohloma', []], monety: ['coins', []], zoloto: ['chain', []], globus: ['globus', []], shahmaty: ['chess', []],
  balalayka: ['balalayka', []],
  _money: ['money', []], _ammo: ['ammo', ['#c8a040']], _fuel: ['barrel', ['#2a2a2a']],
};
function uniqueRecipe(n) {
  if (/^Письмо/.test(n)) return ['envelope', ['родным']];
  if (/^Открытка/.test(n)) return ['envelope', ['привет!']];
  if (/^Фотография/.test(n)) return ['photo', []];
  if (/^Дневник|^Трудовая/.test(n)) return ['book', ['#3a4a2a', /^Дневник/.test(n) ? 'ДНЕВНИК' : 'ТРУДОВАЯ']];
  if (/^Значок/.test(n)) return ['badge', []];
  if (/^Ключ/.test(n)) return ['key', []];
  if (/^Карта/.test(n)) return ['map', []];
  return ['coins', []];
}
export function iconURL(id, uniqueName) {
  const k = uniqueName ? 'u:' + uniqueRecipe(uniqueName)[0] + uniqueName.slice(0, 6) : id;
  if (cache[k]) return cache[k];
  const rec = uniqueName ? uniqueRecipe(uniqueName) : R[id] || ['box', ['#6a6a6a', null, '?', '']];
  const c = cv(), x = c.getContext('2d');
  try { D[rec[0]](x, rec[1]); } catch (e) { x.fillStyle = '#555'; x.fillRect(30, 30, 68, 68); }
  return (cache[k] = c.toDataURL('image/png'));
}
export function iconImg(id, uniqueName, cls = 'ii') { return `<img class="${cls}" src="${iconURL(id, uniqueName)}" alt="">`; }
