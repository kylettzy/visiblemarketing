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

const filters = document.getElementById("catalog-filters");
const filterToggle = document.querySelector("[data-filter-toggle]");
const filterBackdrop = document.querySelector(".catalog-filter-backdrop");

function setFilterDrawer(open) {
  if (!filters || !filterToggle || !filterBackdrop) return;
  filters.classList.toggle("open", open);
  filterToggle.setAttribute("aria-expanded", String(open));
  filterBackdrop.hidden = !open;
  document.body.classList.toggle("filter-drawer-open", open);
  if (open) filters.querySelector("[data-filter-close]")?.focus();
  else filterToggle.focus();
}

filterToggle?.addEventListener("click", () => setFilterDrawer(true));
document.querySelectorAll("[data-filter-close]").forEach((button) => {
  button.addEventListener("click", () => setFilterDrawer(false));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && filters?.classList.contains("open")) {
    setFilterDrawer(false);
  }
});
