(() => {
  const header = document.querySelector(".site-header");
  const navigation = document.querySelector("#landing-navigation");
  const toggle = document.querySelector(".mobile-nav-toggle");
  const menus = [...document.querySelectorAll(".landing-menu, .solution-menu")];

  const closeOthers = (activeMenu) => {
    menus.forEach((menu) => {
      if (menu !== activeMenu) menu.open = false;
    });
  };

  menus.forEach((menu) => {
    menu.addEventListener("pointerenter", () => {
      closeOthers(menu);
      menu.open = true;
    });

    menu.addEventListener("pointerleave", () => {
      menu.open = false;
    });

    menu.addEventListener("focusin", () => {
      closeOthers(menu);
      menu.open = true;
    });

    menu.addEventListener("focusout", (event) => {
      if (!menu.contains(event.relatedTarget)) menu.open = false;
    });
  });

  if (!header || !navigation || !toggle) return;

  const setMenuOpen = (open) => {
    header.classList.toggle("is-menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute(
      "aria-label",
      open ? "Close navigation" : "Open navigation",
    );
  };

  toggle.addEventListener("click", () => {
    setMenuOpen(!header.classList.contains("is-menu-open"));
  });

  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setMenuOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setMenuOpen(false);
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 980) setMenuOpen(false);
  });
})();
