(() => {
  const refreshablePaths = [
    "/admin/messages",
    "/admin/review-requests",
    "/admin/calendar",
    "/admin/catered-customers",
    "/account/reviews",
  ];
  const shouldRefreshPage = refreshablePaths.some((path) =>
    location.pathname.startsWith(path),
  );
  let baseline = null;
  let checking = false;
  let formIsDirty = false;
  let updateWaiting = false;

  const stateKey = (state) =>
    JSON.stringify({
      reviews: state.reviews,
      messages: state.messages,
      calendar: state.calendar,
    });

  const hasActiveEditing = () => {
    const active = document.activeElement;
    const editing =
      active?.matches?.("input:not([type='checkbox']):not([type='radio']), textarea, select") ??
      false;
    return editing || formIsDirty || Boolean(document.querySelector("dialog[open]"));
  };

  const showRefreshBanner = () => {
    if (document.querySelector("[data-live-update-banner]")) return;
    const banner = document.createElement("aside");
    banner.className = "live-update-banner";
    banner.dataset.liveUpdateBanner = "";
    banner.innerHTML =
      '<span><b>New activity received</b><small>Messages or project information changed.</small></span><button type="button">Refresh now</button>';
    banner.querySelector("button").addEventListener("click", () => location.reload());
    document.body.appendChild(banner);
  };

  const applyUpdate = () => {
    if (!shouldRefreshPage) return;
    if (document.visibilityState !== "visible" || hasActiveEditing()) {
      updateWaiting = true;
      showRefreshBanner();
      return;
    }
    location.reload();
  };

  const check = async () => {
    if (checking) return;
    checking = true;
    try {
      const response = await fetch("/api/live-state", { cache: "no-store" });
      if (!response.ok) return;
      const state = await response.json();
      const next = stateKey(state);
      if (baseline === null) baseline = next;
      else if (next !== baseline) {
        baseline = next;
        window.dispatchEvent(new CustomEvent("vtic:live-update", { detail: state }));
        applyUpdate();
      }
    } catch {
      // A later poll will recover after a temporary connection problem.
    } finally {
      checking = false;
    }
  };

  document.addEventListener("input", (event) => {
    if (event.target.closest("form")) formIsDirty = true;
  });
  document.addEventListener("submit", () => {
    formIsDirty = false;
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (updateWaiting && !hasActiveEditing()) location.reload();
      else check();
    }
  });

  check();
  window.setInterval(check, 5000);
})();
