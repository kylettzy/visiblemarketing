const logoInput = document.querySelector("[data-logo-input]");
const logoUrl = document.querySelector("[data-logo-url]");
const logoPreview = document.querySelector("[data-logo-preview]");

function showLogoPreview(source) {
  if (!logoPreview || !source) return;
  logoPreview.replaceChildren();
  const image = document.createElement("img");
  image.src = source;
  image.alt = "Selected manufacturer logo preview";
  image.addEventListener("error", () => {
    logoPreview.textContent = "Invalid image";
  });
  logoPreview.appendChild(image);
}

logoInput?.addEventListener("change", () => {
  const file = logoInput.files?.[0];
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    logoPreview.textContent = "Select an image file";
    return;
  }

  const reader = new FileReader();
  reader.addEventListener("load", () => showLogoPreview(reader.result));
  reader.readAsDataURL(file);
});

logoUrl?.addEventListener("change", () => {
  if (logoUrl.value.trim()) showLogoPreview(logoUrl.value.trim());
});
