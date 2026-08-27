const advisorForm = document.getElementById("advisor-form");
const advisorInput = document.getElementById("advisor-input");
const messages = document.getElementById("advisor-messages");
const solutionResults = document.getElementById("solution-results");
const solutionGrid = document.getElementById("solution-grid");
const requirementsSummary = document.getElementById("requirements-summary");
const questionsContainer = document.getElementById("advisor-questions");
const historyList = document.getElementById("conversation-history-list");
let conversationId = null;

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const badge = document.createElement("span");
  badge.textContent = role === "assistant" ? "VT" : "YOU";
  const body = document.createElement("div");
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.appendChild(paragraph);
  article.append(badge, body);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function appendTypingIndicator() {
  const article = document.createElement("article");
  article.className = "message assistant typing-message";
  article.innerHTML =
    '<span>VT</span><div><p>VTIC Advisor is analyzing your requirements</p><span class="typing-dots" aria-label="VTIC Advisor is replying"><i></i><i></i><i></i></span></div>';
  messages.appendChild(article);
  messages.setAttribute("aria-busy", "true");
  messages.scrollTop = messages.scrollHeight;
  return () => {
    article.remove();
    messages.setAttribute("aria-busy", "false");
  };
}

function formatHistoryDate(value) {
  if (!value) return "";
  const parsed = new Date(`${value.replace(" ", "T")}Z`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        year:
          parsed.getFullYear() === new Date().getFullYear()
            ? undefined
            : "numeric",
      }).format(parsed);
}

async function loadConversationHistory() {
  if (!historyList) return;
  try {
    const response = await fetch("/api/ai/advisor/conversations");
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Unable to load history.");
    if (!result.conversations.length) {
      historyList.innerHTML =
        '<div class="history-empty"><b>No saved consultations</b><p>Your first conversation will appear here automatically.</p></div>';
      return;
    }
    historyList.innerHTML = result.conversations
      .map(
        (conversation) =>
          `<button type="button" class="history-item ${conversation.id === conversationId ? "active" : ""}" data-conversation-id="${conversation.id}"><span>${escapeHtml(conversation.title)}</span><small>${conversation.message_count} message${conversation.message_count === 1 ? "" : "s"} · ${escapeHtml(formatHistoryDate(conversation.updated_at))}</small></button>`,
      )
      .join("");
    historyList.querySelectorAll("[data-conversation-id]").forEach((button) => {
      button.addEventListener("click", () =>
        loadConversation(Number(button.dataset.conversationId)),
      );
    });
  } catch (error) {
    historyList.innerHTML = `<p class="history-error">${escapeHtml(error.message)}</p>`;
  }
}

async function loadConversation(id) {
  advisorInput.disabled = true;
  try {
    const response = await fetch(`/api/ai/advisor/conversations/${id}`);
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Unable to open conversation.");
    conversationId = result.conversation.id;
    messages.innerHTML = "";
    result.messages.forEach((message) =>
      appendMessage(message.role, message.content),
    );
    requirementsSummary.textContent =
      result.conversation.requirements_summary ||
      "No requirements summary was captured yet.";
    questionsContainer.innerHTML = "";
    renderOptions(result.options || []);
    await loadConversationHistory();
    messages.scrollTop = messages.scrollHeight;
  } catch (error) {
    showAdvisorToast(error.message);
  } finally {
    advisorInput.disabled = false;
    advisorInput.focus();
  }
}

