// inventory.js -- items, guarded consume, lot-captured restock, optimistic recount.
import { el, badge, table, formDialog } from "./ui.js";

export const view = { id: "inventory", label: "Inventory", minRole: "viewer" };

const CATEGORIES = ["antibody", "reagent", "media", "chemical", "consumable", "other"];

export async function render(root, ctx) {
  const search = el("input", {
    type: "search", placeholder: "Search items…", "aria-label": "Search items",
  });
  const toolbar = el("div", { class: "toolbar" }, search);
  if (ctx.can("admin")) {
    toolbar.append(el("button", {
      class: "btn primary", type: "button",
      onclick: () => newItemDialog(ctx, load),
    }, "New item"));
  }

  const host = el("div");
  const note = el("p", { class: "muted sm" },
    "Quantities are the authoritative total. Consumption is atomic and drains lots earliest-expiry-first.");
  root.append(toolbar, note, host);

  let query = "";
  let timer = null;
  search.addEventListener("input", () => {
    query = search.value.trim();
    clearTimeout(timer);
    timer = setTimeout(load, 250);
  });

  async function load() {
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    const items = await ctx.api.get(`/api/items${suffix}`);
    host.replaceChildren(items.length ? renderTable(items) : el("p", { class: "muted" }, "No items match."));
  }

  function renderTable(items) {
    return table(
      ["Item", "Category", "On hand / reorder", "Status", "Lots", ""],
      items.map((item) => [
        item.name,
        item.category,
        `${item.quantity_on_hand} / ${item.reorder_level}`,
        item.low ? badge("LOW", "warn") : badge("OK", "ok"),
        item.status === "deprecated" ? badge("deprecated", "muted") : "",
        actions(item),
      ]),
    );
  }

  function actions(item) {
    const box = el("div", { class: "row-actions" });
    if (ctx.can("member")) {
      box.append(
        el("button", { class: "btn sm", type: "button",
          onclick: () => consumeDialog(item, ctx, load) }, "Consume"),
        el("button", { class: "btn sm", type: "button",
          onclick: () => restockDialog(item, ctx, load) }, "Restock"),
        el("button", { class: "btn sm", type: "button",
          onclick: () => recountDialog(item, ctx, load) }, "Recount"),
      );
    }
    if (ctx.can("admin")) {
      box.append(el("button", {
        class: "btn sm ghost", type: "button",
        onclick: async () => {
          const status = item.status === "active" ? "deprecated" : "active";
          await ctx.api.patch(`/api/items/${item.id}`, { status });
          ctx.toast(`${item.name} → ${status}`);
          await load();
        },
      }, item.status === "active" ? "Deprecate" : "Reactivate"));
    }
    return box;
  }

  await load();
}

function consumeDialog(item, ctx, reload) {
  formDialog({
    title: `Consume — ${item.name}`,
    fields: [
      { name: "quantity", label: "Quantity", type: "number", min: 1, value: 1, required: true },
      { name: "note", label: "Note (optional)", placeholder: "e.g. passage 4 staining" },
    ],
    submitLabel: "Consume",
    onSubmit: async (v) => {
      await ctx.api.post(`/api/items/${item.id}/consume`, {
        quantity: Number(v.quantity),
        note: v.note || null,
      });
      ctx.toast(`Consumed ${v.quantity} × ${item.name}`);
      await reload();
    },
  });
}

function restockDialog(item, ctx, reload) {
  formDialog({
    title: `Restock — ${item.name}`,
    fields: [
      { name: "quantity", label: "Quantity", type: "number", min: 1, value: 1, required: true },
      { name: "lot_number", label: "Vendor lot number", required: true },
      { name: "expiry_date", label: "Expiry date", type: "date", required: true },
      { name: "location", label: "BGC storage location", value: "BGC -20C Freezer F1 / Box 1", required: true },
      { name: "cold_chain_ok", label: "Cold chain intact", type: "checkbox", value: true },
    ],
    submitLabel: "Restock",
    onSubmit: async (v) => {
      await ctx.api.post(`/api/items/${item.id}/restock`, {
        quantity: Number(v.quantity),
        lot_number: v.lot_number,
        expiry_date: v.expiry_date,
        location: v.location,
        cold_chain_ok: Boolean(v.cold_chain_ok),
      });
      ctx.toast(`Restocked ${v.quantity} × ${item.name}`);
      await reload();
    },
  });
}

function recountDialog(item, ctx, reload) {
  formDialog({
    title: `Recount — ${item.name}`,
    fields: [
      { name: "quantity", label: `Counted quantity (system shows ${item.quantity_on_hand})`,
        type: "number", min: 0, value: item.quantity_on_hand, required: true },
      { name: "reason", label: "Reason", placeholder: "e.g. physical count, breakage" },
    ],
    submitLabel: "Apply recount",
    onSubmit: async (v) => {
      await ctx.api.post(`/api/items/${item.id}/recount`, {
        expected_quantity: item.quantity_on_hand,
        quantity: Number(v.quantity),
        reason: v.reason || null,
      });
      ctx.toast(`${item.name} recounted to ${v.quantity}`);
      await reload();
    },
  });
}

function newItemDialog(ctx, reload) {
  formDialog({
    title: "New item",
    fields: [
      { name: "name", label: "Name", required: true },
      { name: "category", label: "Category", type: "select", value: "reagent",
        options: CATEGORIES.map((c) => ({ value: c, label: c })) },
      { name: "unit", label: "Unit", value: "vial" },
      { name: "quantity_on_hand", label: "Opening quantity", type: "number", min: 0, value: 0 },
      { name: "daily_burn_rate", label: "Daily burn rate", type: "number", min: 0, step: "0.01", value: 0 },
      { name: "safety_stock", label: "Safety stock", type: "number", min: 0, value: 0 },
      { name: "lead_time_days", label: "Supplier lead time (days)", type: "number", min: 0, value: 7 },
      { name: "unit_cost_php", label: "Unit cost (PHP)", type: "number", min: 0, step: "0.01", value: 0 },
    ],
    submitLabel: "Create item",
    onSubmit: async (v) => {
      await ctx.api.post("/api/items", {
        name: v.name,
        category: v.category,
        unit: v.unit,
        quantity_on_hand: Number(v.quantity_on_hand),
        daily_burn_rate: Number(v.daily_burn_rate),
        safety_stock: Number(v.safety_stock),
        lead_time_days: Number(v.lead_time_days),
        unit_cost_php: Number(v.unit_cost_php),
      });
      ctx.toast(`Created ${v.name}`);
      await reload();
    },
  });
}
