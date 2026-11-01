/* HVGC LINEUP service worker — Web Push delivery.
   Shows a notification for each pushed message and focuses/opens the linked
   page when the notification is clicked. */

self.addEventListener("push", function (event) {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = data.title || "HVGC LINEUP";
  const options = {
    body: data.body || "",
    icon: "/static/logo.png",
    badge: "/static/logo.png",
    data: { url: data.url || "/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (const client of list) {
        if ("focus" in client) {
          if ("navigate" in client) { try { client.navigate(target); } catch (e) {} }
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
