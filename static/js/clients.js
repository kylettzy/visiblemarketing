document.addEventListener("DOMContentLoaded", () => {
  const buttons = [...document.querySelectorAll("[data-client-filter]")];
  const cards = [...document.querySelectorAll("[data-client-sector]")];

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.clientFilter;
      buttons.forEach((item) => item.classList.toggle("active", item === button));
      cards.forEach((card) => {
        card.hidden = filter !== "all" && card.dataset.clientSector !== filter;
      });
    });
  });
});
