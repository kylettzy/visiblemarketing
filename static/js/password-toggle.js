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

document
  .querySelectorAll('input[type="password"], input[data-password-input]')
  .forEach((input) => {
    input.addEventListener("copy", (event) => event.preventDefault());
    input.addEventListener("cut", (event) => event.preventDefault());
    input.addEventListener("paste", (event) => event.preventDefault());
    input.addEventListener("drop", (event) => event.preventDefault());
    input.setAttribute("data-password-input", "");
  });

document
  .querySelectorAll(
    'input[autocomplete="new-password"]:not([name="confirm_password"])',
  )
  .forEach((input) => {
    const control = input.closest(".password-control");
    if (
      !control ||
      control.nextElementSibling?.classList.contains("password-strength")
    )
      return;

    const meter = document.createElement("div");
    meter.className = "password-strength";
    meter.dataset.level = "empty";
    meter.setAttribute("role", "status");
    meter.setAttribute("aria-live", "polite");
    meter.innerHTML =
      '<div class="password-strength-track"><div class="password-strength-fill"></div></div>' +
      '<div class="password-strength-copy"><span>Password strength</span><strong>Start typing</strong></div>';
    control.insertAdjacentElement("afterend", meter);

    const updateStrength = () => {
      const value = input.value;
      const checks = [
        value.length >= 12,
        /[a-z]/.test(value) && /[A-Z]/.test(value),
        /\d/.test(value),
        /[^A-Za-z0-9]/.test(value),
      ];
      const score = checks.filter(Boolean).length;
      const level = !value
        ? "empty"
        : value.length < 12
          ? value.length < 8
            ? "weak"
            : "fair"
          : ["weak", "weak", "fair", "good", "strong"][score];
      const label = {
        empty: "Start typing",
        weak: "Weak",
        fair: "Fair",
        good: "Good",
        strong: "Strong",
      }[level];
      meter.dataset.level = level;
      meter.querySelector("strong").textContent = label;
    };
    input.addEventListener("input", updateStrength);
    updateStrength();
  });
