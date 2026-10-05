// Shared UI pieces that more than one view needs: loading skeletons, error states that
// match the API's status codes, a confirm dialog, sortable tables and KPI sparklines.
// No view should hand-roll these again.
import { $, $$, esc, h } from "./core.js";

/** Placeholder markup shown while a panel's data is in flight. */
export function skeleton(kind = "block", count = 1) {
  const one = { block: '<span class="skel block"></span>',
                kpi: '<span class="skel kpi"></span>',
                lines: '<span class="skel line"></span><span class="skel line medium"></span><span class="skel line short"></span>',
                table: '<span class="skel line"></span>'.repeat(6) }[kind] || '<span class="skel block"></span>';
  return `<div aria-busy="true" aria-live="polite">${one.repeat(count)}</div>`;
}

/**
 * Turn a failed request into the right message. The API's conventions are documented:
 * 404 not run yet / not found · 422 value out of range · 409 already decided or changed ·
 * 503 model service unavailable. Anything else is shown verbatim.
 */
export function errorState(err, { what = "this panel" } = {}) {
  const status = err?.status;
  const detail = err?.message ? `<span class="hint">${esc(err.message)}</span>` : "";
  const states = {
    404: ["Not run yet", `No results file for ${esc(what)} on this dataset. Run the experiment, then reload.`],
    422: ["Value out of range", "The request used a value the API does not accept. Change the selection and try again."],
    409: ["Already decided", "This incident changed or was decided elsewhere. Reload the queue to see the current state."],
    503: ["Model service unavailable", "The live model is not running. Overview, Models, Adaptation &amp; trust and Reproducibility still work from saved results."],
  };
  const [title, body] = states[status] || ["Could not load", `${esc(what)} could not be loaded.`];
  return `<div class="empty s${status || "x"}"><span class="title">${title}</span>${body}${detail}</div>`;
}

/** Render `errorState` straight into an element. */
export function showError(el, err, opts) {
  if (el) el.innerHTML = errorState(err, opts);
}

/**
 * Ask before something irreversible-looking. Resolves true/false.
 * `detail` is rendered as monospace (a firewall rule, a path).
 */
export function confirmDialog({ title, body, detail, confirmLabel = "Confirm", danger = false, tag }) {
  return new Promise((resolve) => {
    const scrim = h('<div class="scrim"></div>');
    const dialog = h(`<div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h3>${esc(title)} ${tag ? `<span class="tag dry">${esc(tag)}</span>` : ""}</h3>
      <p>${esc(body)}</p>
      ${detail ? `<pre>${esc(detail)}</pre>` : ""}
      <div class="dialog-foot">
        <button class="btn" data-x="no">Cancel</button>
        <button class="btn ${danger ? "danger" : "primary"}" data-x="yes">${esc(confirmLabel)}</button>
      </div></div>`);
    const close = (answer) => {
      document.removeEventListener("keydown", onKey);
      scrim.remove(); dialog.remove();
      resolve(answer);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
      if (e.key === "Enter") { e.preventDefault(); close(true); }
    };
    scrim.addEventListener("click", () => close(false));
    $$("[data-x]", dialog).forEach((b) => b.addEventListener("click", () => close(b.dataset.x === "yes")));
    document.addEventListener("keydown", onKey);
    document.body.append(scrim, dialog);
    $('[data-x="yes"]', dialog).focus();
  });
}

/**
 * Make a rendered `table.data` sortable by clicking its headers. Numeric columns sort
 * numerically (the text may carry separators or a % sign), everything else sorts as text.
 */
export function makeSortable(root, { skip = [] } = {}) {
  const tbl = root?.querySelector?.("table.data") || root;
  if (!tbl || tbl.dataset.sortable) return;
  tbl.dataset.sortable = "1";
  const headers = [...tbl.querySelectorAll("thead th")];
  const body = tbl.querySelector("tbody");
  const value = (row, i) => {
    const cell = row.children[i];
    const text = (cell?.textContent || "").trim();
    const num = Number(text.replace(/[,%\s]/g, "").replace(/[^\d.eE+-]/g, ""));
    return { text, num: Number.isFinite(num) && /\d/.test(text) ? num : null };
  };
  headers.forEach((th, i) => {
    if (skip.includes(i) || !th.textContent.trim()) return;
    th.classList.add("sortable");
    th.tabIndex = 0;
    th.setAttribute("role", "columnheader");
    const sort = () => {
      const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
      headers.forEach((o) => o.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", dir);
      const sign = dir === "ascending" ? 1 : -1;
      [...body.rows]
        .sort((a, b) => {
          const va = value(a, i), vb = value(b, i);
          if (va.num !== null && vb.num !== null) return sign * (va.num - vb.num);
          return sign * va.text.localeCompare(vb.text, undefined, { numeric: true });
        })
        .forEach((r) => body.appendChild(r));
    };
    th.addEventListener("click", sort);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
  });
}

/** Tiny inline trend line for a KPI tile. `values` is a plain number array. */
export function sparkline(values, { width = 160, height = 28 } = {}) {
  const pts = (values || []).filter((v) => Number.isFinite(v));
  if (pts.length < 2) return "";
  const min = Math.min(...pts), max = Math.max(...pts), span = max - min || 1;
  const x = (i) => (i / (pts.length - 1)) * width;
  const y = (v) => height - ((v - min) / span) * (height - 4) - 2;
  const line = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
    <path class="area" d="${area}"></path><path d="${line}"></path></svg>`;
}

/** Disable a button while its request is in flight, with a spinner, then restore it. */
export async function withBusy(btn, fn) {
  if (!btn) return fn();
  const wasDisabled = btn.disabled;
  btn.disabled = true;
  btn.classList.add("busy");
  try {
    return await fn();
  } finally {
    btn.classList.remove("busy");
    btn.disabled = wasDisabled;
  }
}
