"""Read-only HTTP dashboard over a fleet snapshot directory.

The server never opens an event store. It renders the precomputed
``index.json`` and per-host ``snapshot.json`` files that ``milton fleet
collect`` writes, so every request is cheap and the projections a page shows
are exactly the ones on disk.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

from milton.findings import FindingLedger
from milton.fleet import read_index, read_snapshot
from milton.model import JsonValue
from milton.version import __version__

_STYLE = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--dim:#6b6a65;--line:#e2dfd7;--ok:#2f7d4f;
--warn:#a3670b;--err:#b3322c;--accent:#2b5c8a}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#e9e7e1;--dim:#9a988f;
--line:#2c2b28;--ok:#5cc28a;--warn:#e0a443;--err:#ef7a70;--accent:#7fb0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 ui-sans-serif,system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 24px 64px}
h1{font-size:22px;margin:0}h2{font-size:14px;text-transform:uppercase;letter-spacing:.07em;
color:var(--dim);margin:32px 0 10px}a{color:var(--accent)}
.sub{color:var(--dim);margin:4px 0 0}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:500;color:var(--dim);font-size:12px;border-bottom:1px solid var(--line);
padding:6px 8px}td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
td.n,th.n{text-align:right}.ok{color:var(--ok)}.partial,.stale{color:var(--warn)}
.error,.unreachable{color:var(--err)}.dim{color:var(--dim)}
pre{white-space:pre-wrap;font-size:12px;color:var(--dim);margin:4px 0 0}
.note{color:var(--dim);font-size:13px;max-width:72ch}
"""


def _money(value: JsonValue) -> str:
    try:
        return f"${Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return "—"


