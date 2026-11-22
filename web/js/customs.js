// customs.js -- BOC stages, inline document checkboxes, 48h chase flag,
// and lot-captured receiving.
import { el, badge, formDialog, php, runAction } from "./ui.js";

export const view = { id: "customs", label: "Customs", minRole: "viewer" };

const STAGES = [
  ["po_placed", "PO placed"],
  ["shipped_awb", "Shipped (AWB)"],
  ["pre_arrival_docs", "Pre-arrival docs"],
  ["at_boc_filing", "At BOC filing"],
  ["permit_clearance", "Permit clearance"],
  ["duties_assessed", "Duties assessed"],
  ["released_in_transit", "Released / in transit"],
];
const STAGE_LABEL = Object.fromEntries(STAGES);

// Six-node clearance rail. Pre-arrival docs share the AWB node.
const STEPS = [
  ["po_placed", "PO"],
  ["shipped_awb", "AWB"],
  ["at_boc_filing", "BOC"],
  ["permit_clearance", "Permit"],
  ["duties_assessed", "Duty"],
  ["released_in_transit", "Released"],
];
const STEP_OF = {
  po_placed: 0, shipped_awb: 1, pre_arrival_docs: 1, at_boc_filing: 2,
  permit_clearance: 3, duties_assessed: 4, released_in_transit: 5, received: 6,
};

const DOCS = [
  ["doc_invoice", "INV"],
  ["doc_packing", "PL"],
  ["doc_awb", "AWB"],
  ["doc_coa_msds", "CoA"],
];

const DISCREPANCIES = [
  ["NONE", "None — receive normally"],
  ["short_shipped", "Short shipped"],
  ["damaged_cold_chain", "Cold chain broken"],
  ["wrong_spec", "Wrong specification"],
];

