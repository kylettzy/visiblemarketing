document.addEventListener("DOMContentLoaded", () => {
  const search = document.querySelector("[data-conversation-search]");
  const cards = [...document.querySelectorAll("[data-conversation-card]")];
  const messages = document.querySelector("[data-thread-messages]");

  if (messages) messages.scrollTop = messages.scrollHeight;

  search?.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    cards.forEach((card) => {
      card.hidden = Boolean(query && !card.dataset.search.includes(query));
    });
  });

  document.querySelectorAll(".conversation-card-actions").forEach((menu) => {
    const positionMenu = () => {
      if (!menu.open) return;
      const trigger = menu.querySelector("summary");
      const panel = menu.querySelector(":scope > div");
      if (!trigger || !panel) return;
      const triggerRect = trigger.getBoundingClientRect();
      const panelWidth = 210;
      const panelHeight = panel.offsetHeight || 218;
      const spaceBelow = window.innerHeight - triggerRect.bottom;
      const top =
        spaceBelow >= panelHeight + 12
          ? triggerRect.bottom + 7
          : Math.max(10, triggerRect.top - panelHeight - 7);
      const left = Math.max(
        10,
        Math.min(
          triggerRect.right - panelWidth,
          window.innerWidth - panelWidth - 10,
        ),
      );
      panel.style.top = `${top}px`;
      panel.style.left = `${left}px`;
    };

    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      document.querySelectorAll(".conversation-card-actions[open]").forEach((other) => {
        if (other !== menu) other.open = false;
      });
      window.requestAnimationFrame(positionMenu);
    });

    window.addEventListener("resize", positionMenu);
    document.querySelector(".conversation-list nav")?.addEventListener("scroll", () => {
      if (menu.open) menu.open = false;
    });
  });

  const muteDialog = document.querySelector("[data-mute-dialog]");
  const muteForm = document.querySelector("[data-mute-form]");
  const muteCustomer = document.querySelector("[data-mute-customer]");
  document.querySelectorAll("[data-open-mute]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!muteDialog || !muteForm) return;
      muteForm.action = `/admin/messages/${button.dataset.requestId}/action`;
      if (muteCustomer) muteCustomer.textContent = button.dataset.customerName || "";
      button.closest("details")?.removeAttribute("open");
      muteDialog.showModal();
    });
  });
  document.querySelectorAll("[data-close-mute]").forEach((button) => {
    button.addEventListener("click", () => muteDialog?.close());
  });
  muteDialog?.addEventListener("click", (event) => {
    if (event.target === muteDialog) muteDialog.close();
  });

  const profileDialog = document.querySelector("[data-profile-dialog]");
  if (profileDialog?.dataset.openProfile === "true") profileDialog.showModal();
  document.querySelectorAll("[data-close-profile]").forEach((button) => {
    button.addEventListener("click", () => profileDialog?.close());
  });
  profileDialog?.addEventListener("click", (event) => {
    if (event.target === profileDialog) profileDialog.close();
  });
});
