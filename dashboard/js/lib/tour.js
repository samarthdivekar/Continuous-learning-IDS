// A short guided walk through the console: five steps, each one switching to a tab and
// saying in one sentence what the person is looking at. Built for demos and first-time
// visitors, so it never blocks the UI — the tour is a small card you can close at any time.
import { $, prefs } from "./core.js";

const STEPS = [
  { view: "overview", title: "The result in one line",
    body: "The graph model catches some attacks it was never trained on, and learned seven attack types one "
        + "after another without forgetting the first. Every number here is read from the saved experiment files." },
  { view: "soc", title: "What an analyst sees",
    body: "Thousands of flagged flows collapse into a handful of incidents. Pick one to see why it was "
        + "flagged and what containment the system proposes. Nothing is ever executed." },
  { view: "sites", title: "Live traffic",
    body: "Sensors, the cyber range and the sandbox replay arrive here within seconds. Label what you see and "
        + "adapt: the update is kept only if it does not forget old attacks or add false alarms." },
  { view: "explorer", title: "An attack has a shape",
    body: "One window as a graph. Port scans fan out from a single host; floods fan in to a single victim. "
        + "That shape is what the graph model sees and a per-flow model cannot." },
  { view: "models", title: "The evidence",
    body: "Accuracy over the task sequence, forgetting, unseen attacks and the IP-leakage test. "
        + "Turn on Compare models in the top bar to see every baseline." },
];

let index = 0;

function render() {
  const step = STEPS[index];
  location.hash = step.view;
  let el = $("#tour");
  if (!el) {
    el = document.createElement("aside");
    el.id = "tour";
    el.className = "tour";
    document.body.appendChild(el);
  }
  el.innerHTML = `
    <div class="tour-head"><b>${step.title}</b><button class="icon-btn small" id="tour-x" title="End the tour">✕</button></div>
    <p>${step.body}</p>
    <div class="tour-foot">
      <span class="muted">${index + 1} of ${STEPS.length}</span>
      <span>
        <button class="btn" id="tour-prev" ${index === 0 ? "disabled" : ""}>Back</button>
        <button class="btn primary" id="tour-next">${index === STEPS.length - 1 ? "Done" : "Next"}</button>
      </span>
    </div>`;
  $("#tour-x").addEventListener("click", stop);
  $("#tour-prev").addEventListener("click", () => { index = Math.max(0, index - 1); render(); });
  $("#tour-next").addEventListener("click", () => {
    if (index === STEPS.length - 1) stop();
    else { index += 1; render(); }
  });
}

export function start() {
  index = 0;
  prefs.set("tourSeen", "1");
  render();
}

export function stop() {
  $("#tour")?.remove();
}
