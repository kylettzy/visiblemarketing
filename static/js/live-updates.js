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

  const stateKey = (state) => {
    if (location.pathname.startsWith("/admin/messages")) {
      return JSON.stringify({ messages: state.messages });
    }
    if (location.pathname.startsWith("/admin/calendar")) {
      return JSON.stringify({ calendar: state.calendar });
    }
    if (
      location.pathname.startsWith("/admin/review-requests") ||
      location.pathname.startsWith("/account/reviews")
    ) {
      return JSON.stringify({ reviews: state.reviews, messages: state.messages });
    }
    if (location.pathname.startsWith("/admin/catered-customers")) {
      return JSON.stringify({ reviews: state.reviews });
    }
    return "";
  };

  const showRefreshBanner = () => {
    if (document.querySelector("[data-live-update-banner]")) return;
    const banner = document.createElement("aside");
    banner.className = "live-update-banner";
    banner.dataset.liveUpdateBanner = "";
    banner.innerHTML =
      '<span><b>New activity received</b><small>Refresh when you are ready to view the latest information.</small></span><button type="button">Refresh now</button>';
    banner.querySelector("button").addEventListener("click", () => location.reload());
    document.body.appendChild(banner);
  };

  const applyUpdate = () => {
    if (!shouldRefreshPage) return;
    showRefreshBanner();
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

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      check();
    }
  });

  check();
  window.setInterval(check, 5000);
})();
