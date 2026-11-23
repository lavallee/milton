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
from milton.fleet import FLEET_NAME, read_index, read_snapshot
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


def _when(value: JsonValue) -> str:
    if not isinstance(value, str) or len(value) < 16:
        return "never" if value is None else str(value)
    return f"{value[:10]} {value[11:16]}Z"


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
        '<link rel="icon" href="data:,">'
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
        observations = _dict(_dict(report.get("accounting")).get("observations"))
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
                "cost_events": observations.get("cost_events"),
                "priced_cost_events": observations.get("with_amount"),
                "notional_usd": _dict(snapshot.get("notional")).get("amount_usd")
                if snapshot
                else None,
                "source_coverage": cast(JsonValue, coverage),
            }
        )
    fleet_entry = _dict(index.get("fleet"))
    merged = read_snapshot(fleet_dir, FLEET_NAME)
    fleet: dict[str, JsonValue] = {
        "scope": "merged_store_rebuilt_from_host_stores",
        "status": fleet_entry.get("status"),
        "error": fleet_entry.get("error"),
    }
    if merged is not None:
        merged_report = _dict(merged.get("report"))
        fleet.update(
            snapshot_at=merged.get("generated_at"),
            event_count=merged_report.get("event_count"),
            selected_cost_usd=merged_report.get("cost_usd"),
            notional_usd=_dict(merged.get("notional")).get("amount_usd"),
            pricing_version=_dict(merged.get("notional")).get("pricing_version"),
            merge=merged.get("merge"),
            outcomes=merged.get("outcomes"),
            notional_outcomes=merged.get("notional_outcomes"),
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
        "fleet": fleet,
    }


def _render_fleet(summary: dict[str, JsonValue], findings: dict[str, int] | None) -> str:
    window = _dict(summary.get("window")).get("since") or "all time"
    rows = []
    for raw in _list(summary.get("hosts")):
        host = _dict(raw)
        name = escape(str(host.get("name")))
        status = escape(str(host.get("status") or "unknown"))
        coverage = _dict(host.get("source_coverage"))
        shown = {a: st for a, st in coverage.items() if st not in {"empty", "unavailable"}}
        cov = " ".join(
            f'<span class="{escape(str(state))}">{escape(adapter)}</span>'
            + ("" if state == "ok" else f" ({escape(str(state))})")
            for adapter, state in sorted(shown.items())
        )
        if len(coverage) > len(shown):
            cov += f' <span class="dim">+{len(coverage) - len(shown)} without data</span>'

        error = host.get("error")
        error_html = (
            f"<pre>{escape(str(error)[-400:])}</pre>" if error and status not in {"ok"} else ""
        )
        rows.append(
            f'<tr><td><a href="/hosts/{name}">{name}</a></td>'
            f'<td class="{status}">{status}{error_html}</td>'
            f'<td class="dim">{escape(_when(host.get("last_success_at")))}</td>'
            f'<td class="n">{_int(host.get("event_count"))}</td>'
            f'<td class="n">{_money(host.get("selected_cost_usd"))}</td>'
            f'<td class="n">{_money(host.get("notional_usd"))}</td>'
            f'<td class="n">{_int(host.get("priced_cost_events"))} / '
            f"{_int(host.get('cost_events'))}</td>"
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
        f"collected {escape(_when(summary.get('generated_at')))} · "
        f"milton {escape(str(summary.get('milton_version')))}</p>"
        "<h2>Hosts</h2><table><tr><th>Host</th><th>Last collection</th><th>Last success</th>"
        "<th class='n'>Events</th><th class='n'>Selected cost</th>"
        "<th class='n'>Notional (list)</th>"
        "<th class='n'>Priced / cost events</th><th>Source coverage</th></tr>"
        + "".join(rows)
        + "<tr><td><strong>Sum of hosts</strong></td><td></td><td></td>"
        f"<td class='n'>{_int(totals.get('event_count'))}</td>"
        f"<td class='n'>{_money(totals.get('selected_cost_usd'))}</td>"
        "<td></td><td></td><td class='dim'>may count a shared source twice</td></tr>"
        + _fleet_row(_dict(summary.get("fleet")))
        + "</table>"
        '<p class="note">Each host is scanned on that host under the metadata content '
        "policy and keeps its own coverage. Fleet totals add host projections; they do not "
        "deduplicate observations that more than one host recorded. Selected cost follows "
        "the exact-key precedence in the accounting projection and covers only priced "
        "observations: usage that a source reports without an amount, such as subscription "
        "sessions, counts toward cost events but not toward selected cost. "
        "Notional is the same unpriced usage valued at public list prices: an estimate of "
        "what it would cost on the API, never a charge. "
        '<a href="/api/fleet.json">JSON</a></p>'
        + _fleet_outcomes(_dict(summary.get("fleet")))
        + findings_html
    )
    return _page("Milton", body)


