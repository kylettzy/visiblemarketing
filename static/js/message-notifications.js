(() => {
  const widget = document.querySelector("[data-message-notifications]");
  if (!widget) return;
  const badge = widget.querySelector("[data-message-notification-count]");
  const target = widget.dataset.target;
  const storageKey = `vtic-last-message-notification:${target}`;
  let serviceWorkerRegistration = null;
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/static/js/vtic-notification-sw.js")
      .then((registration) => { serviceWorkerRegistration = registration; })
      .catch(() => {});
  }

  async function markRead() {
    try {
      await fetch("/api/message-notifications/read", {
        method: "POST",
        headers: { "X-CSRF-Token": widget.dataset.csrfToken },
      });
    } catch {
      // The badge will remain until the next successful refresh.
    }
  }

  async function refresh() {
    try {
      const response = await fetch("/api/message-notifications", { cache: "no-store" });
      if (!response.ok) return;
      const result = await response.json();
      const count = Number(result.unread_count || 0);
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.hidden = count === 0;
      widget.classList.toggle("has-unread", count > 0);
      if (count && result.latest && "Notification" in window && Notification.permission === "granted") {
        const lastNotified = Number(localStorage.getItem(storageKey) || 0);
        if (Number(result.latest.id) > lastNotified) {
          const title = `New message from ${result.latest.sender_name}`;
          const options = {
            body: `Request #${String(result.latest.request_id).padStart(5, "0")}: ${result.latest.message}`,
            tag: `vtic-message-${result.latest.id}`,
            data: { url: result.target_url },
          };
          if (serviceWorkerRegistration) serviceWorkerRegistration.showNotification(title, options);
          else {
            const notification = new Notification(title, options);
            notification.onclick = () => { window.focus(); location.href = result.target_url; };
          }
          localStorage.setItem(storageKey, String(result.latest.id));
        }
      }
    } catch {
      // Poll again later when the connection returns.
    }
  }

  if (location.pathname === target) markRead().then(refresh);
  else refresh();
  window.setInterval(refresh, 5000);
})();
