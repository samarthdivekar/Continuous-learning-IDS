# Live demo and multi-site (LAN / MAN) guide

This is the step-by-step for running the system on **real network traffic** instead of the recorded
datasets: one or more sensor machines capture their own traffic, the central console scores it per site,
and you can label flows and watch the model adapt without forgetting old attacks.

> **It never blocks traffic.** Every proposed containment rule is a dry run — text you could paste into a
> firewall yourself, never executed. The sensor only listens.

> **Honest expectation.** The model has only ever been trained on two lab datasets (CIC-IDS2017 /
> CSE-CIC-IDS2018). On your own Wi-Fi it will raise some false alarms until you teach it what your normal
> traffic looks like (step 4). It has the best chance on the attacks it was trained on: **port scans
> (nmap)** and **DoS (Slowloris / Hulk-style)**. Treat the demo as evidence of the pipeline and the
> learning loop, not as a finished product.

---

## Quick start (desktop app)

The easiest way to run everything is the control center:

```
python desktop/control_center.py        (or double-click desktop/GNN-IDS.bat)
```

One window: **Start stack**, **Open console**, start a **sensor** on a chosen interface, and a **Sandbox**
button that replays a recorded attack into the live view. It only drives the existing pieces; it starts no
attacks. If you prefer the command line, everything below still works.

### The safe "watch it detect an attack" moment — sandbox replay

In the console's **Live sites** tab (or the desktop app), pick an attack (DoS / PortScan / DDoS / …) and
press **Replay recorded attack**. This takes a *real recorded window* of that attack from the dataset's
held-out test set and runs it through the live scorer, so you see it detected live — the graph lights up
red, incidents appear with the attacker IP and a dry-run rule — **without launching anything**. Nothing is
generated and nothing is sent to any host. This is the reliable centrepiece; the live attack in §3 is the
"for real" version you run by hand.

## 0. What runs where

```
 Site A (your PC, Wi-Fi)            Central console (your PC, or a 3rd machine)
 ┌───────────────────────┐          ┌──────────────────────────────────────────┐
 │ sensor/agent.py        │  pcap    │ /sensor/pcap → CICFlowMeter (Docker)       │
 │  dumpcap → 10 s chunks │ ───────► │  → flows → live model → per-site console    │
 └───────────────────────┘  HTTP     │  dashboard /#sites                          │
 Site B (friend's laptop)            │                                             │
 ┌───────────────────────┐  pcap     │                                             │
 │ sensor/agent.py        │ ───────► │                                             │
 │  (over Tailscale VPN)  │          └──────────────────────────────────────────┘
 └───────────────────────┘
```

The central console is the normal stack (`scripts/run_stack.ps1`). The flow conversion runs in Docker with
the **exact CICFlowMeter the training data came from** (`sensor/cicflowmeter.Dockerfile`, pinned to commit
`e3bb9ce`); any capture whose columns do not match the training data is refused, not scored.

---

## 1. One-time setup

**On the central machine (the one that shows the console):**

1. Docker Desktop (already installed here). Build the flow meter once:
   ```powershell
   docker build -t gnnids-cicflowmeter -f sensor/cicflowmeter.Dockerfile sensor
   ```
2. Start the stack (GPU):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1 -Open
   ```
   The console opens at `http://localhost:8080/`. Go to **Live sites** (key `4`).
3. Find this machine's address other machines will use:
   - same Wi-Fi: `ipconfig` → the IPv4 of your Wi-Fi adapter, e.g. `192.168.1.20`.
   - across networks: install **Tailscale** (below) and use its `100.x.y.z` address.

**On each sensor machine (your PC, your friend's laptop):**

1. Install **Wireshark** from <https://www.wireshark.org/> and, in the installer, tick **Install Npcap**.
   This is what lets the sensor capture packets. (This is a driver install; only you can do it.)
2. Python 3.10+ (standard library only — no pip packages needed for the sensor).
3. Copy the `sensor/` folder (or the whole repo) to that machine.

**Optional, for the MAN / two-network demo — Tailscale (free):**

1. Install Tailscale on **both** the central machine and the second sensor from <https://tailscale.com/>.
2. Sign in to the same account on both. Each gets a stable `100.x.y.z` address that works across any two
   networks (home Wi-Fi + phone hotspot) with an encrypted tunnel and no router changes.
3. On the central machine, `tailscale ip -4` gives the address the sensors point at.

---

## 2. Start a sensor

Find the interface number first:

```bash
python sensor/agent.py --list
```

Pick your Wi-Fi/Ethernet adapter's number, then (replace the address with your central machine's):

```bash
python sensor/agent.py --server http://192.168.1.20:8000 --site home-lan --iface 5
```

- `--site` is the name shown in the console (`home-lan`, `campus`, `friend-laptop`, …).
- Each 10-second chunk is captured, uploaded, converted and scored; a line prints per chunk.
- The sensor skips its own upload traffic, so it does not score itself.
- Stop it with Ctrl-C.

