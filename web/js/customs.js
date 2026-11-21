// customs.js -- BOC stages, permit/doc readiness, 48h watchdog, lot-captured receiving.
import { el, badge, formDialog, php } from "./ui.js";

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

const DOCS = [
  ["doc_invoice", "Commercial invoice"],
  ["doc_packing", "Packing list"],
  ["doc_awb", "AWB"],
  ["doc_coa_msds", "CoA & MSDS"],
];

const DISCREPANCIES = [
  ["NONE", "None — receive normally"],
  ["short_shipped", "Short shipped"],
  ["damaged_cold_chain", "Cold chain broken"],
  ["wrong_spec", "Wrong specification"],
];

export async function render(root, ctx) {
  const host = el("div");
  root.append(
    el("p", { class: "muted sm" },
      "A red badge means the broker/supplier has been silent for over 48 hours. " +
      "Receiving mints a lot and requires the vendor lot number, expiry, cold-chain status and storage location."),
    host,
  );

  async function load() {
    const orders = await ctx.api.get("/api/purchase-orders");
    host.replaceChildren(...orders.map((po) => card(po)));
  }

  function card(po) {
    const editable = ctx.can("member");
    const closed = po.status === "received" || po.status === "cancelled";
    const extras = closed || po.status === "discrepancy_hold" ? [po.status] : [];
    const statusOptions = [...STAGES, ...extras.map((s) => [s, s.replace("_", " ")])];

    const stageSelect = el("select", {
      "aria-label": `Stage for PO ${po.id}`,
      disabled: closed || !editable ? "" : null,
    }, ...statusOptions.map(([value, label]) => el("option", {
      value, selected: value === po.status ? "" : null,
    }, label)));

    const docBoxes = DOCS.map(([key, label]) => {
      const box = el("input", { type: "checkbox", disabled: !editable || closed ? "" : null });
      box.checked = Boolean(po[key]);
      return el("label", { class: "check" }, box, label);
    });

    const permitSelect = el("select", {
      "aria-label": "Permit type", disabled: !editable || closed ? "" : null,
    }, ...["NONE", "FDA", "PDEA", "DENR"].map((p) => el("option", {
      value: p, selected: p === po.permit_type ? "" : null,
    }, `Permit: ${p}`)));
    const permitOk = el("input", { type: "checkbox", disabled: !editable || closed ? "" : null });
    permitOk.checked = Boolean(po.permit_ok);

    const save = el("button", {
      class: "btn sm primary", type: "button",
      onclick: async () => {
        const body = { permit_type: permitSelect.value, permit_ok: permitOk.checked };
        DOCS.forEach(([key], index) => { body[key] = docBoxes[index].querySelector("input").checked; });
        if (!closed) body.status = stageSelect.value;
        await ctx.api.patch(`/api/purchase-orders/${po.id}`, body);
        ctx.toast(`PO #${po.id} updated`);
        await load();
      },
    }, "Save");

    return el("article", { class: "card" },
      el("div", { class: "card-head" },
        el("div", {},
          el("h2", {}, `PO #${po.id} · ${po.item}`),
          el("p", { class: "muted" },
            `${po.supplier_name} · ${po.quantity} ${po.unit} · ${php(po.landed_cost_php)} landed · ${po.hours_since}h since follow-up`)),
        el("div", { class: "card-badges" },
          badge(STAGE_LABEL[po.status] || po.status, po.status === "received" ? "ok" : "stage"),
          po.chase_required ? badge(`Chase required — ${po.hours_since}h`, "danger") : null)),
      el("div", { class: "grid-2" },
        el("div", {},
          el("h3", {}, "Clearance"),
          el("div", { class: "inline" }, stageSelect, save),
          el("div", { class: "inline wrap" }, permitSelect,
            el("label", { class: "check" }, permitOk, "Permit secured"))),
        el("div", {},
          el("h3", {}, "Import documents"),
          el("div", { class: "checks" }, ...docBoxes),
          el("p", { class: "muted sm" }, `${po.docs_ready}/${po.docs_total} documents on file`))),
      el("div", { class: "card-actions" },
        editable && !closed
          ? el("button", {
              class: "btn sm", type: "button",
              onclick: async () => {
                await ctx.api.post(`/api/purchase-orders/${po.id}/followup`);
                ctx.toast(`Follow-up logged for PO #${po.id}`);
                await load();
              },
            }, "Log follow-up")
          : null,
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
          { name: "location", label: "BGC storage location", value: "BGC -20C Freezer F1 / Box 1" },
          { name: "cold_chain_ok", label: "Cold chain intact on arrival", type: "checkbox", value: true },
          { name: "discrepancy", label: "Or open a discrepancy hold", type: "select",
            value: "NONE", options: DISCREPANCIES.map(([value, label]) => ({ value, label })) },
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
