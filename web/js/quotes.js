// quotes.js -- PHP landed-cost matrix, Alibaba deal finder and sourcing decision bar.
import {
  el, badge, table, formDialog, php, num, icon, runAction,
} from "./ui.js";

export const view = { id: "quotes", label: "Quotes", minRole: "viewer" };

const TYPES = [
  { value: "local_ph", label: "Local PH distributor" },
  { value: "alibaba", label: "China — Alibaba" },
  { value: "wechat", label: "China — WeChat" },
  { value: "us_eu", label: "US / EU direct" },
];
const TYPE_LABEL = Object.fromEntries(TYPES.map((t) => [t.value, t.label]));

export async function render(root, ctx) {
  const items = await ctx.api.get("/api/items");
  if (!items.length) {
    root.append(el("p", { class: "muted" }, "No items yet — create one in Inventory."));
    return;
  }

  const select = el("select", { "aria-label": "Item" },
    ...items.map((item) => el("option", { value: item.id }, item.name)));

  const toolbar = el("div", { class: "toolbar" },
    el("span", { class: "eyebrow" }, "Sourcing bench"),
    select,
    el("span", { class: "toolbar-gap" }));
  if (ctx.can("member")) {
    toolbar.append(el("button", {
      class: "btn primary", type: "button",
      onclick: () => newQuoteDialog(Number(select.value), ctx, load),
    }, icon("plus"), "Add quote"));
  }

  const decision = el("div", { class: "decision" });
  const alibaba = el("section", { class: "panel sourcing" });
  const host = el("div");

  root.append(
    toolbar,
    el("p", { class: "muted sm" },
      "Landed cost = goods + freight + cold chain + BOC duties + 12% VAT, in PHP. " +
      "Lead time includes the BOC buffer. Green marks the cheapest landed unit."),
    decision,
    alibaba,
    host,
  );

  let seq = 0;

  async function load() {
    const mine = ++seq;
    host.replaceChildren(el("p", { class: "muted" }, "Loading quotes…"));
    let quotes;
    try {
      quotes = await ctx.api.get(`/api/quotes?item_id=${select.value}`);
    } catch (err) {
      if (mine === seq) {
        host.replaceChildren(el("p", { class: "error" }, err.message));
        ctx.toast(err.message, "error");
      }
      return;
    }
    if (mine !== seq) return;

    if (!quotes.length) {
      decision.replaceChildren(el("p", { class: "panel-empty" }, "No quotes to compare."));
      fillAlibaba([]);
      host.replaceChildren(el("p", { class: "muted" }, "No quotes for this item yet."));
      return;
    }

    // Rejected quotes must not set the price or lead-time benchmark.
    const live = quotes.filter((q) => q.status !== "rejected");
    const pool = live.length ? live : quotes;
    fillDecision(pool);
    fillAlibaba(quotes);
    host.replaceChildren(renderTable(quotes, pool));
  }

  function renderTable(quotes, pool) {
    const cheapest = Math.min(...pool.map(unitLanded));
    const cheapestTotal = Math.min(...pool.map((q) => q.landed_cost_php));
    const fastest = Math.min(...pool.map((q) => q.effective_lead_days));
    return table(
      ["Supplier", "Source", "MOQ", "Unit PHP", "UNIT LANDED", "LANDED PHP", "Lead", "Status", ""],
      quotes.map((q) => [
        el("strong", {}, q.supplier_name),
        TYPE_LABEL[q.supplier_type] || q.supplier_type,
        num(q.moq),
        q.currency === "PHP"
          ? el("span", { class: "mono" }, php(q.unit_price, 2))
          : el("span", { class: "mono" }, `$${num(q.unit_price, 2)}`),
        el("span", {
          class: `mono${q.status !== "rejected" && unitLanded(q) === cheapest ? " best" : ""}`,
        }, php(unitLanded(q), 2)),
        el("span", {
          class: q.status !== "rejected" && q.landed_cost_php === cheapestTotal
            ? "mono best" : "mono",
        }, php(q.landed_cost_php, 2)),
        el("span", {
          class: q.status !== "rejected" && q.effective_lead_days === fastest ? "mono best" : "mono",
        }, `${q.effective_lead_days}d`),
        statusBadge(q.status),
        awardCell(q),
      ]),
      { numeric: [2, 3, 4, 5, 6] },
    );
  }

  function fillDecision(pool) {
    const best = pool.reduce((a, b) => (unitLanded(a) <= unitLanded(b) ? a : b));
    const fast = pool.reduce((a, b) => (
      a.effective_lead_days <= b.effective_lead_days ? a : b));
    const imports = pool.filter((q) => q.supplier_type !== "local_ph")
      .sort((a, b) => a.landed_cost_php - b.landed_cost_php);
    const imp = imports[0];

    decision.replaceChildren(
      cell("Best unit cost", php(unitLanded(best), 2), badge(best.supplier_name, "stage")),
      cell("Fastest arrival", `${fast.effective_lead_days} days`, badge(fast.supplier_name, "muted")),
      cell("Break-even qty", breakEven(pool),
        el("span", { class: "muted sm" }, "vs cheapest local")),
      cell("PH import safety", imp ? "IMPORT" : "LOCAL",
        imp ? badge(`BOC ${Math.round(imp.duty_rate * 100)}% + VAT`, "warn")
          : badge("NO BOC", "ok")),
    );
  }

  function fillAlibaba(quotes) {
    const deals = quotes.filter((q) => q.supplier_type === "alibaba");
    alibaba.replaceChildren(
      el("div", { class: "panel-head" },
        icon("search"),
        el("h2", {}, "Find Alibaba Deals"),
        badge(`${deals.length} deal${deals.length === 1 ? "" : "s"}`,
          deals.length ? "stage" : "muted")),
      deals.length
        ? el("div", { class: "deal-list" }, ...deals.map(dealRow))
        : el("p", { class: "panel-empty" }, "No Alibaba quote for this item yet."),
    );
  }

  function dealRow(q) {
    const imported = q.status === "primary";
    const blocked = imported || q.status === "rejected";
    const btn = el("button", {
      class: `btn sm${imported ? "" : " primary"}`, type: "button",
      disabled: blocked ? "" : null,
      title: imported ? "Already imported as the primary PO" : "Award this deal and create the PO",
    }, imported ? "Imported" : q.status === "rejected" ? "Rejected" : "1-click import");
    if (!blocked) {
      btn.addEventListener("click", () => runAction(btn, ctx, async () => {
        const res = await ctx.api.post(`/api/quotes/${q.id}/award`, { quantity: q.moq });
        ctx.toast(`Imported ${q.supplier_name} → PO #${res.po_id}`);
        await load();
      }));
    }
    return el("div", { class: "deal" },
      el("div", { class: "deal-main" },
        el("strong", {}, q.supplier_name),
        el("span", { class: "muted sm" },
          `${q.currency === "PHP" ? php(q.unit_price, 2) : `$${num(q.unit_price, 2)}`} / unit · MOQ ${num(q.moq)}`)),
      el("div", { class: "deal-meta" },
        el("span", { class: "mono" }, `${php(unitLanded(q), 2)} landed/unit`),
        el("span", { class: "mono muted" }, `${q.effective_lead_days}d`),
        statusBadge(q.status)),
      btn);
  }

  function statusBadge(status) {
    if (status === "primary") return badge("PRIMARY", "ok");
    if (status === "backup") return badge("BACKUP", "warn");
    if (status === "rejected") return badge("REJECTED", "muted");
    return badge("DRAFT", "muted");
  }

  function awardCell(q) {
    if (!ctx.can("member") || q.status === "primary" || q.status === "rejected") {
      return el("span", { class: "muted sm" }, q.status === "primary" ? "awarded" : "");
    }
    return el("button", {
      class: "btn sm", type: "button",
      onclick: () => formDialog({
        title: `Award — ${q.supplier_name}`,
        fields: [{ name: "quantity", label: "Order quantity", type: "number", min: 1, value: q.moq, required: true, wide: true }],
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

// Landed cost per unit at the quote's own quantity.
function unitLanded(q) {
  return q.landed_cost_php / (q.landed_for_qty || q.moq || 1);
}

// Quantity where an import's per-unit saving repays its fixed freight/cold chain.
function breakEven(pool) {
  const imp = pool.filter((q) => q.supplier_type !== "local_ph")
    .sort((a, b) => a.unit_price_php - b.unit_price_php)[0];
  const loc = pool.filter((q) => q.supplier_type === "local_ph")
    .sort((a, b) => a.unit_price_php - b.unit_price_php)[0];
  if (!imp || !loc) return "—";
  const duty = 1 + Number(imp.duty_rate);
  const variable = imp.unit_price_php * duty * 1.12;
  const fixed = (Number(imp.shipping_php) + Number(imp.cold_chain_php)) * duty * 1.12;
  const saving = loc.unit_price_php - variable;
  if (saving <= 0) return "never";
  return `${num(Math.ceil(fixed / saving))} u`;
}

function cell(label, value, tag) {
  return el("div", { class: "decision-cell" },
    el("span", { class: "decision-label" }, label),
    el("strong", { class: "decision-value" }, value),
    tag);
}

function newQuoteDialog(itemId, ctx, reload) {
  formDialog({
    title: "New supplier quote",
    fields: [
      { name: "supplier_name", label: "Supplier", required: true, wide: true },
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