Within ~15 seconds the site appears in **Live sites** with a live flow count.

---

## 3. The demo script (≈ 10 minutes)

Do this on **your own devices and your own router or a phone hotspot** — never on college or shared Wi-Fi.
A scan or flood on a shared network can disrupt other people and breaks most acceptable-use rules. You own
the kit; keep it that way.

**Scene 1 — normal traffic.** Start the sensor on your PC. Browse a few sites. The console shows the site
online, flows counting up, nothing flagged. *"This is the model watching real traffic for the first time."*

**Scene 2 — teach it your network (continual learning, part 1).** After a minute of normal use, in the
**Teach the model** panel set "last 2 min" and click **Mark normal**, then **Adapt model now**. The Live
model card logs an adaptation and shows *old-attack macro-F1 before → after* staying flat: *"it learned my
network without forgetting the attacks it already knew — that number is measured each time, and if it had
dropped, the update would have been rolled back."*

**Scene 3 — a known attack.** On the friend's laptop, run an attack the model was trained on, against your
PC's IP (your PC is the victim). Examples (install these on the attacker machine yourself):

- Port scan: `nmap -sS -T4 <victim-ip>` (nmap).
- DoS: `slowhttptest -c 500 -H -i 10 -r 200 -u http://<victim-ip>/` (slowhttptest), or a rate-limited
  SYN flood with `hping3 --flood -S -p 80 <victim-ip>` — keep it short.

Within ~10–30 s an **incident** appears in the console: the attacker host, the category, a dry-run rule.
*"Detected from traffic shape alone, grouped into one incident, with a proposed action I would apply by hand."*

**Scene 4 — a new attack (continual learning, part 2).** Run something the model does not know well (e.g. a
different tool, or a protocol it never saw). It will likely show up under **Unfamiliar traffic** (flagged as
"unlike anything in training") even if it is not classified. Pick a label for those flows, click **Adapt
model now**, and show that the attack is now caught while Scene-3's attack and the lab attacks are still
caught (old-attack F1 held). *"This is the whole point: it keeps learning new attacks without forgetting."*

**Backup:** record each attack once beforehand (`sensor/agent.py` can also just capture to a file, or use
Wireshark), and if the live run misbehaves, replay it:
```bash
python sensor/agent.py --server http://<central>:8000 --site lab --replay attack.pcap
```
The replay goes through the exact same pipeline, so it looks identical in the console.

---

## 3a. A real number: false alarms on your own traffic

The honest open question for this project is how well a model trained on lab data holds up on real traffic.
You can measure one piece of that on your own network, and quote it in the viva:

1. Capture ~10 minutes of **normal** use (browse, stream, whatever is ordinary for you); do nothing unusual
   so you can treat it all as benign. Save it as `normal.pcap` (Wireshark → File → Save, or the sensor's
   ring-buffer files).
2. On the central machine (the one with Docker and the flow-meter image):
   ```bash
   python sensor/measure_fpr.py --pcap normal.pcap --server http://localhost:8000
   ```

It splits the capture into a teach half and a held-out half, measures the **false-positive rate** on the
held-out half, teaches the teach half as benign, measures again, and restores the model (so it only
measures, changing nothing). It prints before/after, and what teaching cost the model's recall on attacks it
already knew. A real sentence for the report: *"on N minutes of my own traffic the model flagged X% of
benign flows; after two minutes of teaching, Y%."*

Be honest about what it means: the number is only for the network you captured on, it is not a dataset
result, and on a **small or unrepresentative capture teaching can make things slightly worse** (a tiny
benign sample is not enough to learn "normal" from) — which is itself a finding worth stating. Capture
enough, and capture traffic that is genuinely typical.

## 4. Two sites at once (LAN + the MAN story)

1. Central machine on your Wi-Fi runs the stack.
2. Sensor A = your PC on the same Wi-Fi: `--server http://<lan-ip>:8000 --site site-a`.
3. Sensor B = friend's laptop on a **phone hotspot** (a different network), over Tailscale:
   `--server http://<tailscale-ip>:8000 --site site-b`.

Both sites show side by side in **Live sites**, each with its own flows, incidents and graph. A real MAN
links sites across a city; this is the same architecture — two networks, one console, an encrypted tunnel
between them — at a scale you can run from two laptops.

---

## 5. Security and honesty notes for the viva

- **Dry-run only.** No endpoint blocks traffic; the proposed rules are text. This is deliberate and stated
  in the model card and README.
- **Features must match.** The sensor uses the pinned CICFlowMeter; a capture from a different tool is
  rejected, because a model fed differently computed features gives confident answers that mean nothing.
- **Expect false positives on real traffic** until you teach it (Scene 2). The datasets are lab captures;
  generalisation to live traffic is exactly the open problem the project is honest about.
- **No new model claims.** Nothing in the README's results comes from the live demo; the demo exercises the
  trained model and the learning loop, it does not add measured numbers to the evaluation.
