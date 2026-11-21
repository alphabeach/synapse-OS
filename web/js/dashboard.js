// dashboard.js -- command centre: counters + Attention Needed, one endpoint.
import { el, php, fmtDate } from "./ui.js";

export const view = { id: "dashboard", label: "Command", minRole: "viewer" };

export async function render(root, ctx) {
  const data = await ctx.api.get("/api/dashboard");
  const c = data.counts;

  root.append(
    el("div", { class: "stat-grid" },
      stat("Active items", c.active_items),
      stat("Low stock", c.low_stock, c.low_stock > 0),
      stat("Expiring ≤ 30d", c.expiring, c.expiring > 0),
      stat("Chase required", c.chase, c.chase > 0),
      stat("Open POs", c.open_pos),
      stat("Spend (received)", php(c.spend_php))),
  );

  const total = data.low_stock.length + data.expiring.length + data.chase.length;
  root.append(el(
    "div",
    { class: `banner ${total ? "warn" : "ok"}`, role: "status" },
    total
      ? `Attention needed: ${data.low_stock.length} low stock · ${data.expiring.length} expiring · ${data.chase.length} shipments to chase`
      : "All clear — no stock or customs alerts.",
  ));

  root.append(
    el("div", { class: "panels" },
      panel("Reorder now", data.low_stock.map((a) => el("li", {},
        `${a.item} — ${a.quantity} ${a.unit} on hand, reorder at ${a.reorder_level}`))),
      panel("Expiring within 30 days", data.expiring.map((a) => el("li", {},
        `${a.item} — lot ${a.lot_number}, ${a.quantity} left, expires ${fmtDate(a.expiry_date)}`))),
      panel("Customs chase (48h silent)", data.chase.map((a) => el("li", {},
        `PO #${a.id} ${a.item} — ${a.supplier_name}, ${a.hours_since}h silent (${a.status})`))),
    ),
  );
}

function stat(label, value, alert = false) {
  return el("div", { class: `stat${alert ? " alert" : ""}` },
    el("span", { class: "stat-label" }, label),
    el("span", { class: "stat-value" }, String(value)));
}

function panel(title, items) {
  return el("section", { class: "panel" },
    el("h2", {}, title),
    items.length
      ? el("ul", { class: "list" }, ...items)
      : el("p", { class: "muted" }, "Nothing here."));
}
