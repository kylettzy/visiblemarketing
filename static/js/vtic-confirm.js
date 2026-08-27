(() => {
  let resolver = null;
  const dialog = document.createElement("dialog");
  dialog.className = "vtic-confirm";
  dialog.innerHTML = `
    <section class="vtic-confirm__header">
      <i class="vtic-confirm__mark" aria-hidden="true">!</i>
      <div class="vtic-confirm__copy"><span>VTIC CONFIRMATION</span><h2 data-vtic-confirm-title></h2></div>
      <button class="vtic-confirm__close" type="button" data-vtic-confirm-cancel aria-label="Close">×</button>
    </section>
    <p class="vtic-confirm__message" data-vtic-confirm-message></p>
    <p class="vtic-confirm__notice">Please confirm before continuing. Destructive changes may not be recoverable.</p>
    <footer class="vtic-confirm__actions"><button type="button" data-vtic-confirm-cancel>Cancel</button><button type="button" data-vtic-confirm-accept>Confirm</button></footer>`;

  const finish = (answer) => {
    if (dialog.open) dialog.close();
    const current = resolver;
    resolver = null;
    current?.(answer);
  };

  const ask = ({ title, message, confirmLabel = "Confirm", tone = "danger" }) =>
    new Promise((resolve) => {
      resolver = resolve;
      dialog.dataset.tone = tone;
      dialog.querySelector("[data-vtic-confirm-title]").textContent = title;
      dialog.querySelector("[data-vtic-confirm-message]").textContent = message;
      dialog.querySelector("[data-vtic-confirm-accept]").textContent = confirmLabel;
      dialog.showModal();
    });

  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(dialog));
  dialog.querySelectorAll("[data-vtic-confirm-cancel]").forEach((button) =>
    button.addEventListener("click", () => finish(false)),
  );
  dialog.querySelector("[data-vtic-confirm-accept]").addEventListener("click", () => finish(true));
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); finish(false); });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) finish(false); });

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-vtic-confirm], form[data-confirm-signout], form[onsubmit*='confirm(']");
    if (!form || form.dataset.confirmed === "true") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const signout = form.hasAttribute("data-confirm-signout");
    const legacyMessage = form.getAttribute("onsubmit")?.match(/confirm\(['\"](.+?)['\"]\)/)?.[1];
    const confirmed = await ask({
      title: form.dataset.confirmTitle || (signout ? "Sign out of VTIC?" : "Confirm this action?"),
      message: form.dataset.confirmMessage || legacyMessage || (signout ? "You will need to enter your account credentials to access the system again." : "Please verify that you want to continue."),
      confirmLabel: form.dataset.confirmLabel || (signout ? "Sign out" : "Confirm"),
      tone: form.dataset.confirmTone || (signout ? "standard" : "danger"),
    });
    if (!confirmed) return;
    form.dataset.confirmed = "true";
    form.removeAttribute("onsubmit");
    form.requestSubmit(event.submitter || undefined);
  }, true);

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-vtic-confirm-button]");
    if (!button) return;
    event.preventDefault();
    const confirmed = await ask({
      title: button.dataset.confirmTitle || "Confirm this action?",
      message: button.dataset.confirmMessage || "Please verify that you want to continue.",
      confirmLabel: button.dataset.confirmLabel || "Confirm",
      tone: button.dataset.confirmTone || "danger",
    });
    if (confirmed) button.closest("form")?.requestSubmit(button);
  }, true);

  window.VTICConfirm = { ask };
})();
