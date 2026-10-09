# Positioning

**What it is.** A standalone, flow-based network intrusion detector with an analyst console. Sensors capture
packets; a pinned CICFlowMeter turns them into flow records; a graph model scores each site's traffic as a
host/flow graph, groups flagged flows into incidents, abstains when it cannot tell attack from normal, flags
traffic unlike anything it was trained on, and learns new attack types from analyst labels without forgetting
the old ones — every update checked, and rolled back when it would forget or add false alarms.

**What it is not.** A SOC platform or a SIEM. It does not ingest other tools' alerts (Suricata, Snort, Zeek),
correlate across sources, manage cases, or block anything. It has one shared API key, no user accounts or
roles, and no TLS of its own; flows are stored in clear text in SQLite (unlabelled flows are deleted after
seven days). Containment actions are proposed, approved or rejected, and recorded — never executed. Incidents
can be exported as CEF text for a SIEM; nothing is sent automatically.

**Who would use it.** A small team (two to five analysts) running a network it can place a sensor on, that
wants a behaviour-based second opinion beside its existing defences and will not let a model block traffic.

**Alert volume it addresses.** A per-flow detector raises one alert per flow. On the CIC-IDS2017 test windows
about 100,000 flagged flows become about fifty incidents (README §7). Analysts review incidents.

**What it adds next to existing tools.**

| Existing tools keep | This system adds |
|---|---|
| Signature detection, protocol decoding (an IDS such as Suricata or Zeek, run separately) | A behaviour-based view (fan-out, fan-in, who talks to whom) that catches some attack types it was never trained on that a per-flow model misses |
| Correlation, retention, compliance (a SIEM) | Incidents with evidence and a proposed dry-run response, CEF export, an "unsure" list, a novelty flag |
| Every containment decision (the analyst) | A queue ordered by incident, and a model that learns the local network and new attacks from labels, gated against forgetting |

**What must hold before anyone relies on it.** Every number comes from two lab datasets with block-wise attack
schedules. On the cyber range, the untaught model called 45–75 % of a simulated office's normal traffic an
attack; teaching reduces that, but it must be measured on the deployment's own traffic. The graph's advantage
depends on attacks coming from few hosts; with randomised sources it collapses (README §5). Drift detection
needs analyst labels.
