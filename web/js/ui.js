// ui.js -- the only module every view imports.
// DOM building, formatting, tables, tags, modal forms, the lot inspector and
// guarded actions live here so a view never needs a second helper module.

export const RANK = { viewer: 0, member: 1, admin: 2 };

export function rank(role) {
  return RANK[role] ?? -1;
}

// Lucide-style 16px line icons. Paths only, no external sprite or font.
const ICON_PATHS = {
  dashboard: ["M3 3h7v7H3z", "M14 3h7v4h-7z", "M14 10h7v11h-7z", "M3 14h7v7H3z"],
  package: ["M21 8l-9-5-9 5 9 5 9-5z", "M3 8v8l9 5 9-5V8", "M12 13v8"],
  scale: ["M12 3v18", "M5 7h14", "M7 7l-4 7h8L7 7z", "M17 7l-4 7h8l-4-7z"],
  ship: ["M3 18h18", "M5 18V9l7-4 7 4v9", "M9 18v-4h6v4"],
  search: ["M11 19a8 8 0 100-16 8 8 0 000 16z", "M21 21l-4.3-4.3"],
  plus: ["M12 5v14", "M5 12h14"],
  minus: ["M5 12h14"],
  refresh: ["M20 12a8 8 0 10-2.3 5.7", "M20 4v6h-6"],
  archive: ["M3 6h18", "M8 6V4h8v2", "M6 6l1 14h10l1-14", "M10 11v5", "M14 11v5"],
  x: ["M18 6L6 18", "M6 6l12 12"],
  "alert-triangle": ["M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z", "M12 9v4", "M12 17h.01"],
  "check-circle": ["M22 11.1V12a10 10 0 11-5.9-9.1", "M22 4L12 14l-3-3"],
  clock: ["M12 22a10 10 0 100-20 10 10 0 000 20z", "M12 6v6l4 2"],
  thermometer: ["M14 14.8V4a2 2 0 10-4 0v10.8a4 4 0 104 0z"],
  "arrow-right": ["M5 12h14", "M13 6l6 6-6 6"],
  "chevron-right": ["M9 18l6-6-6-6"],
  "file-check": ["M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", "M14 2v6h6", "M9 15l2 2 4-4"],
  truck: ["M1 3h15v13H1z", "M16 8h4l3 3v5h-7V8z", "M5.5 21a2.5 2.5 0 100-5 2.5 2.5 0 000 5z", "M18.5 21a2.5 2.5 0 100-5 2.5 2.5 0 000 5z"],
  save: ["M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z", "M17 21v-8H7v8", "M7 3v5h8"],
  inbox: ["M22 12h-6l-2 3h-4l-2-3H2", "M5.5 5.1L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.5-6.9A2 2 0 0016.8 4H7.2a2 2 0 00-1.7 1.1z"],
  snowflake: ["M12 2v20", "M4.2 6.5l15.6 9", "M19.8 6.5l-15.6 9"],
  flask: ["M9 3h6", "M10 3v6L4.5 19a2 2 0 001.7 3h11.6a2 2 0 001.7-3L14 9V3"],
  "map-pin": ["M21 10c0 7-9 12-9 12s-9-5-9-12a9 9 0 1118 0z", "M12 13a3 3 0 100-6 3 3 0 000 6z"],
};

export function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ICON_PATHS[name] || []) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (value !== null && value !== undefined && value !== false) {
      node.setAttribute(key, value === true ? "" : value);
    }
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function php(amount, decimals = 0) {
  return new Intl.NumberFormat("en-PH", {
    style: "currency", currency: "PHP",
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(Number(amount) || 0);
}

export function num(value, decimals = 0) {
  return new Intl.NumberFormat("en-PH", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(Number(value) || 0);
}

export function fmtDate(iso) {
  return iso ? String(iso).slice(0, 10) : "—";
}

// Rectangular LIMS status tag: 1px border, 3px radius, 6px status dot.
export function badge(text, kind = "neutral") {
  return el("span", { class: `badge ${kind}` },
    el("span", { class: "tag-dot", "aria-hidden": "true" }), text);
}

// Freezer/bench location -> storage temperature tag.
export function tempTag(location) {
  const text = String(location || "");
  let tag;
  if (/-80/i.test(text)) tag = badge("-80°C", "stage");
  else if (/-20/i.test(text)) tag = badge("-20°C", "stage");
  else if (/\b4\s*C|fridge/i.test(text)) tag = badge("4°C", "ok");
  else if (/RT|bench|cabinet|shelf/i.test(text)) tag = badge("RT", "muted");
  else tag = badge("—", "muted");
  tag.classList.add("mono");
  return tag;
}

export function daysUntil(iso) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const expiry = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Math.round((expiry - today) / 86400000);
}

function expiryTag(iso) {
  const days = daysUntil(iso);
  if (days < 0) return badge(`EXPIRED ${Math.abs(days)}d`, "danger");
  if (days === 0) return badge("EXPIRES TODAY", "danger");
  if (days <= 30) return badge(`${days}d LEFT`, "danger");
  if (days <= 90) return badge(`${days}d LEFT`, "warn");
  return badge(`${days}d LEFT`, "ok");
}

// One shared guard for inline buttons: no double-fire, and a failed API call
// becomes a visible toast instead of an unhandled rejection.
export async function runAction(btn, ctx, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  try {
    await fn();
  } catch (err) {
    ctx.toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.removeAttribute("aria-busy");
  }
}

// opts.numeric: column indexes right-aligned with tabular figures.
// opts.onRowClick(index): makes the whole row a keyboard-operable target.
export function table(headers, rows, opts = {}) {
  const numeric = new Set(opts.numeric || []);
  const head = el("tr", {}, ...headers.map((h, i) => (
    el("th", { class: numeric.has(i) ? "num" : null }, h)
  )));
  const body = el("tbody");

  rows.forEach((row, index) => {
    const tr = el("tr", { class: opts.onRowClick ? "clickable" : null });
    row.forEach((cell, i) => {
      tr.append(el("td", { class: numeric.has(i) ? "num" : null }, cell));
    });
    if (opts.onRowClick) {
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      const open = (event) => {
        // Row actions (Consume/Restock/...) must not also open the drawer.
        if (event.target.closest("button, a, input, select, label, textarea")) return;
        opts.onRowClick(index);
      };
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open(event);
        }
      });
    }
    body.append(tr);
  });

  return el("div", { class: "table-wrap" },
    el("table", { class: "tbl" }, el("thead", {}, head), body));
}