export async function render(root, ctx, params = {}) {
  const host = el("div");
  root.append(
    el("p", { class: "muted sm" },
      "A red >48h CHASE flag means the broker/supplier has been silent past the watchdog. " +
      "Document checkboxes save inline; stages advance one step at a time. Receiving mints a " +
      "lot and requires the vendor lot number, expiry, cold-chain status and storage location."),
    host,
  );

  async function load() {
    const orders = await ctx.api.get("/api/purchase-orders");
    host.replaceChildren(...orders.map((po) => card(po)));
    if (params.poId) {
      const target = host.querySelector(`[data-po-id="${params.poId}"]`);
      if (target) {
        target.classList.add("flash");
        target.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }

  function card(po) {
    const editable = ctx.can("member");
    const closed = po.status === "received" || po.status === "cancelled";
    const since = po.hours_since == null
      ? "no follow-up logged"
      : `${po.hours_since}h since follow-up`;

    const stageSelect = el("select", {
      "aria-label": `Stage for PO ${po.id}`,
      disabled: closed || !editable ? "" : null,
    }, ...stageChoices(po).map(([value, label]) => el("option", {
      value, selected: value === po.status ? "" : null,
    }, label)));

    const docs = Object.fromEntries(DOCS.map(([key]) => [key, Boolean(po[key])]));
    const docCount = el("span", { class: "mono" }, `${po.docs_ready}/${po.docs_total}`);

    const docChecks = DOCS.map(([key, label]) => {
      const box = el("input", { type: "checkbox", disabled: !editable || closed ? "" : null });
      box.checked = docs[key];
      box.addEventListener("change", () => runAction(box, ctx, async () => {
        const next = box.checked;
        try {
          await ctx.api.patch(`/api/purchase-orders/${po.id}`, { [key]: next });
        } catch (err) {
          box.checked = !next;  // the server is the source of truth
          throw err;
        }
        docs[key] = next;
        docCount.textContent = `${Object.values(docs).filter(Boolean).length}/${DOCS.length}`;
        ctx.toast(`PO #${po.id} ${label} ${next ? "on file" : "removed"}`);
      }));
      return el("label", { class: "doc-check" }, box, label);
    });

    const permitSelect = el("select", {
      "aria-label": "Permit type", disabled: !editable || closed ? "" : null,
    }, ...["NONE", "FDA", "PDEA", "DENR"].map((p) => el("option", {
      value: p, selected: p === po.permit_type ? "" : null,
    }, p === "NONE" ? "No permit" : p)));

    const permitOk = el("input", {
      type: "checkbox",
      disabled: !editable || closed || po.permit_type === "NONE" ? "" : null,
    });
    permitOk.checked = Boolean(po.permit_ok);
    permitOk.addEventListener("change", () => runAction(permitOk, ctx, async () => {
      const next = permitOk.checked;
      try {
        await ctx.api.patch(`/api/purchase-orders/${po.id}`, { permit_ok: next });
      } catch (err) {
        permitOk.checked = !next;
        throw err;
      }
      ctx.toast(`PO #${po.id} permit ${next ? "secured" : "pending"}`);
    }));
    permitSelect.addEventListener("change", () => {
      permitOk.disabled = !editable || closed || permitSelect.value === "NONE";
    });

    const save = el("button", { class: "btn sm primary", type: "button" }, "Save stage");
    save.addEventListener("click", () => runAction(save, ctx, async () => {
      const body = { permit_type: permitSelect.value };
      if (!closed) body.status = stageSelect.value;
      await ctx.api.patch(`/api/purchase-orders/${po.id}`, body);
      ctx.toast(`PO #${po.id} updated`);
      await load();
    }));

    const followup = el("button", { class: "btn sm", type: "button" }, "Log follow-up");
    followup.addEventListener("click", () => runAction(followup, ctx, async () => {
      await ctx.api.post(`/api/purchase-orders/${po.id}/followup`);
      ctx.toast(`Follow-up logged for PO #${po.id}`);
      await load();
    }));

    return el("article", { class: "card", "data-po-id": po.id },
      el("div", { class: "card-head" },
        el("div", {},
          el("span", { class: "eyebrow mono" }, `PO #${po.id}`),
          el("h2", {}, po.item),
          el("p", { class: "muted sm" },
            `${po.supplier_name} · ${po.quantity} ${po.unit} · `,
            el("span", { class: "mono" }, php(po.landed_cost_php)),
            ` landed · ${since}`)),
        el("div", { class: "card-badges" },
          badge(STAGE_LABEL[po.status] || String(po.status).replaceAll("_", " "),
            po.status === "received" ? "ok" : "stage"),
          po.chase_required
            ? el("span", {
                title: po.hours_since == null
                  ? "No follow-up logged" : `${po.hours_since}h since follow-up`,
              }, badge(">48h CHASE", "danger pulse"))
            : null)),
      stepbar(po),
      el("div", { class: "card-body" },
        el("div", { class: "doc-row" },
          el("span", { class: "eyebrow" }, "Docs"),
          ...docChecks,
          el("label", { class: "doc-check" }, permitOk, "PERMIT"),
          docCount),
        el("div", { class: "customs-controls" },
          el("div", { class: "inline" },
            el("span", { class: "eyebrow" }, "Stage"), stageSelect, save),
          el("div", { class: "inline" },
            el("span", { class: "eyebrow" }, "Permit"), permitSelect))),
      el("div", { class: "card-actions" },
        editable && !closed ? followup : null,
        editable && !closed ? receiveButton(po) : null),
    );
  }

  function receiveButton(po) {
    return el("button", {
      class: "btn sm primary", type: "button",
      onclick: () => formDialog({
        title: `Receive PO #${po.id} — ${po.item}`,
        fields: [
          { name: "lot_number", label: "Vendor lot number" },
          { name: "expiry_date", label: "Expiry date", type: "date" },
          { name: "location", label: "BGC storage location", value: "BGC -20C Freezer F1 / Box 1", wide: true },
          { name: "cold_chain_ok", label: "Cold chain intact on arrival", type: "checkbox", value: true },
          { name: "discrepancy", label: "Or open a discrepancy hold", type: "select",
            value: "NONE", options: DISCREPANCIES.map(([value, label]) => ({ value, label })), wide: true },
        ],
        submitLabel: "Receive",
        onSubmit: async (v) => {
          const body = v.discrepancy !== "NONE"
            ? { discrepancy: v.discrepancy }
            : {
                lot_number: v.lot_number,
                expiry_date: v.expiry_date,
                location: v.location,
                cold_chain_ok: Boolean(v.cold_chain_ok),
              };
          const res = await ctx.api.post(`/api/purchase-orders/${po.id}/receive`, body);
          ctx.toast(res.status === "received"
            ? `Received ${res.quantity} into lot ${v.lot_number}`
            : `Hold opened: ${v.discrepancy}`);
          await load();
        },
      }),
    }, "Receive");
  }

  await load();
}

function stageChoices(po) {
  if (po.status === "received" || po.status === "cancelled") {
    return [[po.status, String(po.status).replaceAll("_", " ")]];
  }
  if (po.status === "discrepancy_hold") {
    // A hold can be cleared into any stage; keep the hold visible as the current state.
    return [["discrepancy_hold", "Discrepancy hold"], ...STAGES];
  }
  const at = STAGES.findIndex(([value]) => value === po.status);
  return at < 0 ? STAGES : STAGES.slice(at, at + 2);
}

function stepbar(po) {
  const at = STEP_OF[po.status] ?? -1;
  return el("ol", { class: "stepbar", "aria-label": "Customs clearance progress" },
    ...STEPS.map(([, label], index) => {
      const done = at > index;
      const current = at === index;
      return el("li", {
        class: `step${done ? " done" : ""}${current ? " current" : ""}`,
        "aria-current": current ? "step" : null,
      },
        el("span", { class: "step-index", "aria-hidden": "true" }, done ? "✓" : String(index + 1)),
        el("span", { class: "step-label" }, label));
    }));
}
