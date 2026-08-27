(() => {
  const menus = [
    ...document.querySelectorAll(".landing-menu, .solution-menu"),
  ];

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
})();
