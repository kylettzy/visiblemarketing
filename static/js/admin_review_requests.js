document.addEventListener("DOMContentLoaded", () => {
  const chats = [...document.querySelectorAll("[data-floating-chat]")];

  chats.forEach((chat, index) => {
    chat.style.setProperty("--chat-index", Math.min(index, 5));

    chat.addEventListener("toggle", () => {
      if (!chat.open) return;
      chats.forEach((other) => {
        if (other !== chat) other.open = false;
      });
      const messages = chat.querySelector(".request-chat-messages");
      if (messages) messages.scrollTop = messages.scrollHeight;
    });

    chat.querySelector("[data-close-chat]")?.addEventListener("click", () => {
      chat.open = false;
    });
  });
});
