// quotes.js -- PHP landed-cost matrix across local / China / US+EU suppliers.
import { el, badge, table, formDialog, php, num } from "./ui.js";

export const view = { id: "quotes", label: "Quotes", minRole: "viewer" };

const TYPES = [
  { value: "local_ph", label: "Local PH distributor" },
  { value: "alibaba", label: "China — Alibaba" },
  { value: "wechat", label: "China — WeChat" },
  { value: "us_eu", label: "US / EU direct" },
];

export async function render(root, ctx) {
  const items = await ctx.api.get("/api/items");
  const select = el("select", { "aria-label": "Item" },
    ...items.map((item) => el("option", { value: item.id }, item.name)));

  const toolbar = el("div", { class: "toolbar" }, select);
  if (ctx.can("member")) {
    toolbar.append(el("button", {
      class: "btn primary", type: "button",
      onclick: () => newQuoteDialog(Number(select.value), ctx, load),
    }, "Add quote"));
  }

  const host = el("div");
  root.append(
    toolbar,
    el("p", { class: "muted sm" },
      "Landed cost = goods + freight + cold chain + BOC duties + 12% VAT, in PHP. " +
      "Bench lead time includes the BOC buffer. Awarding marks the chosen quote primary and the cheapest rival backup."),
    host,
  );

  async function load() {
    const quotes = await ctx.api.get(`/api/quotes?item_id=${select.value}`);
    if (!quotes.length) {
      host.replaceChildren(el("p", { class: "muted" }, "No quotes for this item yet."));
      return;
    }
    const cheapest = Math.min(...quotes.map((q) => q.landed_cost_php));
    host.replaceChildren(table(
      ["Supplier", "Type", "Unit", "MOQ", "Unit (PHP)", "Freight", "Duty", "Landed PHP", "Lead", "Status", ""],
      quotes.map((q) => [
        q.supplier_name,
        q.supplier_type,
        q.currency === "PHP" ? php(q.unit_price) : `$${num(q.unit_price, 2)}`,
        q.moq,
        php(q.unit_price_php),
        php(q.shipping_php + q.cold_chain_php),
        `${Math.round(q.duty_rate * 100)}%`,
        el("strong", { class: q.landed_cost_php === cheapest ? "best" : "" }, php(q.landed_cost_php)),
        `${q.effective_lead_days}d`,
        statusBadge(q.status),
        awardCell(q),
      ]),
    ));
  }

  function statusBadge(status) {
    if (status === "primary") return badge("PRIMARY", "ok");
    if (status === "backup") return badge("backup", "warn");
    if (status === "rejected") return badge("rejected", "muted");
    return badge("draft", "muted");
  }

  function awardCell(q) {
    if (!ctx.can("member") || q.status === "primary" || q.status === "rejected") {
      return el("span", { class: "muted sm" }, q.status === "primary" ? "awarded" : "");
    }
    return el("button", {
      class: "btn sm", type: "button",
      onclick: () => formDialog({
        title: `Award — ${q.supplier_name}`,
        fields: [{ name: "quantity", label: "Order quantity", type: "number", min: 1, value: q.moq, required: true }],
        submitLabel: "Award → create PO",
        onSubmit: async (v) => {
          const res = await ctx.api.post(`/api/quotes/${q.id}/award`, { quantity: Number(v.quantity) });
          ctx.toast(`PO #${res.po_id} created for ${php(res.landed_cost_php)}`);
          await load();
        },
      }),
    }, "Award → PO");
  }

  select.addEventListener("change", load);
  await load();
}

function newQuoteDialog(itemId, ctx, reload) {
  formDialog({
    title: "New supplier quote",
    fields: [
      { name: "supplier_name", label: "Supplier", required: true },
      { name: "supplier_type", label: "Source", type: "select", value: "local_ph", options: TYPES },
      { name: "unit_price", label: "Unit price", type: "number", min: 0.01, step: "0.01", required: true },
      { name: "currency", label: "Currency", type: "select", value: "PHP",
        options: [{ value: "PHP", label: "PHP" }, { value: "USD", label: "USD" }] },
      { name: "fx_rate", label: "FX rate (PHP per USD, 1 for PHP)", type: "number", min: 0.01, step: "0.01", value: 58.5 },
      { name: "moq", label: "MOQ", type: "number", min: 1, value: 1, required: true },
      { name: "shipping_php", label: "Shipping (PHP)", type: "number", min: 0, step: "0.01", value: 0 },
      { name: "cold_chain_php", label: "Cold chain / dry ice (PHP)", type: "number", min: 0, step: "0.01", value: 0 },
      { name: "duty_rate", label: "Duty rate (0.05 = 5%)", type: "number", min: 0, step: "0.01", value: 0 },
      { name: "lead_time_days", label: "Supplier lead time (days)", type: "number", min: 0, value: 14 },
      { name: "boc_buffer_days", label: "BOC buffer (days)", type: "number", min: 0, value: 7 },
    ],
    submitLabel: "Add quote",
    onSubmit: async (v) => {
      await ctx.api.post("/api/quotes", {
        item_id: itemId,
        supplier_name: v.supplier_name,
        supplier_type: v.supplier_type,
        unit_price: Number(v.unit_price),
        currency: v.currency,
        fx_rate: Number(v.fx_rate),
        moq: Number(v.moq),
        shipping_php: Number(v.shipping_php),
        cold_chain_php: Number(v.cold_chain_php),
        duty_rate: Number(v.duty_rate),
        lead_time_days: Number(v.lead_time_days),
        boc_buffer_days: Number(v.boc_buffer_days),
      });
      ctx.toast(`Quote added for ${v.supplier_name}`);
      await reload();
    },
  });
}
