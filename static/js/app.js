const CART_KEY = "vtic-procurement-cart";
const selectedCartItems = new Set();

const cartSlug = (value) =>
  String(value || "Unassigned")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

const normalizeCartItem = (item) => {
  const solutionId = item.ai_solution_option_id;
  const groupKind = solutionId ? "solution" : "manufacturer";
  const groupId = solutionId
    ? `solution:${solutionId}`
    : `manufacturer:${cartSlug(item.brand)}`;
  return {
    ...item,
    qty: Math.max(1, Number(item.qty) || 1),
    group_kind: item.group_kind || groupKind,
    group_id: item.group_id || groupId,
    group_label:
      item.group_label ||
      (solutionId
        ? `VTIC Advisor solution ${solutionId}`
        : item.brand || "Other products"),
    line_id: item.line_id || `${groupId}:product:${item.id}`,
  };
};

const getCart = () => {
  try {
    const stored = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    return Array.isArray(stored) ? stored.map(normalizeCartItem) : [];
  } catch {
    return [];
  }
};

const saveCart = (cart) => {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
  updateCartCount();
};

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

function updateCartCount() {
  const count = getCart().reduce((total, item) => total + item.qty, 0);
  document.querySelectorAll("[data-cart-count]").forEach((element) => {
    element.textContent = count;
  });
}

function showToast(message = "Added to review list") {
  const toast = document.getElementById("toast");
  if (!toast) return;

  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 1800);
}

document.querySelectorAll("[data-add]").forEach((button) => {
  button.addEventListener("click", () => {
    const product = JSON.parse(button.dataset.add);
    const selectedQuantity = Number(
      document.querySelector("[data-qty-value]")?.textContent || 1,
    );
    const cart = getCart();
    const newItem = normalizeCartItem({ ...product, qty: selectedQuantity });
    const existingItem = cart.find((item) => item.line_id === newItem.line_id);

    if (existingItem) {
      existingItem.qty += selectedQuantity;
    } else {
      cart.push(newItem);
    }

    saveCart(cart);
    showToast(`${product.name} added to review list`);
  });
});

document.querySelectorAll("[data-qty]").forEach((button) => {
  button.addEventListener("click", () => {
    const value = document.querySelector("[data-qty-value]");
    value.textContent = Math.max(
      1,
      Number(value.textContent) + Number(button.dataset.qty),
    );
  });
});

function changeCartQuantity(lineId, change) {
  const cart = getCart();
  const item = cart.find((entry) => entry.line_id === lineId);
  if (!item) return;

  item.qty = Math.max(1, item.qty + change);
  saveCart(cart);
  renderCart();
}

function removeCartItem(lineId) {
  selectedCartItems.delete(lineId);
  saveCart(getCart().filter((item) => item.line_id !== lineId));
  renderCart();
}

function updateBulkCartControls() {
  const selectedCount = selectedCartItems.size;
  const removeButton = document.querySelector("[data-remove-selected]");
  const countLabel = document.querySelector("[data-selected-count]");
  const selectAll = document.querySelector("[data-select-all]");
  const itemCheckboxes = [...document.querySelectorAll("[data-cart-select]")];
  const checkoutButton = document.getElementById("checkout");
  const reviewCount = document.querySelector("[data-review-selection-count]");

  if (removeButton) removeButton.disabled = selectedCount === 0;
  if (countLabel) {
    countLabel.textContent = selectedCount
      ? `${selectedCount} selected for review`
      : "Select products for review";
  }
  if (reviewCount) {
    reviewCount.textContent = `${selectedCount} product line${selectedCount === 1 ? "" : "s"}`;
  }
  if (checkoutButton) {
    checkoutButton.disabled = selectedCount === 0;
    checkoutButton.textContent = selectedCount
      ? `Submit ${selectedCount} for review →`
      : "Select products to continue";
  }
  if (selectAll) {
    selectAll.checked =
      itemCheckboxes.length > 0 && selectedCount === itemCheckboxes.length;
    selectAll.indeterminate =
      selectedCount > 0 && selectedCount < itemCheckboxes.length;
  }
  document.querySelectorAll("[data-cart-group-select]").forEach((groupSelect) => {
    const groupCheckboxes = itemCheckboxes.filter(
      (checkbox) => checkbox.dataset.cartGroup === groupSelect.dataset.cartGroupSelect,
    );
    const checkedCount = groupCheckboxes.filter(
      (checkbox) => checkbox.checked,
    ).length;
    groupSelect.checked =
      groupCheckboxes.length > 0 && checkedCount === groupCheckboxes.length;
    groupSelect.indeterminate =
      checkedCount > 0 && checkedCount < groupCheckboxes.length;
  });
}