def _int(value: JsonValue) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def _dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _list(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def fleet_summary(fleet_dir: Path) -> dict[str, JsonValue]:
    """The fleet document behind ``/`` and ``/api/fleet.json``."""

    index = read_index(fleet_dir)
    hosts: list[JsonValue] = []
    total_events = 0
    total_cost = Decimal(0)
    for raw in _list(index.get("hosts", [])):
        entry = _dict(raw)
        name = str(entry.get("name", ""))
        snapshot = read_snapshot(fleet_dir, name)
        report = _dict(snapshot.get("report")) if snapshot else {}
        events = report.get("event_count")
        cost = report.get("cost_usd")
        if isinstance(events, int):
            total_events += events
        try:
            total_cost += Decimal(str(cost)) if cost is not None else Decimal(0)
        except InvalidOperation:
            pass
        coverage = {
            adapter: _dict(item).get("status")
            for adapter, item in _dict(report.get("source_coverage")).items()
        }
        hosts.append(
            {
                "name": name,
                "status": entry.get("status"),
                "error": entry.get("error"),
                "collected_at": entry.get("collected_at"),
                "last_success_at": entry.get("last_success_at"),
                "snapshot_at": snapshot.get("generated_at") if snapshot else None,
                "event_count": events,
                "selected_cost_usd": cost,
                "source_coverage": cast(JsonValue, coverage),
            }
        )
    return {
        "schema_version": 1,
        "milton_version": __version__,
        "generated_at": index.get("generated_at"),
        "window": index.get("window"),
        "content_policy": index.get("content_policy"),
        "hosts": hosts,
        "totals": {
            "scope": "sum_of_host_projections",
            "event_count": total_events,
            "selected_cost_usd": str(total_cost),
        },
    }


def _render_fleet(summary: dict[str, JsonValue], findings: dict[str, int] | None) -> str:
    window = _dict(summary.get("window")).get("since") or "all time"
    rows = []
    for raw in _list(summary.get("hosts")):
        host = _dict(raw)
        name = escape(str(host.get("name")))
        status = escape(str(host.get("status") or "unknown"))
        coverage = _dict(host.get("source_coverage"))
        cov = " ".join(
            f'<span class="{escape(str(state))}">{escape(adapter)}</span>'
            for adapter, state in sorted(coverage.items())
        )
        error = host.get("error")
        error_html = (
            f"<pre>{escape(str(error)[-400:])}</pre>" if error and status not in {"ok"} else ""
        )
        rows.append(
            f'<tr><td><a href="/hosts/{name}">{name}</a></td>'
            f'<td class="{status}">{status}{error_html}</td>'
            f'<td class="dim">{escape(str(host.get("last_success_at") or "never"))}</td>'
            f'<td class="n">{_int(host.get("event_count"))}</td>'
            f'<td class="n">{_money(host.get("selected_cost_usd"))}</td>'
            f"<td>{cov}</td></tr>"
        )
    totals = _dict(summary.get("totals"))
    findings_html = ""
    if findings is not None:
        cells = (
            "".join(
                f"<tr><td>{escape(grade)}</td><td class='n'>{count:,}</td></tr>"
                for grade, count in sorted(findings.items())
            )
            or "<tr><td colspan=2 class='dim'>No findings recorded.</td></tr>"
        )
        findings_html = (
            "<h2>Findings by current grade</h2><table><tr><th>Grade</th>"
            f"<th class='n'>Findings</th></tr>{cells}</table>"
        )
    body = (
        "<h1>Milton</h1>"
        f'<p class="sub">Fleet view · window {escape(str(window))} · '
        f"collected {escape(str(summary.get('generated_at') or 'never'))} · "
        f"milton {escape(str(summary.get('milton_version')))}</p>"
        "<h2>Hosts</h2><table><tr><th>Host</th><th>Last collection</th><th>Last success</th>"
        "<th class='n'>Events</th><th class='n'>Selected cost</th><th>Source coverage</th></tr>"
        + "".join(rows)
        + "<tr><td><strong>Fleet</strong></td><td></td><td></td>"
        f"<td class='n'><strong>{_int(totals.get('event_count'))}</strong></td>"
        f"<td class='n'><strong>{_money(totals.get('selected_cost_usd'))}</strong></td>"
        "<td class='dim'>sum of host projections</td></tr></table>"
        '<p class="note">Each host is scanned on that host under the metadata content '
        "policy and keeps its own coverage. Fleet totals add host projections; they do not "
        "deduplicate observations that more than one host recorded. Selected cost follows "
        "the exact-key precedence in the accounting projection. "
        '<a href="/api/fleet.json">JSON</a></p>' + findings_html
    )
    return _page("Milton", body)


def _render_host(name: str, entry: dict[str, JsonValue], snapshot: dict[str, JsonValue]) -> str:
    report = _dict(snapshot.get("report"))
    adapters = _dict(report.get("adapters"))
    adapter_rows = []
    for adapter, raw in sorted(adapters.items()):
        item = _dict(raw)
        tokens = _dict(item.get("tokens"))
        gaps = ", ".join(f"{k} {v}" for k, v in sorted(_dict(item.get("gaps")).items()))
        adapter_rows.append(
            f"<tr><td>{escape(adapter)}</td><td class='n'>{_int(item.get('events'))}</td>"
            f"<td class='n'>{_money(item.get('cost_usd'))}</td>"
            f"<td class='n'>{_int(tokens.get('input'))}</td>"
            f"<td class='n'>{_int(tokens.get('output'))}</td>"
            f"<td class='dim'>{escape(gaps) or '—'}</td></tr>"
        )
    coverage_rows = []
    for adapter, raw in sorted(_dict(report.get("source_coverage")).items()):
        item = _dict(raw)
        sources = _dict(item.get("sources"))
        state = escape(str(item.get("status")))
        coverage_rows.append(
            f"<tr><td>{escape(adapter)}</td><td class='{state}'>{state}</td>"
            f"<td class='n'>{_int(sources.get('discovered'))}</td>"
            f"<td class='n'>{_int(sources.get('read'))}</td>"
            f"<td class='n'>{_int(sources.get('failed'))}</td>"
            f"<td class='n'>{_int(item.get('malformed_records'))}</td>"
            f"<td class='dim'>{escape(str(item.get('last_ingested_at')))}</td></tr>"
        )
    outcomes = _dict(snapshot.get("outcomes"))
    amounts = _dict(outcomes.get("amounts_usd"))
    denominator_rows = []
    for outcome_type, raw in sorted(_dict(outcomes.get("denominators")).items()):
        item = _dict(raw)
        denominator_rows.append(
            f"<tr><td>{escape(outcome_type)}</td><td class='n'>{_int(item.get('outcomes'))}</td>"
            f"<td class='n'>{_money(item.get('attributed_usd'))}</td>"
            f"<td class='n'>{_money(item.get('cost_per_outcome_usd'))}</td></tr>"
        )
    status = escape(str(entry.get("status") or "unknown"))
    period = _dict(report.get("period"))
    body = (
        f'<p><a href="/">← Fleet</a></p><h1>{escape(name)}</h1>'
        f'<p class="sub"><span class="{status}">{status}</span> · snapshot '
        f"{escape(str(snapshot.get('generated_at')))} · events "
        f"{escape(str(period.get('start')))} to {escape(str(period.get('end')))}</p>"
        "<h2>Sources</h2><table><tr><th>Adapter</th><th class='n'>Events</th>"
        "<th class='n'>Selected cost</th><th class='n'>Input tokens</th>"
        "<th class='n'>Output tokens</th><th>Coverage gaps</th></tr>"
        + ("".join(adapter_rows) or "<tr><td colspan=6 class='dim'>No events.</td></tr>")
        + "</table><h2>Ingestion coverage</h2><table><tr><th>Adapter</th><th>Status</th>"
        "<th class='n'>Discovered</th><th class='n'>Read</th><th class='n'>Failed</th>"
        "<th class='n'>Malformed</th><th>Last ingested</th></tr>"
        + "".join(coverage_rows)
        + "</table><h2>Cost per outcome</h2>"
        f"<p class='note'>Selected {_money(amounts.get('selected_total'))} = attributed "
        f"{_money(amounts.get('attributed'))} + ambiguous {_money(amounts.get('ambiguous'))} "
        f"+ unallocated {_money(amounts.get('unallocated'))}.</p>"
        "<table><tr><th>Outcome type</th><th class='n'>Outcomes</th>"
        "<th class='n'>Attributed</th><th class='n'>Per outcome</th></tr>"
        + ("".join(denominator_rows) or "<tr><td colspan=4 class='dim'>None.</td></tr>")
        + f'</table><p class="note"><a href="/api/hosts/{escape(name)}/snapshot.json">'
        "Snapshot JSON</a></p>"
    )
    return _page(f"Milton · {name}", body)


def _finding_grades(path: Path | None) -> dict[str, int] | None:
    if path is None or not path.exists():
        return None
    counts: dict[str, int] = {}
    for revision in FindingLedger(path).current().values():
        counts[revision.grade.value] = counts.get(revision.grade.value, 0) + 1
    return counts


def make_handler(fleet_dir: Path, findings: Path | None = None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"milton/{__version__}"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json(self, document: JsonValue, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(document, indent=1, sort_keys=True), "application/json")

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlsplit(self.path).path).rstrip("/") or "/"
            if path == "/health":
                index = read_index(fleet_dir)
                self._json(
                    {
                        "status": "ok",
                        "milton_version": __version__,
                        "collected_at": index.get("generated_at"),
                    }
                )
                return
            if path == "/":
                summary = fleet_summary(fleet_dir)
                self._send(
                    HTTPStatus.OK, _render_fleet(summary, _finding_grades(findings)), "text/html"
                )
                return
            if path == "/api/fleet.json":
                self._json(fleet_summary(fleet_dir))
                return
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "hosts":
                entry, snapshot = self._host(parts[1])
                if snapshot is not None:
                    self._send(HTTPStatus.OK, _render_host(parts[1], entry, snapshot), "text/html")
                    return
            if len(parts) == 4 and parts[:2] == ["api", "hosts"] and parts[3] == "snapshot.json":
                _, snapshot = self._host(parts[2])
                if snapshot is not None:
                    self._json(snapshot)
                    return
            self._send(HTTPStatus.NOT_FOUND, _page("Not found", "<h1>Not found</h1>"), "text/html")

        def _host(self, name: str) -> tuple[dict[str, JsonValue], dict[str, JsonValue] | None]:
            for raw in _list(read_index(fleet_dir).get("hosts", [])):
                entry = _dict(raw)
                if entry.get("name") == name:
                    return entry, read_snapshot(fleet_dir, name)
            return {}, None

    return Handler


def serve(fleet_dir: Path, *, host: str, port: int, findings: Path | None = None) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(fleet_dir, findings))
    print(f"milton: serving {fleet_dir} on http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