function showAdvisorToast(message) {
  const toast = document.getElementById("advisor-toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function addOptionToCart(option, optionNumber, button) {
  const cart = getCart();
  const groupId = `solution:${option.id}`;
  option.products.forEach((product) => {
    const lineId = `${groupId}:product:${product.product_id}`;
    const existing = cart.find((item) => item.line_id === lineId);
    if (existing) {
      existing.qty += product.quantity;
    } else {
      cart.push({
        id: product.product_id,
        name: product.name,
        brand: product.brand,
        category: product.category,
        qty: product.quantity,
        ai_solution_option_id: option.id,
        group_kind: "solution",
        group_id: groupId,
        group_label: `Option ${String(optionNumber).padStart(2, "0")} · ${option.name}`,
        line_id: lineId,
      });
    }
  });
  saveCart(cart);
  if (button) {
    button.textContent = "Added to review list ✓";
    window.setTimeout(() => {
      button.textContent = "Add this option →";
    }, 1800);
  }
  showAdvisorToast(`${option.name} was added to your review list.`);
}

function renderOptions(options) {
  solutionGrid.innerHTML = "";
  options.forEach((option, index) => {
    const card = document.createElement("article");
    if (index === 1) card.classList.add("recommended");
    const products = option.products
      .map(
        (product) =>
          `<li><div><b>${escapeHtml(product.name)}</b><small>${escapeHtml(product.brand)} · ${escapeHtml(product.category)}</small></div><span>×${product.quantity}</span><p>${escapeHtml(product.reason)}</p>${product.optional ? "<em>Optional</em>" : ""}</li>`,
      )
      .join("");
    card.innerHTML = `<header><div><span>OPTION ${String(index + 1).padStart(2, "0")}</span>${index === 1 ? "<em>RECOMMENDED</em>" : ""}</div><h3>${escapeHtml(option.name)}</h3><p>${escapeHtml(option.summary)}</p></header><details><summary>View ${option.products.length} product line(s)</summary><div class="option-rationale">${escapeHtml(option.rationale)}</div><ul>${products}</ul></details><footer><button type="button">Add this option →</button></footer>`;
    const button = card.querySelector("button");
    button.addEventListener("click", () =>
      addOptionToCart(option, index + 1, button),
    );
    solutionGrid.appendChild(card);
  });
  solutionResults.hidden = options.length === 0;
}

advisorInput?.addEventListener("input", () => {
  document.getElementById("character-count").textContent =
    advisorInput.value.length;
});

advisorInput?.addEventListener("keydown", (event) => {
  if (
    event.key !== "Enter" ||
    event.shiftKey ||
    event.isComposing ||
    advisorInput.disabled
  ) {
    return;
  }

  event.preventDefault();
  advisorForm?.requestSubmit();
});

advisorForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = advisorInput.value.trim();
  if (!message) return;
  const button = advisorForm.querySelector('button[type="submit"]');
  appendMessage("user", message);
  advisorInput.value = "";
  document.getElementById("character-count").textContent = "0";
  button.disabled = true;
  button.textContent = "Analyzing…";
  const removeTypingIndicator = appendTypingIndicator();
  try {
    const response = await fetch("/api/ai/advisor", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')
          .content,
      },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Unable to analyze requirements.");
    conversationId = result.conversation_id;
    removeTypingIndicator();
    appendMessage("assistant", result.message);
    requirementsSummary.textContent =
      result.requirements_summary || "More information is required.";
    questionsContainer.innerHTML = result.questions.length
      ? `<b>Questions to consider</b><ol>${result.questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}</ol>`
      : "";
    renderOptions(result.options);
    await loadConversationHistory();
  } catch (error) {
    removeTypingIndicator();
    appendMessage("assistant", error.message);
  } finally {
    button.disabled = document.body.dataset.aiConfigured !== "true";
    button.textContent = "Analyze requirements →";
  }
});

function startNewConversation() {
  conversationId = null;
  solutionResults.hidden = true;
  solutionGrid.innerHTML = "";
  requirementsSummary.textContent =
    "Your project brief will appear here as the advisor learns about your requirements.";
  questionsContainer.innerHTML = "";
  messages.innerHTML =
    '<article class="message assistant"><span>VT</span><div><p>Start a new consultation by describing the business or technical problem you want VTIC to solve.</p></div></article>';
  loadConversationHistory();
  advisorInput.focus();
}

document
  .getElementById("new-conversation")
  ?.addEventListener("click", startNewConversation);
document
  .getElementById("history-new-conversation")
  ?.addEventListener("click", startNewConversation);

loadConversationHistory();
