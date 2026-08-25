(() => {
  const STORAGE_KEY = "vtic-appearance-theme";
  const root = document.documentElement;
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

  const getSavedTheme = () => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  };

  const getSystemTheme = () => (systemTheme.matches ? "dark" : "light");

  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
  };

  const applyPreferredTheme = () => {
    applyTheme(getSavedTheme() || getSystemTheme());
  };

  const initializeAppearanceSettings = () => {
    document.querySelectorAll("[data-theme-setting]").forEach((control) => {
      control.value = getSavedTheme() || "system";

      control.addEventListener("change", () => {
        if (control.value === "system") {
          localStorage.removeItem(STORAGE_KEY);
          applyTheme(getSystemTheme());
          return;
        }

        localStorage.setItem(STORAGE_KEY, control.value);
        applyTheme(control.value);
      });
    });
  };

  applyPreferredTheme();
  document.addEventListener("DOMContentLoaded", initializeAppearanceSettings);

  systemTheme.addEventListener("change", () => {
    if (!getSavedTheme()) {
      applyTheme(getSystemTheme());
    }
  });
})();
