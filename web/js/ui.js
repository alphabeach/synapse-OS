// ui.js -- the only module every view imports.
// DOM building, escaping, formatting, tables, badges and modal forms live here
// so a view never needs a second helper module.

export const RANK = { viewer: 0, member: 1, admin: 2 };

export function rank(role) {
  return RANK[role] ?? -1;
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

// Views build DOM nodes, so no innerHTML path exists today. Kept centralised for
// any future templating that must interpolate text into markup.
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
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

export function badge(text, kind = "neutral") {
  return el("span", { class: `badge ${kind}` }, text);
}

export function table(headers, rows) {
  const head = el("tr", {}, ...headers.map((h) => el("th", {}, h)));
  const body = el("tbody");
  for (const row of rows) {
    body.append(el("tr", {}, ...row.map((cell) => el("td", {}, cell))));
  }
  return el("table", { class: "tbl" }, el("thead", {}, head), body);
}

export function field(label, input) {
  return el("label", { class: "field" }, el("span", {}, label), input);
}

// Native <dialog>: focus trapping and Escape come from the platform.
export function formDialog({ title, fields, submitLabel = "Save", onSubmit }) {
  const dialog = el("dialog", { class: "modal" });
  const form = el("form", { method: "dialog", class: "modal-form" });
  form.append(el("h2", {}, title));

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
    form.append(field(f.label, input));
  }

  const error = el("p", { class: "error", role: "alert" });
  form.append(error, el("div", { class: "modal-actions" },
    el("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
    el("button", { class: "btn primary", type: "submit" }, submitLabel)));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = {};
    for (const f of fields) {
      const input = inputs[f.name];
      values[f.name] = f.type === "checkbox" ? input.checked : input.value;
    }
    try {
      await onSubmit(values);
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
    }
  });

  dialog.append(form);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}
