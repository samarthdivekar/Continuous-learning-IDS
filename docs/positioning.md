# Positioning

**What it is.** A continual-learning triage layer on the alert stream of an IDS a team already runs. It
groups flagged flows into incidents, flags traffic unlike any attack it knows, abstains when unsure, and
learns new attack types without losing the old ones.

**What it is not.** A SOC platform. There is no case management, no cross-source SIEM correlation, no
authentication by default, no TLS, no roles; flows are stored in clear text in SQLite; containment actions
are proposed and recorded, never executed.

**Who uses it.** A team of two to five analysts that already runs a signature IDS (Suricata, Snort, Zeek)
and a flow exporter, has more alerts than it can read, and will not let a model block traffic.

**Alert volume it addresses.** A per-flow detector raises one alert per flow. On the CIC-IDS2017 test
windows about 100,000 flagged flows become about fifty incidents (README §7). Analysts review incidents.

**What it augments.**

| Stays with the existing stack | Added by this layer |
|---|---|
| Signature IDS: known-bad patterns, protocol decoding | A behaviour-based second opinion (fan-out, fan-in, who talks to whom), which catches some attack types it was never trained on that a per-flow model misses |
| SIEM: correlation, retention, compliance | Incidents with evidence and a proposed dry-run response; an "unsure" bucket; a novelty flag |
| The analyst: every containment decision | A queue ordered by incident, and models that adapt when labelled traffic shows drift |

**What must hold before anyone relies on it.** The graph's advantage depends on attacks coming from few
hosts; with randomised sources it collapses (README §5). Drift detection needs delayed analyst labels.
Every number here comes from two lab datasets with block-wise attack schedules, so it must be validated on
the deployment's own traffic, and flows would have to arrive from Zeek or Suricata rather than CSV.
