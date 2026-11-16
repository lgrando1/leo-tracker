// Service Worker mínimo para habilitar instalação nativa do PWA no Chrome Android
// Repassa todas as requisições diretamente para a rede sem cachear dados dinâmicos do banco Neon.

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
