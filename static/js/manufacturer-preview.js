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

function showProductPreview(editor, source) {
  const preview = editor.querySelector("[data-product-image-preview]");
  if (!preview || !source) return;
  preview.replaceChildren();
  const image = document.createElement("img");
  image.src = source;
  image.alt = "Selected product picture preview";
  image.addEventListener("error", () => {
    preview.textContent = "Invalid image";
  });
  preview.appendChild(image);
}

document.querySelectorAll("[data-product-image-editor]").forEach((editor) => {
  const fileInput = editor.querySelector("[data-product-image-input]");
  const urlInput = editor.querySelector("[data-product-image-url]");

  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      editor.querySelector("[data-product-image-preview]").textContent =
        "Select an image file";
      return;
    }
    const reader = new FileReader();
    reader.addEventListener("load", () =>
      showProductPreview(editor, reader.result),
    );
    reader.readAsDataURL(file);
  });

  urlInput?.addEventListener("change", () => {
    if (urlInput.value.trim())
      showProductPreview(editor, urlInput.value.trim());
  });
});

const batchForm = document.querySelector("[data-product-batch-form]");
const selectAllProducts = document.querySelector("[data-product-select-all]");
const productSelections = [
  ...document.querySelectorAll("[data-product-select]"),
];
const selectionCount = document.querySelector("[data-product-selection-count]");
const deleteSelected = document.querySelector("[data-product-delete-selected]");

function updateProductBatchControls() {
  const selectedCount = productSelections.filter(
    (checkbox) => checkbox.checked,
  ).length;

  if (selectionCount) {
    selectionCount.textContent = selectedCount
      ? `${selectedCount} product${selectedCount === 1 ? "" : "s"} selected`
      : "Select all products";
  }
  if (deleteSelected) deleteSelected.disabled = selectedCount === 0;
  if (selectAllProducts) {
    selectAllProducts.checked =
      productSelections.length > 0 &&
      selectedCount === productSelections.length;
    selectAllProducts.indeterminate =
      selectedCount > 0 && selectedCount < productSelections.length;
  }
}

document
  .querySelectorAll("[data-product-select-control]")
  .forEach((control) => {
    control.addEventListener("click", (event) => event.stopPropagation());
  });

productSelections.forEach((checkbox) => {
  checkbox.addEventListener("change", updateProductBatchControls);
});

selectAllProducts?.addEventListener("change", () => {
  productSelections.forEach((checkbox) => {
    checkbox.checked = selectAllProducts.checked;
  });
  updateProductBatchControls();
});

batchForm?.addEventListener("submit", (event) => {
  const selectedCount = productSelections.filter(
    (checkbox) => checkbox.checked,
  ).length;
  if (!selectedCount) {
    event.preventDefault();
    return;
  }
  const confirmed = window.confirm(
    `Delete ${selectedCount} selected product${selectedCount === 1 ? "" : "s"}? This cannot be undone.`,
  );
  if (!confirmed) event.preventDefault();
});
