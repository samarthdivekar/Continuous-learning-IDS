// Sub-tabs inside one tab. Each section is an existing view module (mount/refresh/activate);
// it is mounted the first time it is shown, so opening a tab never loads panels nobody looks at.
import { $, $$, esc, prefs } from "./core.js";

export function subTabs(key, sections, { intro } = {}) {
  let root;
  const mounted = new Set();
  let current = sections[0].id;

  async function show(id) {
    const section = sections.find((s) => s.id === id) || sections[0];
    current = section.id;
    prefs.set(`sub.${key}`, current);
    $$(`#sub-nav-${key} button`, root).forEach((b) => b.classList.toggle("on", b.dataset.sub === current));
    $$(`.sub-panel`, root).forEach((p) => p.classList.toggle("on", p.id === `sub-${key}-${current}`));
    const host = $(`#sub-${key}-${current}`, root);
    if (!mounted.has(current)) {
      mounted.add(current);
      await section.mod.mount(host);
    } else if (section.mod.activate) {
      section.mod.activate();
    }
  }

  return {
    async mount(el) {
      root = el;
      root.innerHTML = `
        ${intro ? `<p class="view-intro">${esc(intro)}</p>` : ""}
        <div class="seg sub-nav" id="sub-nav-${key}" role="tablist">
          ${sections.map((s, i) => `<button data-sub="${s.id}" class="${i === 0 ? "on" : ""}">${esc(s.label)}</button>`).join("")}
        </div>
        ${sections.map((s, i) => `<section class="sub-panel ${i === 0 ? "on" : ""}" id="sub-${key}-${s.id}"></section>`).join("")}`;
      $$(`#sub-nav-${key} button`, root).forEach((b) => b.addEventListener("click", () => show(b.dataset.sub)));
      await show(prefs.get(`sub.${key}`, sections[0].id));
    },
    refresh() {
      sections.filter((s) => mounted.has(s.id)).forEach((s) => s.mod.refresh && s.mod.refresh());
    },
    activate() {
      const section = sections.find((s) => s.id === current);
      if (section?.mod.activate) section.mod.activate();
    },
  };
}
