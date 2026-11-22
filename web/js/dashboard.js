// dashboard.js -- command centre: 4-metric telemetry strip + clickable alerts.
import { el, icon, php, fmtDate } from "./ui.js";

export const view = { id: "dashboard", label: "Command", minRole: "viewer" };

export async function render(root, ctx) {
  const data = await ctx.api.get("/api/dashboard");
  const c = data.counts;
  const total = data.low_stock.length + data.expiring.length + data.chase.length;

  root.append(
    el("section", { class: "telemetry", "aria-label": "Lab telemetry" },
      metric("Active items", c.active_items, "inventory", "flask",
        () => ctx.navigate("inventory")),
      metric("Low stock", c.low_stock, "inventory", "package",
        () => ctx.navigate("inventory"), c.low_stock > 0),
      metric("Expiring ≤ 30d", c.expiring, "inventory", "clock",
        () => ctx.navigate("inventory"), c.expiring > 0),
      metric("Chase > 48h", c.chase, "customs", "ship",
        () => ctx.navigate("customs"), c.chase > 0)),
    el("p", { class: "telemetry-meta mono" },
      `${c.open_pos} open POs · ${php(c.spend_php)} received spend · BGC Manila`),
    el("div", { class: `banner ${total ? "warn" : "ok"}`, role: "status" },
      icon(total ? "alert-triangle" : "check-circle"),
      el("span", {}, total
        ? `Attention: ${data.low_stock.length} low stock · ${data.expiring.length} expiring · ${data.chase.length} shipments silent > 48h`
        : "All clear — no stock or customs alerts.")),
    el("div", { class: "panels" },
      panel("Reorder now", "package", data.low_stock.map((a) => ({
        text: `${a.item} — ${a.quantity} ${a.unit} on hand, reorder at ${a.reorder_level}`,
        meta: `${a.reorder_level - a.quantity} units short`,
        go: () => ctx.navigate("inventory", { itemId: a.item_id }),
      })), "Stock is above every reorder point."),
      panel("Expiring within 30 days", "clock", data.expiring.map((a) => ({
        text: `${a.item} — lot ${a.lot_number}, ${a.quantity} left`,
        meta: `expires ${fmtDate(a.expiry_date)}`,
        go: () => ctx.navigate("inventory", { itemId: a.item_id, lotId: a.lot_id }),
      })), "No lots inside the 30-day window."),
      panel("Customs chase (> 48h silent)", "ship", data.chase.map((a) => ({
        text: `PO #${a.id} ${a.item} — ${a.supplier_name}`,
        meta: `${a.hours_since}h silent · ${String(a.status).replaceAll("_", " ")}`,
        go: () => ctx.navigate("customs", { poId: a.id }),
      })), "No shipment is overdue for a chase.")),
  );
}

function metric(label, value, viewId, iconName, go, alert = false) {
  return el("button", {
    class: `metric${alert ? " alert" : ""}`, type: "button", onclick: go,
    "aria-label": `${label}: ${value} — open ${viewId}`,
  },
    el("span", { class: "metric-icon" }, icon(iconName)),
    el("span", { class: "metric-label" }, label),
    el("strong", { class: "metric-value" }, String(value)));
}

function panel(title, iconName, items, emptyText) {
  return el("section", { class: "panel" },
    el("div", { class: "panel-head" },
      icon(iconName),
      el("h2", {}, title),
      el("span", { class: "panel-count mono" }, String(items.length))),
    items.length
      ? el("ul", { class: "list" }, ...items.map((item) => el("li", {},
          el("button", { class: "alert-row", type: "button", onclick: item.go },
            el("span", { class: "alert-text" }, item.text),
            el("span", { class: "alert-meta mono" }, item.meta),
            icon("chevron-right")))))
      : el("p", { class: "panel-empty" }, emptyText));
}
