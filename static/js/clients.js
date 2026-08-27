document.addEventListener("DOMContentLoaded", () => {
  const buttons = [...document.querySelectorAll("[data-client-filter]")];
  const cards = [...document.querySelectorAll("[data-client-sector]")];
  const storageKey = `vtic-active-tab:${location.pathname}`;

  const activate = (button) => {
    if (!button) return;
    const filter = button.dataset.clientFilter;
    buttons.forEach((item) => item.classList.toggle("active", item === button));
    cards.forEach((card) => {
      card.hidden = filter !== "all" && card.dataset.clientSector !== filter;
    });
    sessionStorage.setItem(storageKey, filter);
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => activate(button));
  });

  const saved = sessionStorage.getItem(storageKey);
  activate(buttons.find((button) => button.dataset.clientFilter === saved) || buttons[0]);
});
