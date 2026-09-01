(() => {
  const button = document.querySelector("[data-request-notifications]");
  const sound = document.querySelector("[data-notification-sound]");
  const status = document.querySelector("[data-notification-status]");
  if (!button) return;
  sound.checked = localStorage.getItem("vtic-notification-sound") !== "off";
  sound.addEventListener("change", () => localStorage.setItem("vtic-notification-sound", sound.checked ? "on" : "off"));
  const update = () => status.textContent = !("Notification" in window) ? "This browser does not support notifications." : `Permission: ${Notification.permission}`;
  button.addEventListener("click", async () => { if ("Notification" in window) await Notification.requestPermission(); update(); });
  update();
})();