function renderCart() {
  const itemsContainer = document.getElementById("cart-items");
  if (!itemsContainer) return;

  const cart = getCart();
  const currentIds = new Set(cart.map((item) => item.line_id));
  selectedCartItems.forEach((id) => {
    if (!currentIds.has(id)) selectedCartItems.delete(id);
  });
  const emptyState = document.getElementById("empty-cart");
  const cartLayout = document.querySelector(".cart-layout");
  const itemCount = cart.reduce((total, item) => total + item.qty, 0);
  document.querySelector("[data-cart-title]").textContent =
    `${itemCount} ${itemCount === 1 ? "item" : "items"}`;

  if (!cart.length) {
    cartLayout.style.display = "none";
    emptyState.style.display = "grid";
    return;
  }

  emptyState.style.display = "none";
  cartLayout.style.display = "grid";
  const bulkControls = `
    <div class="cart-bulk-actions">
      <label><input type="checkbox" data-select-all /> <span data-selected-count>Select products</span></label>
      <button type="button" data-remove-selected disabled>Remove selected</button>
    </div>`;
  const groups = new Map();
  cart.forEach((item) => {
    if (!groups.has(item.group_id)) {
      groups.set(item.group_id, {
        id: item.group_id,
        kind: item.group_kind,
        label: item.group_label,
        items: [],
      });
    }
    groups.get(item.group_id).items.push(item);
  });

  const renderItem = (item) => {
    const initials = escapeHtml(item.brand.slice(0, 2).toUpperCase());
    return `
        <article>
          <label class="cart-select" aria-label="Select ${escapeHtml(item.name)}">
            <input type="checkbox" data-cart-select="${escapeHtml(item.line_id)}" data-cart-group="${escapeHtml(item.group_id)}" ${selectedCartItems.has(item.line_id) ? "checked" : ""} />
          </label>
          <div class="cart-pic">${initials}</div>
          <div class="item-copy">
            <small>${escapeHtml(item.brand)} / ${escapeHtml(item.category)}</small>
            <h3>${escapeHtml(item.name)}</h3>
            <p>VTIC SKU VT-${String(item.id).padStart(4, "0")}</p>
            <button type="button" data-remove="${escapeHtml(item.line_id)}">Remove</button>
          </div>
          <div class="item-end">
            <b>For review</b>
            <div class="qty">
              <button type="button" data-line-id="${escapeHtml(item.line_id)}" data-quantity-change="-1" aria-label="Decrease quantity">−</button>
              <span>${item.qty}</span>
              <button type="button" data-line-id="${escapeHtml(item.line_id)}" data-quantity-change="1" aria-label="Increase quantity">+</button>
            </div>
          </div>
        </article>`;
  };

  itemsContainer.innerHTML =
    bulkControls +
    [...groups.values()]
      .map(
        (group) => `<section class="cart-group ${group.kind}">
          <header class="cart-group-header">
            <label class="cart-group-select"><input type="checkbox" data-cart-group-select="${escapeHtml(group.id)}" /><span><small>${group.kind === "solution" ? "ADVISOR PROPOSAL" : "MANUFACTURER"}</small><b>${escapeHtml(group.label)}</b></span></label>
            <small>${group.items.length} product line${group.items.length === 1 ? "" : "s"}</small>
          </header>
          <div class="cart-group-items">${group.items.map(renderItem).join("")}</div>
        </section>`,
      )
      .join("");

  document.querySelectorAll("[data-cart-select]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const lineId = checkbox.dataset.cartSelect;
      if (checkbox.checked) selectedCartItems.add(lineId);
      else selectedCartItems.delete(lineId);
      updateBulkCartControls();
    });
  });

  document.querySelectorAll("[data-cart-group-select]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      document.querySelectorAll("[data-cart-select]").forEach((itemCheckbox) => {
        if (itemCheckbox.dataset.cartGroup !== checkbox.dataset.cartGroupSelect) return;
        itemCheckbox.checked = checkbox.checked;
        const lineId = itemCheckbox.dataset.cartSelect;
        if (checkbox.checked) selectedCartItems.add(lineId);
        else selectedCartItems.delete(lineId);
      });
      updateBulkCartControls();
    });
  });

  document
    .querySelector("[data-select-all]")
    ?.addEventListener("change", (event) => {
      document.querySelectorAll("[data-cart-select]").forEach((checkbox) => {
        checkbox.checked = event.currentTarget.checked;
        const lineId = checkbox.dataset.cartSelect;
        if (checkbox.checked) selectedCartItems.add(lineId);
        else selectedCartItems.delete(lineId);
      });
      updateBulkCartControls();
    });

  document
    .querySelector("[data-remove-selected]")
    ?.addEventListener("click", () => {
      if (!selectedCartItems.size) return;
      saveCart(
        getCart().filter((item) => !selectedCartItems.has(item.line_id)),
      );
      selectedCartItems.clear();
      renderCart();
    });

  document.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () =>
      removeCartItem(button.dataset.remove),
    );
  });

  document.querySelectorAll("[data-quantity-change]").forEach((button) => {
    button.addEventListener("click", () => {
      changeCartQuantity(
        button.dataset.lineId,
        Number(button.dataset.quantityChange),
      );
    });
  });
  updateBulkCartControls();
}

