document.querySelectorAll("[data-confirm-signout]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const confirmed = window.confirm(
      "Are you sure you want to sign out of your VTIC account?",
    );
    if (!confirmed) event.preventDefault();
  });
});
