// "Adaptation & trust" tab: when the system notices that traffic changed and retrains,
// and whether its decisions can be trusted (novel attacks, abstention, alert load,
// label budget). Previously the separate Drift analysis and Trust & novelty tabs.
import * as drift from "./drift.js";
import * as trust from "./trust.js";
import { subTabs } from "../lib/subtabs.js";

const SECTIONS = [
  { id: "drift", label: "Drift & retraining", mod: drift },
  { id: "trust", label: "Trust: novelty, abstention, alert load", mod: trust },
];

const view = subTabs("adapt", SECTIONS, {
  intro: "Traffic changes over time. These panels show when the system noticed, what it did about it, "
         + "and how far its decisions can be trusted.",
});
export const mount = view.mount;
export const refresh = view.refresh;
export const activate = view.activate;
