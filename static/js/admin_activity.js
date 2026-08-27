const logFilterButtons = [...document.querySelectorAll("[data-log-filter]")];
const logGroups = [...document.querySelectorAll("[data-log-group]")];
const logFilterStorageKey = `vtic-active-tab:${location.pathname}`;

function activateLogFilter(button) {
  if (!button) return;
  const filter = button.dataset.logFilter;
  logFilterButtons.forEach((item) =>
    item.classList.toggle("active", item === button),
  );
  logGroups.forEach((group) => {
    group.hidden = filter !== "all" && group.dataset.logGroup !== filter;
  });
  sessionStorage.setItem(logFilterStorageKey, filter);
}

logFilterButtons.forEach((button) => {
  button.addEventListener("click", () => activateLogFilter(button));
});

const savedLogFilter = sessionStorage.getItem(logFilterStorageKey);
activateLogFilter(
  logFilterButtons.find((button) => button.dataset.logFilter === savedLogFilter) ||
    logFilterButtons[0],
);
