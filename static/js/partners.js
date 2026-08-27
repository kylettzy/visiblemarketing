document.addEventListener("DOMContentLoaded", () => {
  const buttons = [...document.querySelectorAll("[data-partner-filter]")];
  const groups = [...document.querySelectorAll("[data-partner-group]")];
  const search = document.querySelector("[data-partner-search]");
  let activeCategory = "all";

  const update = () => {
    const query = (search?.value || "").trim().toLowerCase();
    groups.forEach((group) => {
      const categoryMatches = activeCategory === "all" || group.dataset.partnerGroup === activeCategory;
      let visibleCards = 0;
      group.querySelectorAll("[data-partner-name]").forEach((card) => {
        const matches = !query || card.dataset.partnerName.includes(query);
        card.hidden = !matches;
        if (matches) visibleCards += 1;
      });
      group.hidden = !categoryMatches || visibleCards === 0;
    });
  };

  buttons.forEach((button) => button.addEventListener("click", () => {
    activeCategory = button.dataset.partnerFilter;
    buttons.forEach((item) => item.classList.toggle("active", item === button));
    update();
  }));
  search?.addEventListener("input", update);
});
