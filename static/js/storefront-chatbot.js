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
  const historyPanel = widget.querySelector("[data-chat-history]");
  const historyList = widget.querySelector("[data-chat-history-list]");
  const historyToggle = widget.querySelector("[data-chat-history-toggle]");
  const historyCount = widget.querySelector("[data-chat-history-count]");
  const newChatButton = widget.querySelector("[data-chat-new]");
  const minimizedStorageKey = "vtic-storefront-chat-minimized";
  const initialMessages = messages.innerHTML;
  let conversationId = null;
  let historyLoaded = false;

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
    loadHistory();
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

  const formatDate = (value) => {
    const date = new Date(`${value?.replace(" ", "T")}Z`);
    return Number.isNaN(date.getTime())
      ? "Recent"
      : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
  };

  async function loadHistory() {
    try {
      const response = await fetch("/api/ai/product-chat/conversations");
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      const conversations = result.conversations || [];
      historyCount.textContent = conversations.length;
      historyList.innerHTML = "";
      if (!conversations.length) {
        const empty = document.createElement("p");
        empty.textContent = "No saved chats yet.";
        historyList.appendChild(empty);
      }
      conversations.forEach((conversation) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = conversation.id === conversationId ? "active" : "";
        const title = document.createElement("b");
        title.textContent = conversation.title;
        const meta = document.createElement("small");
        meta.textContent = `${conversation.message_count} messages · ${formatDate(conversation.updated_at)}`;
        const preview = document.createElement("span");
        preview.textContent = conversation.last_message || "Conversation started";
        button.append(title, meta, preview);
        button.addEventListener("click", () => openConversation(conversation.id));
        historyList.appendChild(button);
      });
      historyLoaded = true;
    } catch {
      historyList.innerHTML = "<p>Chats could not be loaded.</p>";
    }
  }

  async function openConversation(id) {
    try {
      const response = await fetch(`/api/ai/product-chat/conversations/${id}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      conversationId = result.conversation.id;
      messages.innerHTML = "";
      (result.messages || []).forEach((message) =>
        appendMessage(message.content, message.role === "user" ? "user" : "assistant"),
      );
      historyPanel.hidden = true;
      historyToggle.setAttribute("aria-expanded", "false");
      await loadHistory();
      input.focus();
    } catch {
      appendMessage("This conversation could not be opened.", "error");
    }
  }

  function startNewChat() {
    conversationId = null;
    messages.innerHTML = initialMessages;
    historyPanel.hidden = true;
    historyToggle.setAttribute("aria-expanded", "false");
    loadHistory();
    input.focus();
  }

  launcher.addEventListener("click", openChat);
  historyToggle.addEventListener("click", () => {
    historyPanel.hidden = !historyPanel.hidden;
    historyToggle.setAttribute("aria-expanded", String(!historyPanel.hidden));
    if (!historyLoaded) loadHistory();
  });
  newChatButton.addEventListener("click", startNewChat);
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
      showToast(`${product.name} added to review list`);
      appendMessage(`${product.name} was added to your review list.`, "assistant");
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
      if (response.ok) await loadHistory();
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
