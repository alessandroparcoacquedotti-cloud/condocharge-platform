/// <reference lib="WebWorker" />

import { clientsClaim } from "workbox-core";
import { precacheAndRoute, cleanupOutdatedCaches, createHandlerBoundToURL } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { NetworkOnly } from "workbox-strategies";

declare let self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{
    url: string;
    revision: string | null;
  }>;
};

self.skipWaiting();
clientsClaim();
cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

const navigationHandler = createHandlerBoundToURL("/index.html");
registerRoute(new NavigationRoute(navigationHandler, { denylist: [/^\/api(?:\/|$)/] }));
registerRoute(({ url }) => url.pathname.startsWith("/api"), new NetworkOnly());

self.addEventListener("push", (event) => {
  const payload = event.data?.json() as
    | {
        title?: string;
        body?: string;
        url?: string;
        tag?: string;
      }
    | undefined;
  const title = payload?.title || "CondoCharge";
  const body = payload?.body || "Hai un nuovo aggiornamento.";
  const url = payload?.url || "/";
  const tag = payload?.tag || "condocharge-push";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag,
      data: { url },
      icon: "/pwa-192x192.png",
      badge: "/pwa-192x192.png",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const relativeUrl = String(event.notification.data?.url || "/");
  const targetUrl = new URL(relativeUrl, self.location.origin).toString();

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    }),
  );
});
