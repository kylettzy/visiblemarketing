const CART_KEY = "vtic-procurement-cart";

const getCart = () => {
  try {
    return JSON.parse(localStorage.getItem(CART_KEY) || "[]");
  } catch {
    return [];
  }
};

const saveCart = (cart) => {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
  updateCartCount();
};

const formatCurrency = (value) =>
  new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency: "PHP",
    minimumFractionDigits: 2,
  }).format(value);

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

function showToast(message = "Added to cart") {
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
    const existingItem = cart.find((item) => item.id === product.id);

    if (existingItem) {
      existingItem.qty += selectedQuantity;
    } else {
      cart.push({ ...product, qty: selectedQuantity });
    }

    saveCart(cart);
    showToast(`${product.name} added to cart`);
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

function changeCartQuantity(productId, change) {
  const cart = getCart();
  const item = cart.find((entry) => entry.id === productId);
  if (!item) return;

  item.qty = Math.max(1, item.qty + change);
  saveCart(cart);
  renderCart();
}

function removeCartItem(productId) {
  saveCart(getCart().filter((item) => item.id !== productId));
  renderCart();
}

function renderCart() {
  const itemsContainer = document.getElementById("cart-items");
  if (!itemsContainer) return;

  const cart = getCart();
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
  itemsContainer.innerHTML = cart
    .map((item) => {
      const initials = escapeHtml(item.brand.slice(0, 2).toUpperCase());
      return `
        <article>
          <div class="cart-pic">${initials}</div>
          <div class="item-copy">
            <small>${escapeHtml(item.brand)} / ${escapeHtml(item.category)}</small>
            <h3>${escapeHtml(item.name)}</h3>
            <p>VTIC SKU VT-${String(item.id).padStart(4, "0")}</p>
            <button type="button" data-remove="${item.id}">Remove</button>
          </div>
          <div class="item-end">
            <b>${formatCurrency(item.price * item.qty)}</b>
            <div class="qty">
              <button type="button" data-change="${item.id},-1" aria-label="Decrease quantity">−</button>
              <span>${item.qty}</span>
              <button type="button" data-change="${item.id},1" aria-label="Increase quantity">+</button>
            </div>
          </div>
        </article>`;
    })
    .join("");

  const subtotal = cart.reduce(
    (total, item) => total + item.price * item.qty,
    0,
  );
  document.querySelector("[data-subtotal]").textContent =
    formatCurrency(subtotal);
  document.querySelector("[data-total]").textContent = formatCurrency(subtotal);

  document.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () =>
      removeCartItem(Number(button.dataset.remove)),
    );
  });

  document.querySelectorAll("[data-change]").forEach((button) => {
    button.addEventListener("click", () => {
      const [productId, change] = button.dataset.change.split(",").map(Number);
      changeCartQuantity(productId, change);
    });
  });
}

document.getElementById("checkout")?.addEventListener("click", () => {
  window.location.href =
    "mailto:sales@vtic.com.ph?subject=Procurement cart review request";
});

updateCartCount();
renderCart();
