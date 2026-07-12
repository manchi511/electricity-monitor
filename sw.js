// Service Worker - 电费监控 PWA
const CACHE_NAME = 'electricity-dashboard-v1';
const CACHE_URLS = [
  './',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

// 安装：预缓存核心资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CACHE_URLS)).catch(() => {})
  );
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// 请求拦截：网络优先，失败回退缓存
self.addEventListener('fetch', (event) => {
  // 只处理 GET 请求
  if (event.request.method !== 'GET') return;

  // API 请求不走缓存
  if (event.request.url.includes('/api/')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 成功则更新缓存
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // 网络失败，回退缓存
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          // 如果是导航请求且没有缓存，返回缓存的首页
          if (event.request.mode === 'navigate') {
            return caches.match('/');
          }
          return new Response('离线且无缓存', { status: 503 });
        });
      })
  );
});
