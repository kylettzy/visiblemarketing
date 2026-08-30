document.addEventListener("DOMContentLoaded", () => {
  const filters = [...document.querySelectorAll("[data-gallery-filter]")];
  const items = [...document.querySelectorAll("[data-gallery-item]")];
  const lightbox = document.querySelector("[data-gallery-lightbox]");
  let activePhotos = [];
  let activeIndex = 0;

  const openLightbox = (photos, index = 0) => {
    activePhotos = photos;
    showPhoto(index);
    lightbox?.showModal();
  };

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

  items.forEach((item) => {
    const photos = JSON.parse(item.dataset.galleryPhotos || "[]");
    const trigger = item.querySelector("[data-gallery-open]");
    const useSwipeAlbum =
      photos.length > 1 && window.matchMedia("(max-width: 540px)").matches;

    if (!useSwipeAlbum) {
      trigger?.addEventListener("click", () => openLightbox(photos));
      return;
    }

    const swipe = document.createElement("div");
    swipe.className = "gallery-swipe";
    swipe.setAttribute("role", "group");
    swipe.setAttribute("aria-label", `Swipe through ${photos.length} album photos`);

    const track = document.createElement("div");
    track.className = "gallery-swipe__track";

    photos.forEach((photo, index) => {
      const slide = document.createElement("button");
      slide.className = "gallery-swipe__slide";
      slide.type = "button";
      slide.setAttribute("aria-label", `Open photo ${index + 1} of ${photos.length}`);

      if (photo.type === "video") {
        const video = document.createElement("video");
        video.src = `${photo.video_src}#t=0.1`;
        video.muted = true;
        video.playsInline = true;
        video.preload = "metadata";
        slide.append(video);
      } else {
        const image = document.createElement("img");
        image.src = photo.src;
        image.alt = photo.title || `Album photo ${index + 1}`;
        image.loading = index === 0 ? "eager" : "lazy";
        slide.append(image);
      }

      slide.addEventListener("click", () => openLightbox(photos, index));
      track.append(slide);
    });

    const counter = document.createElement("span");
    counter.className = "gallery-swipe__counter";
    counter.textContent = `1 / ${photos.length}`;

    const hint = document.createElement("span");
    hint.className = "gallery-swipe__hint";
    hint.textContent = "Swipe to browse →";

    let frame;
    track.addEventListener(
      "scroll",
      () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const index = Math.round(track.scrollLeft / track.clientWidth);
          counter.textContent = `${index + 1} / ${photos.length}`;
        });
      },
      { passive: true },
    );

    swipe.append(track, counter, hint);
    trigger?.replaceWith(swipe);
  });

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
