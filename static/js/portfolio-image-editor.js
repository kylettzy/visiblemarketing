(() => {
  const dialog = document.querySelector("[data-image-editor-dialog]");
  if (!dialog) return;
  const canvas = dialog.querySelector("[data-image-canvas]");
  const context = canvas.getContext("2d");
  const zoom = dialog.querySelector("[data-image-zoom]");
  const positionX = dialog.querySelector("[data-image-x]");
  const positionY = dialog.querySelector("[data-image-y]");
  let activeInput = null;
  let sourceImage = null;

  function dimensions() {
    const aspect = Number(activeInput?.dataset.aspect || 1.6);
    return aspect > 2 ? [900, 300] : [1200, 750];
  }

  function draw() {
    if (!sourceImage || !activeInput) return;
    const [width, height] = dimensions();
    canvas.width = width;
    canvas.height = height;
    const baseScale = Math.max(
      width / sourceImage.naturalWidth,
      height / sourceImage.naturalHeight,
    );
    const scale = baseScale * Number(zoom.value);
    const drawWidth = sourceImage.naturalWidth * scale;
    const drawHeight = sourceImage.naturalHeight * scale;
    const overflowX = Math.max(0, drawWidth - width);
    const overflowY = Math.max(0, drawHeight - height);
    const x =
      (width - drawWidth) / 2 + (Number(positionX.value) * overflowX) / 2;
    const y =
      (height - drawHeight) / 2 + (Number(positionY.value) * overflowY) / 2;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(sourceImage, x, y, drawWidth, drawHeight);
  }

  document.querySelectorAll("[data-image-editor]").forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (!file) return;
      if (!file.type.startsWith("image/")) {
        input.value = "";
        return;
      }
      activeInput = input;
      zoom.value = "1";
      positionX.value = "0";
      positionY.value = "0";
      const image = new Image();
      image.onload = () => {
        sourceImage = image;
        draw();
        dialog.showModal();
        URL.revokeObjectURL(image.src);
      };
      image.src = URL.createObjectURL(file);
    });
  });

  [zoom, positionX, positionY].forEach((control) =>
    control.addEventListener("input", draw),
  );
  dialog.querySelector("[data-image-cancel]").addEventListener("click", () => {
    if (activeInput) activeInput.value = "";
    dialog.close();
  });
  dialog.querySelector("form").addEventListener("submit", () => {
    if (activeInput) activeInput.value = "";
  });
  dialog.querySelector("[data-image-apply]").addEventListener("click", () => {
    if (!activeInput) return;
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const transfer = new DataTransfer();
        transfer.items.add(
          new File([blob], "portfolio-image.jpg", { type: "image/jpeg" }),
        );
        activeInput.files = transfer.files;
        activeInput.closest("label")?.classList.add("has-edited-image");
        dialog.close();
      },
      "image/jpeg",
      0.9,
    );
  });
})();
