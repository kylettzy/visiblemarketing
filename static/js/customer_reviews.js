const reviewFilterButtons = [...document.querySelectorAll("[data-review-filter]")];
const reviewFilterStorageKey = `vtic-active-tab:${location.pathname}`;

function activateReviewFilter(button) {
  if (!button) return;
  reviewFilterButtons.forEach((item) => item.classList.toggle("active", item === button));
  const filter = button.dataset.reviewFilter;
  document.querySelectorAll("[data-review-card]").forEach((card) => {
    card.hidden = filter !== "all" && card.dataset.status !== filter;
  });
  sessionStorage.setItem(reviewFilterStorageKey, filter);
}

reviewFilterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activateReviewFilter(button);
  });
});

const savedReviewFilter = sessionStorage.getItem(reviewFilterStorageKey);
activateReviewFilter(
  reviewFilterButtons.find((button) => button.dataset.reviewFilter === savedReviewFilter) ||
    reviewFilterButtons[0],
);
