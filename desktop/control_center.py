"""GNN-IDS Control Center - a small desktop app to run the whole system without the command line.

    python desktop/control_center.py          (or double-click desktop/GNN-IDS.bat on Windows)

One window to: start/stop the stack, see service status, open the console, start a sensor on a chosen
network interface, and replay a recorded attack into the live view (the safe sandbox). It only drives the
pieces that already exist (scripts/run_stack.ps1, sensor/agent.py, the API) - it starts no attacks and
sends nothing to any host. Standard library only (tkinter); no new dependencies.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, DISABLED, NORMAL, StringVar, Tk, ttk, filedialog

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)
API_DEFAULT = "http://127.0.0.1:8000"
DASH_DEFAULT = "http://127.0.0.1:8080"
CATEGORIES = ["DoS", "PortScan", "DDoS", "BruteForce", "Infiltration", "Botnet"]


def api_key_headers() -> dict:
    k = os.environ.get("GNNIDS_API_KEY")
    return {"X-API-Key": k} if k else {}


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.msgs: "queue.Queue[str]" = queue.Queue()
        self.ui: "queue.Queue" = queue.Queue()        # callables to run on the main (UI) thread
        self.sensor_proc: subprocess.Popen | None = None
        self.api = StringVar(value=API_DEFAULT)
        self.api_url = API_DEFAULT
        self.api.trace_add("write", lambda *a: setattr(self, "api_url", self.api.get()))
        self.site = StringVar(value="home-lan")
        self.iface = StringVar(value="")
        self.category = StringVar(value=CATEGORIES[0])
        root.title("GNN-IDS Control Center")
        root.geometry("860x620")
        root.minsize(720, 540)
        self._build()
        self._pump()
        self._poll_status()
        self._raise_window()

    def _raise_window(self):
        """Bring the window in front of the launcher console so it is actually seen."""
        try:
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(600, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        pad = {"padx": 8, "pady": 6}
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill=BOTH, expand=False)
        ttk.Label(top, text="GNN-IDS Control Center", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w", columnspan=4)
        ttk.Label(top, text="Continual-learning graph intrusion detection - run the whole system from here.",
                  foreground="#666").grid(row=1, column=0, sticky="w", columnspan=4, pady=(0, 10))

        # --- server row
        ttk.Label(top, text="Server").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.api, width=34).grid(row=2, column=1, sticky="w", **pad)
        self.btn_console = ttk.Button(top, text="Open console", command=self.open_console)
        self.btn_console.grid(row=2, column=2, sticky="w", **pad)

        # --- stack controls
        stack = ttk.LabelFrame(self.root, text="Stack", padding=10)
        stack.pack(fill=BOTH, expand=False, padx=12, pady=6)
        self.btn_start = ttk.Button(stack, text="Start stack (GPU)", command=lambda: self.start_stack(False))
        self.btn_start.grid(row=0, column=0, **pad)
        self.btn_start_cpu = ttk.Button(stack, text="Start stack (CPU)", command=lambda: self.start_stack(True))
        self.btn_start_cpu.grid(row=0, column=1, **pad)
        self.btn_stop = ttk.Button(stack, text="Stop stack", command=self.stop_stack)
        self.btn_stop.grid(row=0, column=2, **pad)
        self.status_lbl = ttk.Label(stack, text="checking...", font=("Segoe UI", 10))
        self.status_lbl.grid(row=0, column=3, sticky="w", **pad)

        # --- sensor
        sensor = ttk.LabelFrame(self.root, text="Sensor (capture this machine's traffic)", padding=10)
        sensor.pack(fill=BOTH, expand=False, padx=12, pady=6)
        ttk.Label(sensor, text="Site").grid(row=0, column=0, **pad)
        ttk.Entry(sensor, textvariable=self.site, width=16).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(sensor, text="Interface").grid(row=0, column=2, **pad)
        self.iface_cb = ttk.Combobox(sensor, textvariable=self.iface, width=28, state="readonly")
        self.iface_cb.grid(row=0, column=3, sticky="w", **pad)
        ttk.Button(sensor, text="Find interfaces", command=self.list_interfaces).grid(row=0, column=4, **pad)
        self.btn_sensor = ttk.Button(sensor, text="Start sensor", command=self.toggle_sensor)
        self.btn_sensor.grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(sensor, text="needs Wireshark + Npcap installed", foreground="#888").grid(row=1, column=2, columnspan=3, sticky="w")

        # --- sandbox
        box = ttk.LabelFrame(self.root, text="Sandbox - replay a recorded attack (safe, nothing is attacked)", padding=10)
        box.pack(fill=BOTH, expand=False, padx=12, pady=6)
        ttk.Label(box, text="Attack").grid(row=0, column=0, **pad)
        ttk.Combobox(box, textvariable=self.category, values=CATEGORIES, width=16, state="readonly").grid(row=0, column=1, sticky="w", **pad)
        ttk.Button(box, text="Replay into live view", command=self.replay).grid(row=0, column=2, **pad)
        ttk.Label(box, text="real recorded flows -> live scorer; watch it on the Live sites tab",
                  foreground="#888").grid(row=0, column=3, sticky="w", **pad)

        # --- demo lab (cyber range)
        lab = ttk.LabelFrame(self.root, text="Demo lab - cyber range (isolated, caged; port scan only, no DoS)", padding=10)
        lab.pack(fill=BOTH, expand=False, padx=12, pady=6)
        self.btn_range = ttk.Button(lab, text="Run cyber range", command=self.run_cyber_range)
        self.btn_range.grid(row=0, column=0, **pad)
        ttk.Label(lab, text="two isolated VMs on your PC: an attacker scans a virtual network, the IDS detects it, "
                  "you teach it, it learns - no real machine is touched", foreground="#888").grid(row=0, column=1, sticky="w", **pad)

        # --- log
        logf = ttk.LabelFrame(self.root, text="Activity", padding=8)
        logf.pack(fill=BOTH, expand=True, padx=12, pady=(6, 12))
        from tkinter import Text, Scrollbar
        self.log = Text(logf, height=10, wrap="word", font=("Consolas", 9), background="#111317", foreground="#d6d9e0")
        sb = Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill=BOTH, expand=True)
        sb.pack(side="right", fill="y")
        self._log("Ready. Start the stack, then open the console or start a sensor.")

    # --------------------------------------------------------------- helpers
    def _log(self, msg: str):
        self.msgs.put(msg)
        try:                                   # also to a file, so failures are diagnosable even if the box is empty
            with open(ROOT / "desktop" / "activity.log", "a", encoding="utf-8") as f:
                f.write(msg.rstrip() + "\n")
        except Exception:
            pass

    def _pump(self):
        try:
            while True:
                msg = self.msgs.get_nowait()
                self.log.configure(state=NORMAL)
                self.log.insert(END, msg.rstrip() + "\n")
                self.log.see(END)
        except queue.Empty:
            pass
        # run any UI updates posted by worker threads (tkinter must only be touched from this thread)
        try:
            while True:
                self.ui.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            pass
        self.root.after(150, self._pump)

    def _run_async(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _powershell(self, args: list[str], env: dict | None = None):
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, creationflags=0x08000000 if os.name == "nt" else 0)

    def _get(self, path: str, timeout=3):
        req = urllib.request.Request(f"{self.api_url.rstrip('/')}{path}", headers=api_key_headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def _post(self, path: str, body: dict, timeout=120):
        req = urllib.request.Request(f"{self.api_url.rstrip('/')}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **api_key_headers()}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    # ----------------------------------------------------------------- actions
    def open_console(self):
        webbrowser.open(self.api.get().replace(":8000", ":8080"))

    def start_stack(self, cpu: bool):
        def work():
            self._log(f"starting stack ({'CPU' if cpu else 'GPU'})... first run prepares data, can take a minute")
            env = {"DEVICE": "cpu"} if cpu else {}
            r = self._powershell(["-File", str(ROOT / "scripts" / "run_stack.ps1"), "-SkipSeed"], env=env)
            out = (r.stdout or "") + (r.stderr or "")
            self._log(out.strip()[-800:] or "stack script finished")
        self._run_async(work)

    def stop_stack(self):
        def work():
            self._log("stopping stack...")
            r = self._powershell(["-File", str(ROOT / "scripts" / "run_stack.ps1"), "-Stop"])
            self._log((r.stdout or r.stderr or "stopped").strip()[-400:])
        self._run_async(work)

    def list_interfaces(self):
        def work():
            self._log("listing capture interfaces (needs Wireshark/dumpcap)...")
            try:
                r = subprocess.run([str(PY), str(ROOT / "sensor" / "agent.py"), "--list"],
                                   cwd=str(ROOT), capture_output=True, text=True, timeout=30)
            except Exception as e:
                self._log(f"could not list interfaces: {e}")
                return
            lines = [ln.strip() for ln in (r.stdout or "").splitlines() if "." in ln and ("(" in ln or "\\" in ln or ln[0].isdigit())]
            self._log(r.stdout.strip() or r.stderr.strip() or "no output")
            if lines:
                self.ui.put(lambda: self.iface_cb.configure(values=lines))
                self.ui.put(lambda: self.iface.set(lines[0]))
        self._run_async(work)

    def toggle_sensor(self):
        if self.sensor_proc and self.sensor_proc.poll() is None:
            self._log("stopping sensor...")
            try:
                self.sensor_proc.terminate()
            except Exception:
                pass
            self.sensor_proc = None
            self.btn_sensor.configure(text="Start sensor")
            return
        iface = (self.iface.get() or "").split()[0] if self.iface.get() else ""
        if not iface:
            self._log("pick an interface first (Find interfaces).")
            return
        self._log(f"starting sensor on interface {iface} as site '{self.site.get()}'...")
        self.btn_sensor.configure(text="Stop sensor")
        cmd = [str(PY), str(ROOT / "sensor" / "agent.py"), "--server", self.api.get(),
               "--site", self.site.get(), "--iface", iface]
        self.sensor_proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, bufsize=1)

        def reader(p):
            for line in p.stdout:
                self._log(line.rstrip())
            self._log("sensor stopped.")
            self.ui.put(lambda: self.btn_sensor.configure(text="Start sensor"))
        self._run_async(lambda: reader(self.sensor_proc))

    def replay(self):
        cat = self.category.get()

        def work():
            self._log(f"replaying a recorded {cat} window into the live view...")
            try:
                r = self._post("/sensor/replay_recorded", {"category": cat, "site": "sandbox"})
            except Exception as e:
                self._log(f"replay failed: {e} (is the stack running?)")
                return
            flagged = ", ".join(f"{v} {k}" for k, v in (r.get("counts") or {}).items() if k != "Benign")
            self._log(f"replayed {r.get('replayed', 0)} flows -> {flagged or 'all benign'}. Open the Live sites tab.")
        self._run_async(work)

    def run_cyber_range(self):
        server = self.api_url            # plain string, safe to pass into the worker thread
        self.btn_range.configure(state=DISABLED, text="Running cyber range...")
        self._log("starting the cyber range (isolated attacker + IDS). This takes a couple of minutes...")

        script = ROOT / "demo" / "cyber_range.py"
        self._log(f"launching: {PY} {script} --server {server}")

        def work():
            try:
                # PYTHONUNBUFFERED so the child's output streams line by line instead of buffering to the end
                env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
                proc = subprocess.Popen(
                    [str(PY), "-u", str(script), "--server", server],
                    cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                    env=env, creationflags=0x08000000 if os.name == "nt" else 0)
                for line in proc.stdout:
                    if line.strip():
                        self._log(line.rstrip())
                proc.wait()
                self._log(f"cyber range finished (exit code {proc.returncode}).")
            except Exception as e:
                self._log(f"cyber range failed to launch: {e!r}")
            finally:
                self.ui.put(lambda: self.btn_range.configure(state=NORMAL, text="Run cyber range"))
        self._run_async(work)

    # ----------------------------------------------------------------- status
    def _poll_status(self):
        def work():
            try:
                h = self._get("/health", timeout=2)
                ml = h.get("ml", {})
                dev = ml.get("device", "?")
                models = len(ml.get("models_loaded", []))
                txt = f"online  -  {models} models, {dev}"
                color = "#1a7f37"
            except Exception:
                txt, color = "offline  -  start the stack", "#b00020"
            self.ui.put(lambda: self.status_lbl.configure(text=txt, foreground=color))
        self._run_async(work)
        self.root.after(3000, self._poll_status)


def main():
    import datetime
    import traceback
    logp = Path(__file__).resolve().parent / "last_run.log"

    def note(msg):
        try:
            with open(logp, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
        except Exception:
            pass

    note("starting")
    try:
        root = Tk()
        note("Tk() created")
        App(root)
        note("App built, entering mainloop")
        root.mainloop()
        note("mainloop returned normally")
    except Exception:
        note("CRASH:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
