const advisorForm = document.getElementById("advisor-form");
const advisorInput = document.getElementById("advisor-input");
const messages = document.getElementById("advisor-messages");
const solutionResults = document.getElementById("solution-results");
const solutionGrid = document.getElementById("solution-grid");
const requirementsSummary = document.getElementById("requirements-summary");
const questionsContainer = document.getElementById("advisor-questions");
let conversationId = null;

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const badge = document.createElement("span");
  badge.textContent = role === "assistant" ? "AI" : "YOU";
  const body = document.createElement("div");
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.appendChild(paragraph);
  article.append(badge, body);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function showAdvisorToast(message) {
  const toast = document.getElementById("advisor-toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function addOptionToCart(option) {
  const cart = getCart();
  option.products.forEach((product) => {
    const existing = cart.find((item) => item.id === product.product_id);
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
      });
    }
  });
  saveCart(cart);
  showAdvisorToast(`${option.name} was added to your review cart.`);
}

function renderOptions(options) {
  solutionGrid.innerHTML = "";
  options.forEach((option, index) => {
    const card = document.createElement("article");
    if (index === 1) card.classList.add("recommended");
    const products = option.products
      .map(
        (product) => `<li><div><b>${escapeHtml(product.name)}</b><small>${escapeHtml(product.brand)} · ${escapeHtml(product.category)}</small></div><span>×${product.quantity}</span><p>${escapeHtml(product.reason)}</p>${product.optional ? '<em>Optional</em>' : ""}</li>`,
      )
      .join("");
    card.innerHTML = `<header><span>OPTION ${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(option.name)}</h3><p>${escapeHtml(option.summary)}</p></header><div class="option-rationale">${escapeHtml(option.rationale)}</div><ul>${products}</ul><footer><span>${option.products.length} product line(s)</span><button type="button">Add solution to cart →</button></footer>`;
    card.querySelector("button").addEventListener("click", () => addOptionToCart(option));
    solutionGrid.appendChild(card);
  });
  solutionResults.hidden = options.length === 0;
}

advisorInput?.addEventListener("input", () => {
  document.getElementById("character-count").textContent = advisorInput.value.length;
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
  try {
    const response = await fetch("/api/ai/advisor", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
      },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to analyze requirements.");
    conversationId = result.conversation_id;
    appendMessage("assistant", result.message);
    requirementsSummary.textContent = result.requirements_summary || "More information is required.";
    questionsContainer.innerHTML = result.questions.length
      ? `<b>Questions to consider</b><ol>${result.questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}</ol>`
      : "";
    renderOptions(result.options);
  } catch (error) {
    appendMessage("assistant", error.message);
  } finally {
    button.disabled = document.body.dataset.aiConfigured !== "true";
    button.textContent = "Analyze requirements →";
  }
});

document.getElementById("new-conversation")?.addEventListener("click", () => {
  conversationId = null;
  solutionResults.hidden = true;
  solutionGrid.innerHTML = "";
  requirementsSummary.textContent = "Your project brief will appear here as the advisor learns about your requirements.";
  questionsContainer.innerHTML = "";
  messages.innerHTML = '<article class="message assistant"><span>AI</span><div><p>Start a new consultation by describing the business or technical problem you want VTIC to solve.</p></div></article>';
});