document
  .getElementById("checkout")
  ?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const status = document.getElementById("review-status");
    const cart = getCart();
    const selectedCart = cart.filter((item) =>
      selectedCartItems.has(item.line_id),
    );
    if (!selectedCart.length) {
      status.textContent = "Select at least one product using its checkbox.";
      status.className = "error";
      return;
    }

    button.disabled = true;
    button.textContent = "Submitting…";
    status.textContent = "";
    try {
      const response = await fetch("/api/review-requests", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token":
            document.querySelector('meta[name="csrf-token"]')?.content || "",
        },
        body: JSON.stringify({
          items: selectedCart.map(({ id, qty }) => ({ id, qty })),
          ai_solution_option_ids: [
            ...new Set(
              selectedCart
                .map((item) => item.ai_solution_option_id)
                .filter(Boolean),
            ),
          ],
          notes: document.getElementById("review-notes")?.value || "",
        }),
      });
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        if (response.redirected && response.url.includes("/login")) {
          throw new Error("Please sign in with a customer account before submitting a review request.");
        }
        if (response.status === 403) {
          throw new Error("Review requests must be submitted from a customer account.");
        }
        if (response.status === 400) {
          throw new Error("Your session expired. Refresh the page and try again.");
        }
        throw new Error("The server returned an unexpected response. Please refresh and try again.");
      }
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Unable to submit request.");
      saveCart(
        cart.filter((item) => !selectedCartItems.has(item.line_id)),
      );
      selectedCartItems.clear();
      renderCart();
      status.textContent = `Request #${result.request_id} was submitted successfully. Unselected products remain in your review list.`;
      status.className = "success";
      window.setTimeout(() => {
        window.location.href = "/account/reviews";
      }, 900);
    } catch (error) {
      status.textContent = error.message;
      status.className = "error";
    } finally {
      updateBulkCartControls();
    }
  });

updateCartCount();
renderCart();
