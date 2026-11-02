/* Octop custom build: the desktop shell must always load the current bundle, so the
   PWA precache worker is replaced by a stub that clears caches and unregisters. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    } catch (error) {}
    await self.clients.claim();
    try {
      await self.registration.unregister();
    } catch (error) {}
  })());
});
