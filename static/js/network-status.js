(() => {
  const banner = document.createElement("div");
  banner.className = "network-status-alert";
  banner.setAttribute("role", "alert");
  banner.textContent = "No internet connection. Changes may not be saved until you reconnect.";
  const update = () => {
    banner.hidden = navigator.onLine;
    if (!banner.isConnected) document.body.append(banner);
  };
  window.addEventListener("online", update);
  window.addEventListener("offline", update);
  document.addEventListener("DOMContentLoaded", update);
})();
