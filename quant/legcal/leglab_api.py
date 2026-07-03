#!/usr/bin/env python3
"""Tiny shared-progress store for the leg-labeling dashboard.
Single-threaded (requests serialize -> no races). Binds localhost only;
Caddy basic_auth (@protected /api/*) handles authentication in front.

  GET  /api/state                          -> {"ftmo":{date:label,...},"cme":{...}}
  POST /api/state  body {ds,date,label}    -> merge one label, persist, return counts

DATA-SAFETY (labels.json ist das EINZIGE unersetzliche Artefakt):
  - append-only Audit-Log labels_audit.jsonl bei JEDEM POST (volle Historie -> rekonstruierbar)
  - labels.json.bak = letzter guter Stand VOR dem Ueberschreiben (Ein-Schritt-Undo)
  - Validierung: Content-Length-Cap, Datumsformat-Whitelist, Label-Form-Check (kein Junk in den Store)

Body wird als JSON unabhaengig vom Content-Type geparst (CORS-safe simple request aus dem Blob-Doc).
"""
import json, os, re, shutil, threading, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

DATA = "/opt/leglab/data/labels.json"
AUDIT = "/opt/leglab/data/labels_audit.jsonl"
LOCK = threading.Lock()
MAX_BODY = 1_000_000                          # 1 MB cap pro POST
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(__retest)?$")
OK_TYPES = {"cand", "drawn", "box"}
# Claude bekommt EIGENE Stores (ftmo_claude/cme_claude) -> Cristianos ftmo/cme werden NIE ueberschrieben.
OK_DS = ("ftmo", "cme", "ftmo_claude", "cme_claude")


def load():
    try:
        with open(DATA) as f:
            return json.load(f)
    except Exception:
        return {k: {} for k in OK_DS}


def save(state):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    if os.path.exists(DATA):                  # letzter guter Stand sichern (Ein-Schritt-Undo) — nur wenn valide+nicht leer, sonst clobbert ein degenerierter Stand das Backup
        try:
            with open(DATA) as _f: _cur = json.load(_f)
            if _cur and any(_cur.get(k) for k in OK_DS):
                shutil.copy2(DATA, DATA + ".bak")
        except Exception: pass
    tmp = DATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, DATA)


def audit(ds, date, label):                  # append-only: geht NIE verloren, selbst wenn labels.json kaputtgeht
    try:
        os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
        with open(AUDIT, "a") as f:
            f.write(json.dumps({"t": datetime.datetime.utcnow().isoformat() + "Z",
                                "ds": ds, "date": date, "label": label}, separators=(",", ":")) + "\n")
            f.flush(); os.fsync(f.fileno())
    except Exception:
        pass


class H(BaseHTTPRequestHandler):
    timeout = 15   # per-request socket timeout -> kein slowloris-Hang des single-thread Servers

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/") == "/api/state":
            with LOCK:
                self._send(200, load())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/state":
            self._send(404, {"error": "not found"}); return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            self._send(400, {"error": "bad content-length"}); return
        if n < 0 or n > MAX_BODY:
            self._send(413, {"error": "bad body size"}); return
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, {"error": "bad json"}); return
        ds, date, label = body.get("ds"), body.get("date"), body.get("label")
        if ds not in OK_DS:
            self._send(400, {"error": "bad ds"}); return
        if not isinstance(date, str) or not DATE_RE.match(date):
            self._send(400, {"error": "bad date format (YYYY-MM-DD[__retest])"}); return
        if not isinstance(label, dict) or label.get("type") not in OK_TYPES:
            self._send(400, {"error": "bad label shape"}); return
        with LOCK:
            audit(ds, date, label)            # zuerst protokollieren (Intent sicher), dann mergen
            st = load()
            st.setdefault(ds, {})[date] = label
            save(st)
            self._send(200, {"ok": True, "count": {k: len(v) for k, v in st.items()}})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 3002), H).serve_forever()
