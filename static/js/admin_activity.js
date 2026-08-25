const logFilterButtons = [...document.querySelectorAll("[data-log-filter]")];
const logGroups = [...document.querySelectorAll("[data-log-group]")];

logFilterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.logFilter;
    logFilterButtons.forEach((item) =>
      item.classList.toggle("active", item === button),
    );
    logGroups.forEach((group) => {
      group.hidden = filter !== "all" && group.dataset.logGroup !== filter;
    });
  });
});
