// inventory.js -- dense item grid, guarded consume, lot-captured restock,
// optimistic recount, and the shared lot inspector on row click.
import {
  el, badge, table, formDialog, runAction, num, tempTag, icon, openLotInspector,
} from "./ui.js";

export const view = { id: "inventory", label: "Inventory", minRole: "viewer" };

const CATEGORIES = ["antibody", "reagent", "media", "chemical", "consumable", "other"];

export async function render(root, ctx, params = {}) {
  const search = el("input", {
    type: "search", placeholder: "Search name…", "aria-label": "Search items",
  });
  const toolbar = el("div", { class: "toolbar" },
    el("span", { class: "eyebrow" }, "Item register"),
    search,
    el("span", { class: "toolbar-gap" }));
  if (ctx.can("admin")) {
    toolbar.append(el("button", {
      class: "btn primary", type: "button",
      onclick: () => newItemDialog(ctx, load),
    }, icon("plus"), "New item"));
  }

  const host = el("div");
  root.append(toolbar, host);

  let query = "";
  let timer = null;
  // Monotonic guard: a slow earlier search must never paint over a newer one.
  let seq = 0;

  search.addEventListener("input", () => {
    query = search.value.trim();
    clearTimeout(timer);
    timer = setTimeout(load, 250);
  });

  async function load() {
    const mine = ++seq;
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    let items;
    try {
      items = await ctx.api.get(`/api/items${suffix}`);
    } catch (err) {
      if (mine === seq) {
        host.replaceChildren(el("p", { class: "error" }, err.message));
        ctx.toast(err.message, "error");
      }
      return null;
    }
    if (mine !== seq) return null;
    host.replaceChildren(items.length
      ? renderTable(items)
      : el("p", { class: "muted" }, "No items match."));
    return items;
  }

  function renderTable(items) {
    return table(
      ["SKU", "Item", "Storage", "On hand", "Reorder", "Runway", "Status", ""],
      items.map((item) => [
        el("span", { class: "mono sku" }, sku(item)),
        el("div", {},
          el("strong", {}, item.name),
          el("span", { class: "muted sm" }, ` · ${item.unit}`)),
        tempTag(item.storage_location),
        num(item.quantity_on_hand),
        num(item.reorder_level),
        runway(item),
        item.low ? badge("LOW", "warn") : badge("OK", "ok"),
        actions(item),
      ]),
      {
        numeric: [3, 4, 5],
        onRowClick: (index) => openLotInspector(items[index], ctx),
      },
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
        el("button", { class: "btn sm ghost", type: "button",
          onclick: () => recountDialog(item, ctx, load) }, "Recount"),
      );
    }
    if (ctx.can("admin")) {
      const toggle = el("button", {
        class: "btn sm ghost", type: "button",
      }, item.status === "active" ? "Deprecate" : "Reactivate");
      toggle.addEventListener("click", () => runAction(toggle, ctx, async () => {
        const status = item.status === "active" ? "deprecated" : "active";
        await ctx.api.patch(`/api/items/${item.id}`, { status });
        ctx.toast(`${item.name} → ${status}`);
        await load();
      }));
      box.append(toggle);
    }
    return box;
  }

  const items = await load();
  if (params.itemId && items) {
    const item = items.find((i) => i.id === Number(params.itemId));
    if (item) openLotInspector(item, ctx, params.lotId);
  }
}

function sku(item) {
  const cat = String(item.category || "oth").slice(0, 3).toUpperCase();
  return `LAB-${cat}-${String(item.id).padStart(4, "0")}`;
}

// Days until the reorder point at the current burn; red when it lands inside
// the supplier lead time, so the order must go out now.
function runway(item) {
  const burn = Number(item.daily_burn_rate) || 0;
  if (!burn) return el("span", { class: "muted" }, "—");
  const days = Math.floor(
    (Number(item.quantity_on_hand) - Number(item.reorder_level)) / burn);
  if (days <= 0) {
    return el("span", { class: "mono danger", title: "at or below reorder point" }, "NOW");
  }
  const tone = days <= item.lead_time_days ? "danger"
    : days <= item.lead_time_days + 14 ? "warn" : "";
  return el("span", { class: `mono ${tone}`, title: "days until reorder point" }, `${days}d`);
}

// --------------------------------------------------------------------------- //
// Dialogs
// --------------------------------------------------------------------------- //
function consumeDialog(item, ctx, reload) {
  formDialog({
    title: `Consume — ${item.name}`,
    fields: [
      { name: "quantity", label: "Quantity", type: "number", min: 1, value: 1, required: true },
      { name: "note", label: "Note (optional)", placeholder: "e.g. passage 4 staining", wide: true },
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
      { name: "location", label: "Storage location", value: "Lab -20C Freezer F1 / Box 1", required: true, wide: true },
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
      { name: "reason", label: "Reason", placeholder: "e.g. physical count, breakage", wide: true },
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
      { name: "name", label: "Name", required: true, wide: true },
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
