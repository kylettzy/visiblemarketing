(() => {
  const installButtons = [...document.querySelectorAll("[data-install-app]")];
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  let installPrompt = null;

  const reportInstallation = (source) => {
    const storageKey = "vtic-app-install-id";
    let deviceId = localStorage.getItem(storageKey);
    if (!deviceId) {
      deviceId = crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      localStorage.setItem(storageKey, deviceId);
    }
    fetch("/api/app-installations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, source }),
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
  };

  const showInstallButtons = () => {
    if (isStandalone) return;
    installButtons.forEach((button) => {
      button.hidden = false;
    });
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    showInstallButtons();
  });

  if (isIos) showInstallButtons();

  installButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (installPrompt) {
        installPrompt.prompt();
        await installPrompt.userChoice;
        installPrompt = null;
        return;
      }

      if (isIos) {
        window.alert(
          "To install VTIC: tap the Share button in Safari, then choose Add to Home Screen.",
        );
      }
    });
  });

  window.addEventListener("appinstalled", () => {
    reportInstallation("appinstalled");
    installPrompt = null;
    installButtons.forEach((button) => {
      button.hidden = true;
    });
  });

  if (isStandalone) reportInstallation("standalone_launch");

  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/" })
      .catch(() => {
        // The storefront remains fully usable when installation is unavailable.
      });
  });
})();
