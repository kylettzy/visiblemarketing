document.addEventListener("DOMContentLoaded", () => {
  const filters = [...document.querySelectorAll("[data-gallery-filter]")];
  const items = [...document.querySelectorAll("[data-gallery-item]")];
  const lightbox = document.querySelector("[data-gallery-lightbox]");
  let activePhotos = [];
  let activeIndex = 0;

  const showPhoto = (index) => {
    if (!activePhotos.length || !lightbox) return;
    activeIndex = (index + activePhotos.length) % activePhotos.length;
    const photo = activePhotos[activeIndex];
    const image = lightbox.querySelector("[data-gallery-full]");
    const video = lightbox.querySelector("[data-gallery-video]");
    const download = lightbox.querySelector("[data-gallery-download]");
    const isVideo = photo.type === "video";
    const mediaSource = isVideo ? photo.video_src : photo.src;
    image.hidden = isVideo;
    video.hidden = !isVideo;
    video.pause();
    if (isVideo) {
      video.src = mediaSource;
      image.removeAttribute("src");
    } else {
      image.src = mediaSource;
      image.alt = photo.title;
      video.removeAttribute("src");
    }
    download.href = mediaSource;
    download.download = `${photo.title || "VTIC gallery media"}.${isVideo ? "mp4" : "jpg"}`
      .replace(/[^a-z0-9._ -]/gi, "")
      .replace(/\s+/g, "-");
    lightbox.querySelector("[data-gallery-title]").textContent = photo.title;
    lightbox.querySelector("[data-gallery-meta]").textContent =
      activePhotos.length > 1
        ? `${photo.meta} · ${activeIndex + 1} of ${activePhotos.length}`
        : photo.meta;
    lightbox.classList.toggle("is-album", activePhotos.length > 1);
  };

  filters.forEach((button) =>
    button.addEventListener("click", () => {
      const filter = button.dataset.galleryFilter;
      filters.forEach((entry) => entry.classList.toggle("active", entry === button));
      items.forEach((item) => {
        item.hidden = filter !== "all" && item.dataset.category !== filter;
      });
    }),
  );

  items.forEach((item) =>
    item.querySelector("[data-gallery-open]")?.addEventListener("click", () => {
      activePhotos = JSON.parse(item.dataset.galleryPhotos || "[]");
      showPhoto(0);
      lightbox.showModal();
    }),
  );

  lightbox?.querySelector("[data-gallery-prev]")?.addEventListener("click", () => showPhoto(activeIndex - 1));
  lightbox?.querySelector("[data-gallery-next]")?.addEventListener("click", () => showPhoto(activeIndex + 1));
  lightbox?.querySelector("[data-gallery-close]")?.addEventListener("click", () => lightbox.close());
  lightbox?.addEventListener("click", (event) => {
    if (event.target === lightbox) lightbox.close();
  });
  document.addEventListener("keydown", (event) => {
    if (!lightbox?.open || activePhotos.length < 2) return;
    if (event.key === "ArrowLeft") showPhoto(activeIndex - 1);
    if (event.key === "ArrowRight") showPhoto(activeIndex + 1);
  });
});
