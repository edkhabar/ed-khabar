// ED Khabar service worker: app ko install-able banata hai aur offline bhi pichhli khabrein dikhata hai.
const CACHE = 'edk-v8';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network first (taaki hamesha taaza news aaye), network na ho to cache se
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  const isNews = new URL(req.url).pathname.endsWith('news.json');
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(isNews ? 'news.json' : req, copy));
      }
      return res;
    }).catch(() => caches.match(isNews ? 'news.json' : req).then(r => r || caches.match('index.html')))
  );
});
