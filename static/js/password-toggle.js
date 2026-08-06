document.querySelectorAll("[data-toggle-password]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.closest(".password-control").querySelector("input");
    const isVisible = input.type === "text";

    input.type = isVisible ? "password" : "text";
    button.textContent = isVisible ? "Show" : "Hide";
    button.setAttribute("aria-pressed", String(!isVisible));
    button.setAttribute(
      "aria-label",
      `${isVisible ? "Show" : "Hide"} ${input.name.replaceAll("_", " ")}`,
    );
  });
});
