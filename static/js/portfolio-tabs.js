(() => {
  const tabs = [...document.querySelectorAll("[data-portfolio-tabs] [data-tab]")];
  const panels = [...document.querySelectorAll("[data-panel]")];
  if (!tabs.length) return;
  function activate(name) {
    tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    panels.forEach((panel) => {
      const selected = panel.dataset.panel === name;
      panel.hidden = !selected;
      panel.classList.toggle("active", selected);
    });
    history.replaceState(null, "", `#${name}`);
  }
  tabs.forEach((tab) => tab.addEventListener("click", () => activate(tab.dataset.tab)));
  const requested = location.hash.slice(1);
  if (tabs.some((tab) => tab.dataset.tab === requested)) activate(requested);
})();