export function field(label, input, wide = false) {
  return el("label", { class: `field${wide ? " wide" : ""}` }, el("span", {}, label), input);
}

// Native <dialog>: focus trapping and Escape come from the platform.
export function formDialog({ title, fields, submitLabel = "Save", onSubmit }) {
  const dialog = el("dialog", { class: "modal" });
  const form = el("form", { method: "dialog", class: "modal-form" });
  const head = el("div", { class: "modal-head" },
    el("h2", {}, title),
    el("button", {
      class: "icon-btn", type: "button", "aria-label": "Close", title: "Close",
      onclick: () => dialog.close(),
    }, icon("x")));
  const body = el("div", { class: "modal-body" });

  const inputs = {};
  for (const f of fields) {
    let input;
    if (f.type === "select") {
      input = el("select", { name: f.name },
        ...(f.options || []).map((o) => el("option", {
          value: o.value,
          selected: String(o.value) === String(f.value ?? "") ? "" : null,
        }, o.label)));
    } else if (f.type === "checkbox") {
      input = el("input", { type: "checkbox", name: f.name });
      input.checked = Boolean(f.value);
    } else {
      input = el("input", {
        type: f.type || "text",
        name: f.name,
        value: f.value ?? "",
        step: f.step,
        min: f.min,
        placeholder: f.placeholder,
        required: f.required ? "" : null,
      });
    }
    inputs[f.name] = input;
    body.append(field(f.label, input, f.wide));
  }

  const submit = el("button", { class: "btn primary", type: "submit" }, submitLabel);
  const error = el("p", { class: "error", role: "alert" });
  const foot = el("div", { class: "modal-foot" }, error,
    el("div", { class: "modal-actions" },
      el("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
      submit));

  form.append(head, body, foot);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return;  // a double-click must not mint a second lot
    const values = {};
    for (const f of fields) {
      const input = inputs[f.name];
      values[f.name] = f.type === "checkbox" ? input.checked : input.value;
    }
    error.textContent = "";
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    try {
      await onSubmit(values);
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
    }
  });

  dialog.append(form);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Right-hand slide-over: one fetch per open, real lot rows, no stale cache.
export async function openLotInspector(item, ctx, focusLotId) {
  let detail;
  try {
    detail = await ctx.api.get(`/api/items/${item.id}`);
  } catch (err) {
    ctx.toast(err.message, "error");
    return;
  }

  const lots = (detail.lots || []).filter((lot) => lot.quantity > 0);
  const dialog = el("dialog", { class: "modal drawer", "aria-label": `${detail.name} lots` });
  const close = el("button", {
    class: "icon-btn", type: "button", "aria-label": "Close lot inspector", title: "Close",
    onclick: () => dialog.close(),
  }, icon("x"));

  const body = el("div", { class: "drawer-body" },
    el("div", { class: "drawer-summary" },
      badge(`${num(detail.quantity_on_hand)} ${detail.unit} on hand`, "stage"),
      tempTag(detail.storage_location),
      badge(`reorder ${detail.reorder_level}`, "muted"),
      detail.low ? badge("LOW STOCK", "warn") : null,
      detail.status === "deprecated" ? badge("DEPRECATED", "muted") : null),
    el("div", { class: "drawer-section-head" },
      el("h3", {}, "Active lots"),
      badge(String(lots.length), "muted")),
    lots.length
      ? el("div", { class: "lot-list" },
          ...lots.map((lot) => lotCard(lot, String(lot.id) === String(focusLotId))))
      : el("p", { class: "muted sm" }, "No active lots. Restock or receive a PO to mint one."));

  dialog.append(
    el("div", { class: "drawer-head" },
      el("div", {},
        el("span", { class: "eyebrow" }, "Lot inspector"),
        el("h2", {}, detail.name),
        el("p", { class: "muted sm" }, `${detail.category} · ${detail.unit}`)),
      close),
    body);

  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  document.body.append(dialog);
  dialog.showModal();

  if (focusLotId) {
    const target = dialog.querySelector(".lot-focus");
    if (target) target.scrollIntoView({ block: "center" });
  }
}

function lotCard(lot, focused) {
  return el("article", { class: `lot${focused ? " lot-focus" : ""}` },
    el("div", { class: "lot-head" },
      el("strong", { class: "mono" }, lot.lot_number),
      expiryTag(lot.expiry_date)),
    el("div", { class: "lot-meta" },
      el("span", { class: "mono" }, `${num(lot.quantity)} on hand`),
      lot.cold_chain_ok
        ? badge("COLD CHAIN OK", "ok")
        : badge("COLD CHAIN BROKEN", "danger"),
      el("span", { class: "muted sm" }, `received ${fmtDate(lot.received_date)}`)),
    el("p", { class: "lot-loc" }, lot.location));
}