def _fleet_row(fleet: dict[str, JsonValue]) -> str:
    if fleet.get("event_count") is None:
        status = escape(str(fleet.get("status") or "not built"))
        return (
            f"<tr><td><strong>Fleet (merged)</strong></td><td class='{status}'>{status}</td>"
            "<td colspan=6 class='dim'>No merged store yet.</td></tr>"
        )
    conflicts = 0
    for item in _dict(fleet.get("merge")).values():
        value = _dict(item).get("conflicts")
        conflicts += value if isinstance(value, int) else 0
    note = "deduplicated by event identity"
    if conflicts:
        note += f"; {conflicts:,} conflicting records kept from the first host"
    return (
        "<tr><td><strong>Fleet (merged)</strong></td>"
        f"<td class='{escape(str(fleet.get('status')))}'>{escape(str(fleet.get('status')))}</td>"
        f"<td class='dim'>{escape(_when(fleet.get('snapshot_at')))}</td>"
        f"<td class='n'><strong>{_int(fleet.get('event_count'))}</strong></td>"
        f"<td class='n'><strong>{_money(fleet.get('selected_cost_usd'))}</strong></td>"
        f"<td class='n'><strong>{_money(fleet.get('notional_usd'))}</strong></td>"
        f"<td></td><td class='dim'>{escape(note)}</td></tr>"
    )


def _outcome_rows(
    outcomes: dict[str, JsonValue], notional_outcomes: dict[str, JsonValue]
) -> tuple[str, str]:
    selected = _dict(outcomes.get("denominators"))
    notional = _dict(notional_outcomes.get("denominators"))
    rows = []
    for outcome_type in sorted(set(selected) | set(notional)):
        priced = _dict(selected.get(outcome_type))
        valued = _dict(notional.get(outcome_type))
        if not priced.get("outcomes") and not valued.get("outcomes"):
            continue
        rows.append(
            f"<tr><td>{escape(outcome_type)}</td>"
            f"<td class='n'>{_int(valued.get('outcomes') or priced.get('outcomes'))}</td>"
            f"<td class='n'>{_money(priced.get('attributed_usd'))}</td>"
            f"<td class='n'>{_money(valued.get('attributed_usd'))}</td>"
            f"<td class='n'>{_money(valued.get('cost_per_outcome_usd'))}</td></tr>"
        )
    amounts = _dict(notional_outcomes.get("amounts_usd"))
    summary = (
        f"<p class='note'>Priced plus notional: {_money(amounts.get('selected_total'))} = "
        f"attributed {_money(amounts.get('attributed'))} + ambiguous "
        f"{_money(amounts.get('ambiguous'))} + unallocated "
        f"{_money(amounts.get('unallocated'))}. Attribution follows exact recorded "
        "relations only; unallocated spend has no recorded path to a typed outcome.</p>"
    )
    table = (
        "<table><tr><th>Outcome type</th><th class='n'>Outcomes</th>"
        "<th class='n'>Priced attributed</th><th class='n'>Priced + notional</th>"
        "<th class='n'>Per outcome (priced + notional)</th></tr>"
        + ("".join(rows) or "<tr><td colspan=5 class='dim'>No attributed outcomes.</td></tr>")
        + "</table>"
    )
    return summary, table


def _fleet_outcomes(fleet: dict[str, JsonValue]) -> str:
    if fleet.get("event_count") is None:
        return ""
    summary, table = _outcome_rows(
        _dict(fleet.get("outcomes")), _dict(fleet.get("notional_outcomes"))
    )
    return (
        "<h2>Cost per outcome across hosts</h2>"
        "<p class='note'>Computed on the merged fleet store, so an outcome recorded on one "
        "host can claim spend recorded on another. Notional pricing: "
        f"{escape(str(fleet.get('pricing_version')))}.</p>" + summary + table
    )


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
    outcome_summary, outcome_table = _outcome_rows(
        _dict(snapshot.get("outcomes")), _dict(snapshot.get("notional_outcomes"))
    )
    notional = _dict(snapshot.get("notional"))
    model_rows = "".join(
        f"<tr><td>{escape(model)}</td><td class='n'>{_int(_dict(item).get('events'))}</td>"
        f"<td class='n'>{_money(_dict(item).get('amount_usd'))}</td></tr>"
        for model, item in sorted(_dict(notional.get("by_model")).items())
    )
    unvalued = ", ".join(
        f"{model} ({count})"
        for model, count in sorted(_dict(notional.get("unvalued_models")).items())
    )
    notional_html = (
        "<h2>Notional value of unpriced usage</h2>"
        f"<p class='note'>{_int(notional.get('valued_events'))} of "
        f"{_int(notional.get('unpriced_cost_events'))} unpriced cost events valued at list "
        f"price ({escape(str(notional.get('pricing_version')))}): "
        f"<strong>{_money(notional.get('amount_usd'))}</strong>. An estimate, not a charge."
        + (f" No list price for: {escape(unvalued)}." if unvalued else "")
        + "</p><table><tr><th>Model</th><th class='n'>Events</th>"
        "<th class='n'>Notional</th></tr>"
        + (model_rows or "<tr><td colspan=3 class='dim'>None.</td></tr>")
        + "</table>"
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
        + "</table>"
        + notional_html
        + "<h2>Cost per outcome on this host</h2>"
        + outcome_summary
        + outcome_table
        + f'<p class="note"><a href="/api/hosts/{escape(name)}/snapshot.json">'
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
