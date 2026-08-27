self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const existing = windows.find((windowClient) => new URL(windowClient.url).pathname === target);
      if (existing) return existing.focus();
      return clients.openWindow(target);
    }),
  );
});
