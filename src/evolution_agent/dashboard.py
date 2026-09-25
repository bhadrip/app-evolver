from __future__ import annotations

import argparse
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from .engine import Engine


STYLE = """
:root{font-family:Inter,system-ui,sans-serif;color:#172d28;background:#f6f5ef}*{box-sizing:border-box}
body{margin:0}header{padding:28px 5vw;border-bottom:1px solid #d8ddd8;background:#173d32;color:white}
header h1{margin:0 0 6px;font-family:Georgia,serif;font-size:2.3rem}header p{margin:0;color:#c9ded5}
main{width:min(1180px,90vw);margin:40px auto 80px}.policy{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px}
.pill{padding:8px 12px;border-radius:99px;background:#e3ebd0;font-size:.85rem;font-weight:700}
h2{font-family:Georgia,serif;font-size:1.8rem;margin-top:42px}.grid{display:grid;gap:16px}
.card{background:white;border:1px solid #d8ddd8;border-radius:16px;padding:20px;box-shadow:0 10px 30px #173d320a}
.row{display:flex;justify-content:space-between;gap:20px;align-items:start}.muted{color:#667772}.score{font-size:1.4rem;font-weight:800}
button{background:#236b50;color:white;border:0;border-radius:99px;padding:9px 14px;font-weight:750;cursor:pointer}
button.secondary{background:white;color:#173d32;border:1px solid #9baba4}form{display:inline}pre{white-space:pre-wrap;overflow:auto;background:#15241f;color:#d8f3e8;padding:16px;border-radius:12px;max-height:360px}
.error{padding:14px;background:#ffe0d6;border:1px solid #d88870;border-radius:12px}.success{padding:14px;background:#e3f3d1;border:1px solid #8bab63;border-radius:12px}
details{margin-top:12px}summary{cursor:pointer;font-weight:700}@media(max-width:650px){.row{flex-direction:column}}
"""


class DashboardHandler(BaseHTTPRequestHandler):
    engine: Engine
    notice = ""
    error = ""

    def do_GET(self) -> None:
        if self.path != "/":
            return self.send_error(HTTPStatus.NOT_FOUND)
        observations = self.engine.store.observations()
        proposals = self.engine.store.proposals()
        hitl = self.engine.constitution["humanInTheLoop"]
        observation_cards = "".join(self._observation_card(item) for item in observations) or "<p>No observations yet.</p>"
        proposal_cards = "".join(self._proposal_card(item) for item in proposals) or "<p>No proposals yet.</p>"
        message = ""
        if self.error:
            message = f'<p class="error">{html.escape(self.error)}</p>'
        elif self.notice:
            message = f'<p class="success">{html.escape(self.notice)}</p>'
        self.__class__.notice = self.__class__.error = ""
        body = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Evolution control room</title><style>{STYLE}</style></head>
        <body><header><h1>Evolution control room</h1><p>Evidence before hypotheses. Validation before release.</p></header>
        <main>{message}<div class="policy"><span class="pill">Observation selection: {html.escape(hitl['observationSelection'])}</span><span class="pill">Change approval: {html.escape(hitl['changeApproval'])}</span></div>
        <form method="post"><input type="hidden" name="action" value="sync"><button>Sync & triage</button></form>
        <h2>Candidate observations</h2><div class="grid">{observation_cards}</div>
        <h2>Change proposals</h2><div class="grid">{proposal_cards}</div></main></body></html>"""
        encoded = body.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode())
        action = values.get("action", [""])[0]
        try:
            if action == "sync":
                count = self.engine.sync()
                observations = self.engine.triage()
                self.__class__.notice = f"Synced {count} new signal(s); {len(observations)} observation theme(s) are actionable."
            elif action == "select":
                observation_id = int(values["observation_id"][0])
                self.engine.select(observation_id)
                self.__class__.notice = f"Selected observation {observation_id}."
            elif action == "propose":
                proposal = self.engine.propose(int(values["observation_id"][0]))
                self.__class__.notice = f"Proposal {proposal['id']} was generated and validated in its sandbox."
            elif action == "approve":
                proposal_id = values["proposal_id"][0]
                self.engine.approve(proposal_id)
                self.__class__.notice = f"Approved proposal {proposal_id}."
            elif action == "reject":
                proposal_id = values["proposal_id"][0]
                self.engine.reject(proposal_id)
                self.__class__.notice = f"Rejected proposal {proposal_id}."
            elif action == "apply":
                proposal_id = values["proposal_id"][0]
                rollback = self.engine.apply(proposal_id)
                self.__class__.notice = f"Applied {proposal_id}. Roll back to {rollback} if its metrics regress."
            else:
                raise ValueError(f"Unknown action: {action}")
        except Exception as error:
            self.__class__.error = str(error)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def _observation_card(self, item: dict) -> str:
        evidence = item["evidence"]
        actions = ""
        if item["status"] == "candidate":
            actions = self._button("select", "Select", observation_id=item["id"])
        if item["status"] == "selected":
            actions = self._button("propose", "Create sandbox proposal", observation_id=item["id"])
        samples = "".join(f"<li>{html.escape(str(value))}</li>" for value in evidence.get("samples", []))
        return f"""<article class="card"><div class="row"><div><span class="pill">{html.escape(item['status'])}</span><h3>{html.escape(item['theme'].replace('_', ' ').title())}</h3><p>{html.escape(item['summary'])}</p><details><summary>Evidence</summary><ul>{samples}</ul></details></div><div><div class="score">{item['score']:.0f}</div><p class="muted">signals</p>{actions}</div></div></article>"""

    def _proposal_card(self, item: dict) -> str:
        actions = ""
        if item["status"] == "validated":
            actions = self._button("approve", "Approve", proposal_id=item["id"])
            actions += self._button("reject", "Reject", "secondary", proposal_id=item["id"])
        elif item["status"] == "approved":
            actions = self._button("apply", "Apply to app", proposal_id=item["id"])
        return f"""<article class="card"><div class="row"><div><span class="pill">{html.escape(item['status'])}</span><h3>{html.escape(item['id'])} · {html.escape(item['risk'])} risk</h3><p><strong>Hypothesis:</strong> {html.escape(item['hypothesis'])}</p><p><strong>Success metric:</strong> {html.escape(item['success_metric'])}</p></div><div>{actions}</div></div><details><summary>Validated diff</summary><pre>{html.escape(item['diff'])}</pre></details><details><summary>Validation output</summary><pre>{html.escape(item['validation'])}</pre></details></article>"""

    @staticmethod
    def _button(action: str, label: str, css_class: str = "", **values: object) -> str:
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(str(value))}">'
            for key, value in values.items()
        )
        return f'<form method="post"><input type="hidden" name="action" value="{html.escape(action)}">{hidden}<button class="{css_class}">{html.escape(label)}</button></form>'

    def log_message(self, format: str, *args: object) -> None:
        print(f"feedback-agent: {format % args}")


def serve(host: str = "127.0.0.1", port: int = 8100) -> None:
    DashboardHandler.engine = Engine()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Evolution control room is running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8100, type=int)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()

