const productGrid = document.querySelector("[data-product-grid]");

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const listView = button.dataset.view === "list";
    productGrid?.classList.toggle("list-view", listView);
    document.querySelectorAll("[data-view]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    localStorage.setItem("vtic-catalog-view", listView ? "list" : "grid");
  });
});

if (localStorage.getItem("vtic-catalog-view") === "list") {
  document.querySelector('[data-view="list"]')?.click();
}

document
  .querySelector("[data-filter-toggle]")
  ?.addEventListener("click", (event) => {
    const filters = document.getElementById("catalog-filters");
    const expanded = filters?.classList.toggle("open") || false;
    event.currentTarget.textContent = expanded ? "Close filters" : "Filters";
  });
