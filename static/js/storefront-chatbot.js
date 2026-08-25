(() => {
  const widget = document.querySelector("[data-storefront-chat]");
  if (!widget) return;

  const panel = widget.querySelector(".storefront-chat__panel");
  const launcher = widget.querySelector("[data-chat-toggle]");
  const messages = widget.querySelector("[data-chat-messages]");
  const form = widget.querySelector("[data-chat-form]");
  const input = widget.querySelector("[data-chat-input]");
  const hideButton = widget.querySelector("[data-chat-hide]");
  const showButton = widget.querySelector("[data-chat-show]");
  const minimizedStorageKey = "vtic-storefront-chat-minimized";
  let conversationId = null;

  const setMinimized = (minimized) => {
    widget.classList.toggle("is-minimized", minimized);
    showButton.hidden = !minimized;
    try {
      localStorage.setItem(minimizedStorageKey, minimized ? "true" : "false");
    } catch {
      // The control still works when browser storage is unavailable.
    }
  };

  try {
    setMinimized(localStorage.getItem(minimizedStorageKey) === "true");
  } catch {
    setMinimized(false);
  }

  const openChat = () => {
    panel.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    input?.focus();
  };

  const closeChat = () => {
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  };

  const appendMessage = (text, type) => {
    const message = document.createElement("div");
    message.className = `storefront-chat__message storefront-chat__message--${type}`;
    message.textContent = text;
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
  };

  launcher.addEventListener("click", openChat);
  hideButton.addEventListener("click", () => setMinimized(true));
  showButton.addEventListener("click", () => setMinimized(false));
  widget
    .querySelector("[data-chat-close]")
    .addEventListener("click", closeChat);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) closeChat();
  });

  input.addEventListener("keydown", (event) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.isComposing ||
      input.disabled
    ) {
      return;
    }

    event.preventDefault();
    form.requestSubmit();
  });

  widget
    .querySelector("[data-chat-add-product]")
    ?.addEventListener("click", () => {
      const product = JSON.parse(widget.dataset.product);
      const cart = getCart();
      const existingItem = cart.find((item) => item.id === product.id);
      if (existingItem) existingItem.qty += 1;
      else cart.push({ ...product, qty: 1 });
      saveCart(cart);
      showToast(`${product.name} added to cart`);
      appendMessage(`${product.name} was added to your cart.`, "assistant");
    });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;

    appendMessage(question, "user");
    input.value = "";
    input.disabled = true;
    const sendButton = form.querySelector("button[type='submit']");
    sendButton.disabled = true;
    const pending = appendMessage("Thinking…", "assistant");

    try {
      const response = await fetch("/api/ai/product-chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": widget.dataset.csrfToken,
        },
        body: JSON.stringify({
          message: question,
          conversation_id: conversationId,
          product_id: widget.dataset.productId || null,
        }),
      });
      const result = await response.json();
      conversationId = result.conversation_id || conversationId;
      pending.remove();
      appendMessage(
        result.answer || result.error || "No response was received.",
        response.ok ? "assistant" : "error",
      );
    } catch {
      pending.remove();
      appendMessage(
        "The assistant could not connect. Please try again.",
        "error",
      );
    } finally {
      input.disabled = false;
      sendButton.disabled = false;
      input.focus();
    }
  });
})();
