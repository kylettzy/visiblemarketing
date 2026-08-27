(() => {
  const reel = document.querySelector("[data-solution-reel]");
  if (!reel) return;

  const video = reel.querySelector("[data-solution-reel-video]");
  const title = reel.querySelector("[data-solution-reel-title]");
  const index = reel.querySelector("[data-solution-reel-index]");
  const link = reel.querySelector("[data-solution-reel-link]");
  const buttons = [...reel.querySelectorAll("[data-video]")];

  const selectVideo = (buttonIndex) => {
    const normalizedIndex = (buttonIndex + buttons.length) % buttons.length;
    const button = buttons[normalizedIndex];
    buttons.forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    video.src = button.dataset.video;
    video.load();
    video.play().catch(() => {});
    if (title) title.textContent = button.dataset.title;
    if (index) {
      index.textContent = `${String(normalizedIndex + 1).padStart(2, "0")} / ${String(buttons.length).padStart(2, "0")}`;
    }
    if (link) {
      link.href = button.dataset.link;
      link.textContent = normalizedIndex === 0 ? "Explore our solutions →" : `Explore ${button.dataset.title} →`;
    }
  };

  buttons.forEach((button, buttonIndex) => {
    button.addEventListener("click", () => selectVideo(buttonIndex));
  });

  video.addEventListener("ended", () => {
    const activeIndex = buttons.findIndex((button) =>
      button.classList.contains("is-active"),
    );
    selectVideo(activeIndex + 1);
  });
})();
