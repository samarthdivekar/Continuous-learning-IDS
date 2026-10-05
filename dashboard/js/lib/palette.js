// Command palette (Ctrl/Cmd+K): one keyboard route to every tab and to the handful of
// actions an analyst repeats during a demo. Actions are supplied by the shell, so this
// module never reaches into a view directly.
import { $, $$, esc, h } from "./core.js";

let box = null;      // the palette element
let scrim = null;    // the backdrop behind it
let actions = [];    // every registered action
let shown = [];      // the actions matching the current query
let active = 0;

/** `list` is an array of { label, group, run, match? }. `label` may be a function of the query. */
export function setActions(list) {
  actions = list;
}

export const isOpen = () => box !== null;

export function close() {
  document.removeEventListener("keydown", onKey, true);
  box?.remove();
  scrim?.remove();
  box = scrim = null;
}

export function open() {
  if (box) { close(); return; }
  scrim = h('<div class="scrim"></div>');
  box = h(`<div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
    <input type="text" placeholder="Type a command… (tab name, dataset, incident number)" aria-label="Command"
           aria-controls="palette-list" autocomplete="off" spellcheck="false">
    <ul id="palette-list" role="listbox"></ul></div>`);
  scrim.addEventListener("click", close);
  document.body.append(scrim, box);
  const input = $("input", box);
  input.addEventListener("input", () => render(input.value));
  document.addEventListener("keydown", onKey, true);
  render("");
  input.focus();
}

function render(query) {
  const q = query.trim().toLowerCase();
  shown = actions
    .filter((a) => (a.match ? a.match(q) : haystack(a, q).includes(q)))
    .sort((x, y) => (y.priority || 0) - (x.priority || 0));
  active = 0;
  const list = $("#palette-list", box);
  list.innerHTML = shown.length
    ? shown.map((a, i) => `<li data-i="${i}" class="${i === 0 ? "on" : ""}" role="option" aria-selected="${i === 0}">
        <span>${esc(label(a, q))}</span><span class="group">${esc(a.group || "")}</span></li>`).join("")
    : `<li class="none" role="option" aria-selected="false">Nothing matches “${esc(query)}”</li>`;
  $$("li[data-i]", list).forEach((li) => {
    li.addEventListener("click", () => run(Number(li.dataset.i)));
    li.addEventListener("mousemove", () => highlight(Number(li.dataset.i)));
  });
}

const label = (a, q) => (typeof a.label === "function" ? a.label(q) : a.label);
// people search for the concept ("drift", "novelty"), not the tab's title
const haystack = (a, q) => `${label(a, q)} ${a.group || ""} ${(a.keywords || []).join(" ")}`.toLowerCase();

function highlight(i) {
  if (!shown.length) return;
  active = (i + shown.length) % shown.length;
  $$("#palette-list li[data-i]", box).forEach((li, k) => {
    li.classList.toggle("on", k === active);
    li.setAttribute("aria-selected", String(k === active));
  });
  $$("#palette-list li[data-i]", box)[active]?.scrollIntoView({ block: "nearest" });
}

function run(index) {
  const item = shown[index];
  if (!item) return;
  const query = $("input", box).value.trim();
  close();
  try {
    item.run(query);
  } catch (e) {
    console.error("command failed", e);
  }
}

function onKey(e) {
  if (!box) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  else if (e.key === "ArrowDown") { e.preventDefault(); highlight(active + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active - 1); }
  else if (e.key === "Enter") { e.preventDefault(); run(active); }
}
