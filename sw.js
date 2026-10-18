// Офлайн-кэш: игра работает без интернета после первого запуска.
const V = 'peregon-v2';
const CORE = ['./', './index.html', './manifest.webmanifest', './vendor/three.module.min.js',
  './js/main.js', './js/util.js', './js/world.js', './js/models.js', './js/train.js', './js/zombies.js', './js/audio.js', './js/data.js', './js/chars.js', './js/player.js', './vendor/addons/GLTFLoader.js', './vendor/addons/SkeletonUtils.js', './vendor/addons/BufferGeometryUtils.js', './assets/models/soldier.glb', './assets/models/woman.glb',
  './assets/icon-180.png', './assets/icon-192.png', './assets/icon-512.png'].concat(
  ['red_brick_03', 'white_bricks', 'concrete_panels', 'yellow_plaster', 'wood_trunk_wall', 'wood_plank_wall', 'corrugated', 'rusty_metal_02',
    'sparse_grass', 'withered_grass', 'gravel_floor_02', 'worn_asphalt', 'rough_wood', 'shutter', 'green_metal_rust', 'snow_02', 'grey_plaster']
    .map((n) => `./assets/tex/${n}.jpg`));
self.addEventListener('install', (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(CORE)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
    const copy = res.clone(); caches.open(V).then((c) => c.put(e.request, copy)).catch(() => {});
    return res;
  }).catch(() => hit)));
});
