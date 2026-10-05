// "Models" tab: how the models score through the task sequence, and how they hold up on
// attacks and hosts they never saw. Two sections that used to be separate tabs, so the
// evidence about model quality lives in one place.
import * as compare from "./compare.js";
import * as general from "./general.js";
import { subTabs } from "../lib/subtabs.js";

const SECTIONS = [
  { id: "accuracy", label: "Accuracy & forgetting", mod: compare },
  { id: "unseen", label: "Unseen attacks & IP leakage", mod: general },
];

const view = subTabs("models", SECTIONS, {
  intro: "Does the model learn each new attack and keep the old ones? And does it still work on attacks "
         + "and hosts it has never seen?",
});
export const mount = view.mount;
export const refresh = view.refresh;
export const activate = view.activate;
