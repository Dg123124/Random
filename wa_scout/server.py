"""Local web app: edit your profile, run the scout, browse the ranked top 20.

Run with ``python -m wa_scout serve`` and open http://localhost:8765
"""

from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import finance, scout
from .config import REPORTS_DIR, load_profile, save_profile
from .listings import Listing

WEB_DIR = Path(__file__).parent / "web"
MANUAL_INBOX = scout.INBOX_DIR / "manual-ui.json"

_job = {"running": False, "log": [], "error": None, "report": None}
_job_lock = threading.Lock()


def budget_summary(profile: dict) -> dict:
    max_price = finance.max_purchase_price(profile)
    purchase = finance.structure_purchase(max_price, profile)
    service = finance.serviceability(profile, purchase.loan, 0)
    return {
        "max_purchase_price": max_price,
        "purchase_at_max": purchase.to_dict(),
        "serviceability_no_rent": service.to_dict(),
        "net_income_monthly": round(finance.household_net_monthly(profile), 2),
    }


def _run_job(options: dict) -> None:
    def log(msg):
        with _job_lock:
            _job["log"].append(str(msg))

    try:
        out = scout.run(
            load_profile(),
            sources=tuple(options.get("sources") or scout.ALL_SOURCES),
            pages=int(options.get("pages") or 5),
            use_browser=bool(options.get("use_browser", True)),
            refresh_rents=bool(options.get("refresh_rents", True)),
            fetch=bool(options.get("fetch", True)),
            log=log,
        )
        with _job_lock:
            _job["report"] = out["paths"]["json"]
    except Exception as exc:  # surface any failure in the UI log
        log(traceback.format_exc())
        with _job_lock:
            _job["error"] = str(exc)
    finally:
        with _job_lock:
            _job["running"] = False


def _latest_shortlist() -> dict | None:
    path = scout.latest_report_json()
    return json.loads(path.read_text(encoding="utf-8")) if path else None


class Handler(BaseHTTPRequestHandler):
    server_version = "WAPropertyScout/0.1"

    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code: int, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else (
            json.dumps(body, default=str).encode() if content_type == "application/json" else str(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if "text" in content_type or "json" in content_type else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html")
        if path == "/api/profile":
            return self._send(200, load_profile())
        if path == "/api/budget":
            return self._send(200, budget_summary(load_profile()))
        if path == "/api/shortlist":
            return self._send(200, _latest_shortlist() or {"top": []})
        if path == "/api/scout/status":
            with _job_lock:
                return self._send(200, dict(_job))
        if path.startswith("/reports/"):
            target = (REPORTS_DIR / path.removeprefix("/reports/")).resolve()
            if target.parent == REPORTS_DIR.resolve() and target.exists():
                ctype = {"html": "text/html", "csv": "text/csv", "json": "application/json", "md": "text/markdown"}.get(
                    target.suffix.lstrip("."), "application/octet-stream")
                return self._send(200, target.read_bytes(), ctype)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})
        try:
            if path == "/api/profile":
                save_profile(body)
                return self._send(200, {"ok": True, "budget": budget_summary(load_profile())})
            if path == "/api/scout":
                with _job_lock:
                    if _job["running"]:
                        return self._send(409, {"error": "a scout run is already in progress"})
                    _job.update(running=True, log=[], error=None, report=None)
                threading.Thread(target=_run_job, args=(body,), daemon=True).start()
                return self._send(202, {"ok": True})
            if path == "/api/analyse":
                return self._send(200, self._analyse(body))
            if path == "/api/listings":
                return self._send(200, self._add_listing(body))
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found"})

    def _analyse(self, body: dict) -> dict:
        listing = None
        if body.get("url") and not body.get("price") and not body.get("price_text"):
            from .sources import realestate

            listing = realestate.fetch_listing(body["url"])
            if listing is None:
                return {"error": "Could not read that listing page. Enter the details by hand instead."}
        else:
            body.setdefault("id", "adhoc")
            listing = Listing.from_dict(body)
        result = scout.analyse_single(listing)
        if result is None:
            return {"error": "The listing needs a price (or a price range) to be assessed."}
        return result.to_dict()

    def _add_listing(self, body: dict) -> dict:
        scout.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        existing = json.loads(MANUAL_INBOX.read_text(encoding="utf-8")) if MANUAL_INBOX.exists() else []
        body.setdefault("id", f"manual-ui-{len(existing) + 1}")
        existing.append(body)
        MANUAL_INBOX.write_text(json.dumps(existing, indent=1), encoding="utf-8")
        return {"ok": True, "count": len(existing)}


def serve(port: int = 8765, host: str = "127.0.0.1") -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"WA Property Scout running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
