document.querySelectorAll("form[data-auth-ajax]").forEach((form) => {
  const errorBox = form.querySelector("[data-auth-error]");
  const submitButton = form.querySelector('button[type="submit"]');

  const clearErrors = () => {
    errorBox?.classList.remove("is-visible");
    form
      .querySelectorAll(".auth-field-error")
      .forEach((field) => field.classList.remove("auth-field-error"));
  };

  form.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => {
      input.closest("label")?.classList.remove("auth-field-error");
      if (!form.querySelector(".auth-field-error")) {
        errorBox?.classList.remove("is-visible");
      }
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearErrors();
    if (!form.reportValidity()) return;

    submitButton?.setAttribute("disabled", "");
    form.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });
      const result = await response.json();
      if (response.ok && result.redirect) {
        window.location.assign(result.redirect);
        return;
      }

      (result.fields || []).forEach((name) =>
        form.elements[name]
          ?.closest("label")
          ?.classList.add("auth-field-error"),
      );
      if (errorBox) {
        errorBox.textContent =
          result.message || "Please check the highlighted fields.";
        errorBox.classList.add("is-visible");
        errorBox.focus();
      }
    } catch (_error) {
      if (errorBox) {
        errorBox.textContent =
          "We could not verify your details. Please try again.";
        errorBox.classList.add("is-visible");
      }
    } finally {
      submitButton?.removeAttribute("disabled");
      form.removeAttribute("aria-busy");
    }
  });
});
