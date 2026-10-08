# Demo cheat sheet (for the guide meeting)

## What the three pieces are (say this)

1. **The console** — the web page at **http://localhost:8080**. This is the **IDS screen** an analyst
   watches. It shows the network as a graph and flags attacks. *This is the product.*

2. **The stack (the backend / "brain")** — runs the AI model on the GPU and feeds the console.
   The console needs it running. That's why you **Start the stack** first.

3. **The cyber range (the "VMs")** — a tiny fake network **inside Docker**: one container is the
   **attacker**, a few are **victims**. It lets you show a **real attack** without a second laptop and
   without touching the real Wi-Fi. *Nothing real is attacked.*

**How the attack "reflects":** the attacker VM scans the victims → the IDS captures that traffic → the AI
scores it → it shows up as a **red site (CYBER-RANGE)** in the console, with a graph and incidents.

---

## Before the meeting (5 min, once)

1. Make sure **Docker Desktop** is running (whale icon in the taskbar). Open it if not.
2. Double-click the Desktop shortcut **"GNN-IDS Control Center"** → click **Start stack (GPU)**.
   Wait until the status reads **online – 4 models, cuda** (about 30–45 seconds).
3. Open a browser to **http://localhost:8080** → click **Live sites** on the left.
4. Click **Reset model** (top of Live sites) so you start clean.

---

## The demo (two parts)

### Part 1 — "The IDS detects attacks" (instant, always works)
1. In **Live sites**, next to **Sandbox**, pick **DoS** (or PortScan / DDoS).
2. Click **Replay recorded attack**.
3. A **red site** appears with a graph and the attack flagged. Open **Incident queue** (left) to show the
   attacker's IP, why it was flagged, and the proposed (dry-run) firewall rule.

Say: *"This is the IDS scoring real recorded attack traffic and raising an incident — it never blocks, it
advises; a human approves."*

### Part 2 — "A real attack, and it learns" (the wow, ~2 min)
1. Double-click the Desktop shortcut **"Run Cyber Range (demo)"**. A black window opens and shows 4 phases.
2. Watch it, and keep the console **Live sites** tab open next to it.
3. The phases:
   - **Attack #1** — an attacker VM scans a virtual network. The model's response to a *brand-new* real
     scan is weak (it may miss it — that's the honest limitation: it was trained on lab data).
   - **Teach it** — we label the scan and the model adapts. The window shows **old-attack score held at
     ~0.97** (it did **not** forget).
   - **Attack #2** — a *fresh* scan it never saw is now **detected** (the **CYBER-RANGE** site goes red).
   - **No forgetting** — the recorded attacks still detect at 95–100%.

Say: *"A real attacker scanned a network. The model trained on 2017 lab data didn't recognise this modern
scan — that's the real-world gap my project is about. I taught it with a few labels, and now it catches
scans it never saw, while still catching everything it already knew. That continual learning — new attacks
without forgetting old ones — is the contribution."*

---

## If something goes wrong (stay calm)

- **Console won't load / says offline:** the stack isn't running. Control Center → **Start stack**, wait for
  "online". Or close and reopen the Control Center.
- **Cyber range window flashes and closes:** Docker Desktop isn't running — open it, wait for the whale icon
  to go steady, try again.
- **Cyber range says "cannot reach the console":** start the stack first (see above).
- **Fallback:** Part 1 (Sandbox replay) always works and tells the whole "it detects and advises" story on
  its own. Use it if Part 2 misbehaves.

---

## The honest points (examiners respect these)

- It **never blocks** traffic — every action is a dry-run proposal a human approves.
- A **real modern scan is not detected out of the box** — the model learned 2017/2018 lab data, and real
  traffic differs. This is the project's central, documented limitation (README §1, §5).
- The value is the **continual-learning loop**: teach it the local attacks, and it learns them **without
  forgetting** the old ones — measured, gated, and rolled back if it would forget.
