"""Simple HTTP leaderboard for OBLM clusters sorted by winrate.

Usage:
    python -m src.trading.groups_leaderboard --model-path data/oblm/model.pkl --port 8090
"""

from __future__ import annotations

import argparse
import html
import logging
import pickle
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


@dataclass
class GroupRow:
    cluster_id: str
    direction: str
    wins: int
    losses: int
    support: int
    winrate_pct: float
    qualified: bool


def _load_groups(model_path: Path, min_support: int, direction_filter: str) -> list[GroupRow]:
    if not model_path.exists():
        return []

    with model_path.open("rb") as f:
        state = pickle.load(f)

    pattern = state.get("pattern_tracker", {}) if isinstance(state, dict) else {}
    raw_clusters = pattern.get("clusters", []) if isinstance(pattern, dict) else []
    if not isinstance(raw_clusters, list):
        return []

    edge_threshold = float(pattern.get("edge_winrate_threshold", 0.60))
    min_cluster_samples = int(pattern.get("min_cluster_samples", 30))
    hi = edge_threshold * 100.0
    lo = (1.0 - edge_threshold) * 100.0

    rows: list[GroupRow] = []
    for row in raw_clusters:
        if not isinstance(row, dict):
            continue
        wins = int(row.get("wins", 0))
        losses = int(row.get("losses", 0))
        support = wins + losses
        if support < max(1, int(min_support)):
            continue

        direction_raw = str(row.get("direction", "NA")).upper()
        direction = "LONG" if direction_raw == "BULL" else "SHORT" if direction_raw == "BEAR" else direction_raw
        if direction_filter in {"LONG", "SHORT"} and direction != direction_filter:
            continue

        winrate = (wins / support * 100.0) if support > 0 else 0.0
        qualified = support >= min_cluster_samples and (winrate >= hi or winrate <= lo)
        rows.append(
            GroupRow(
                cluster_id=str(row.get("cluster_id", "NA")),
                direction=direction,
                wins=wins,
                losses=losses,
                support=support,
                winrate_pct=winrate,
                qualified=qualified,
            )
        )

    rows.sort(key=lambda r: (r.winrate_pct, r.support, r.wins), reverse=True)
    return rows


def _render_html(model_path: Path, min_support: int, direction_filter: str) -> str:
    rows = _load_groups(model_path=model_path, min_support=min_support, direction_filter=direction_filter)
    qs_base = f"?min_support={max(1, int(min_support))}"
    links = (
        f'<a href="{qs_base}&direction=ALL">ALL</a> | '
        f'<a href="{qs_base}&direction=LONG">LONG</a> | '
        f'<a href="{qs_base}&direction=SHORT">SHORT</a>'
    )

    body_rows = []
    for idx, r in enumerate(rows, start=1):
        body_rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{html.escape(r.cluster_id)}</td>"
            f"<td>{html.escape(r.direction)}</td>"
            f"<td>{r.wins}</td>"
            f"<td>{r.losses}</td>"
            f"<td>{r.support}</td>"
            f"<td>{r.winrate_pct:.2f}%</td>"
            f"<td>{'YES' if r.qualified else 'NO'}</td>"
            "</tr>"
        )

    if not body_rows:
        body_rows.append("<tr><td colspan='8'>No groups available yet for current filters.</td></tr>")

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>OBLM Groups Leaderboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #0f1220; color: #e8ecff; }}
    a {{ color: #8ec5ff; }}
    table {{ border-collapse: collapse; width: 100%; background: #171b2f; }}
    th, td {{ border: 1px solid #2a3155; padding: 8px; text-align: left; }}
    th {{ background: #1f2748; }}
    .meta {{ margin-bottom: 12px; color: #b8c2ee; }}
  </style>
</head>
<body>
  <h2>OBLM Groups by Winrate (Best → Worst)</h2>
  <div class="meta">
    model: <code>{html.escape(str(model_path))}</code><br/>
    min_support: <b>{max(1, int(min_support))}</b> &nbsp;|&nbsp; direction: <b>{html.escape(direction_filter)}</b><br/>
    filters: {links}
  </div>
  <table>
    <thead>
      <tr>
        <th>Rank</th>
        <th>Cluster ID</th>
        <th>Direction</th>
        <th>Wins</th>
        <th>Losses</th>
        <th>Support</th>
        <th>Winrate</th>
        <th>Qualified</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="OBLM groups leaderboard web page")
    parser.add_argument("--model-path", default="data/oblm/model.pkl")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--default-min-support", type=int, default=1)
    args = parser.parse_args()

    model_path = Path(args.model_path)
    default_min_support = max(1, int(args.default_min_support))

    class Handler(BaseHTTPRequestHandler):
        def _render(self) -> bytes:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            min_support = int(params.get("min_support", [str(default_min_support)])[0])
            direction = str(params.get("direction", ["ALL"])[0]).upper()
            if direction not in {"ALL", "LONG", "SHORT"}:
                direction = "ALL"
            min_support = max(1, min_support)

            page = _render_html(
                model_path=model_path,
                min_support=min_support,
                direction_filter=direction,
            )
            return page.encode("utf-8")

        def do_GET(self) -> None:  # noqa: N802 (std lib signature)
            payload = self._render()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_HEAD(self) -> None:  # noqa: N802 (std lib signature)
            payload = self._render()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            logger.info("groups_page " + fmt, *args)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    httpd = ThreadingHTTPServer((args.host, int(args.port)), Handler)
    logger.info("Starting groups leaderboard on http://%s:%d", args.host, int(args.port))
    logger.info("Model path: %s", model_path)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
