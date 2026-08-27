(() => {
  const rows = [...document.querySelectorAll("[data-account-row]")];
  if (!rows.length) return;

  const search = document.querySelector("[data-account-search]");
  const type = document.querySelector("[data-account-type]");
  const status = document.querySelector("[data-account-status]");
  const sort = document.querySelector("[data-account-sort]");
  const count = document.querySelector("[data-visible-count]");
  const empty = document.querySelector("[data-empty-state]");
  const table = document.querySelector(".account-table");
  const groups = ["superadmin", "admin", "customer"];
  const groupHeadings = new Map(
    [...table.querySelectorAll("[data-account-group]")].map((item) => [
      item.dataset.accountGroup,
      item,
    ]),
  );

  const timestamp = (value) =>
    value ? new Date(`${value.replace(" ", "T")}Z`).getTime() : 0;

  const updateDirectory = () => {
    const query = search.value.trim().toLowerCase();
    const visible = rows.filter((row) => {
      const matchesSearch = !query || row.dataset.name.includes(query);
      const matchesType =
        type.value === "all" || row.dataset.type === type.value;
      const matchesStatus =
        status.value === "all" || row.dataset.status === status.value;
      const matches = matchesSearch && matchesType && matchesStatus;
      row.hidden = !matches;
      return matches;
    });

    const sorted = [...visible].sort((a, b) => {
      if (sort.value === "oldest")
        return timestamp(a.dataset.joined) - timestamp(b.dataset.joined);
      if (sort.value === "name")
        return a.dataset.name.localeCompare(b.dataset.name);
      if (sort.value === "activity")
        return timestamp(b.dataset.active) - timestamp(a.dataset.active);
      return timestamp(b.dataset.joined) - timestamp(a.dataset.joined);
    });

    const fragment = document.createDocumentFragment();
    groups.forEach((group) => {
      const heading = groupHeadings.get(group);
      const groupRows = sorted.filter((row) => row.dataset.group === group);
      heading.hidden = groupRows.length === 0;
      fragment.appendChild(heading);
      groupRows.forEach((row) => fragment.appendChild(row));
    });
    table.insertBefore(fragment, empty);
    count.textContent = String(visible.length);
    empty.hidden = visible.length !== 0;
  };

  [search, type, status, sort].forEach((control) => {
    control.addEventListener(
      control === search ? "input" : "change",
      updateDirectory,
    );
  });

  document
    .querySelector("[data-reset-filters]")
    .addEventListener("click", () => {
      search.value = "";
      type.value = "all";
      status.value = "all";
      sort.value = "newest";
      updateDirectory();
    });

  const statusControls = [...document.querySelectorAll(".status-control")];
  statusControls.forEach((control) => {
    const form = control.querySelector("[data-status-form]");
    const duration = form.querySelector("[data-restriction-duration]");
    const amount = form.elements.duration_amount;
    const unit = form.elements.duration_unit;
    const permanent = form.elements.duration_mode;
    const syncDuration = () => {
      const selectedStatus = form.elements.status.value;
      const restricted = selectedStatus !== "active";
      duration.hidden = !restricted;
      amount.disabled = !restricted || permanent.checked;
      unit.disabled = !restricted || permanent.checked;
    };

    form
      .querySelectorAll('[name="status"]')
      .forEach((radio) => radio.addEventListener("change", syncDuration));
    permanent.addEventListener("change", syncDuration);
    control
      .querySelector("[data-close-status]")
      .addEventListener("click", () => {
        control.open = false;
      });
    control.addEventListener("toggle", () => {
      if (!control.open) {
        if (!statusControls.some((item) => item.open)) {
          document.body.classList.remove("status-modal-open");
        }
        return;
      }
      statusControls.forEach((other) => {
        if (other !== control) other.open = false;
      });
      document.body.classList.add("status-modal-open");
      syncDuration();
    });
    form.addEventListener("submit", async (event) => {
      if (form.dataset.confirmed === "true") return;
      event.preventDefault();
      const nextStatus = form.elements.status.value;
      const account = form.dataset.accountLabel;
      let durationText = "";
      if (nextStatus !== "active") {
        durationText = permanent.checked
          ? " permanently"
          : ` for ${amount.value} ${unit.value}`;
      }
      const confirmed = await window.VTICConfirm.ask({
        title: "Change account status?",
        message: `Set ${account} to ${nextStatus}${durationText}? Access to the VTIC system may be affected immediately.`,
        confirmLabel: "Update status",
        tone: nextStatus === "active" ? "standard" : "danger",
      });
      if (!confirmed) return;
      form.dataset.confirmed = "true";
      form.requestSubmit(event.submitter || undefined);
    });
    syncDuration();
  });

  document.addEventListener("click", (event) => {
    statusControls.forEach((control) => {
      if (control.open && !control.contains(event.target)) control.open = false;
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      statusControls.forEach((control) => {
        control.open = false;
      });
    }
  });

  updateDirectory();
})();
