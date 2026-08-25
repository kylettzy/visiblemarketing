document.querySelectorAll("[data-review-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-review-filter]").forEach((item) => item.classList.toggle("active", item === button));
    const filter = button.dataset.reviewFilter;
    document.querySelectorAll("[data-review-card]").forEach((card) => {
      card.hidden = filter !== "all" && card.dataset.status !== filter;
    });
  });
});
