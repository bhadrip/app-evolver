from __future__ import annotations

import argparse
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import Engine


STYLE = """
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#172d28;background:#f4f3ed;--ink:#172d28;--muted:#64746f;--line:#d7ded9;--green:#246a50;--green-soft:#e3efd9;--paper:#fff;--dark:#15362d;--warn:#fff0d2;--bad:#ffe3db}*{box-sizing:border-box}
body{margin:0}header{padding:26px max(5vw,24px) 0;background:var(--dark);color:white}header h1{margin:0 0 5px;font-family:Georgia,serif;font-size:2.25rem}header p{margin:0;color:#c9ded5}.nav{display:flex;gap:6px;margin-top:22px}.nav a{padding:12px 15px;color:#c9ded5;text-decoration:none;border-radius:10px 10px 0 0;font-weight:700}.nav a.active{background:#f4f3ed;color:var(--ink)}
main{width:min(1180px,90vw);margin:34px auto 80px}.toolbar,.policy,.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.policy{margin:14px 0 26px}.pill{display:inline-flex;padding:6px 10px;border-radius:99px;background:var(--green-soft);font-size:.82rem;font-weight:750}.pill.off{background:#e6e8e7;color:var(--muted)}.pill.warn{background:var(--warn)}
h2{font-family:Georgia,serif;font-size:1.8rem;margin:42px 0 16px}h3{margin:10px 0 6px}.grid{display:grid;gap:15px}.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 10px 30px #173d3208}.row{display:flex;justify-content:space-between;gap:20px;align-items:start}.muted{color:var(--muted)}.score{font-size:1.4rem;font-weight:800}
button,.button{display:inline-block;background:var(--green);color:white;border:0;border-radius:99px;padding:10px 15px;font:inherit;font-weight:750;cursor:pointer;text-decoration:none}button.secondary{background:white;color:var(--ink);border:1px solid #9baba4}button:disabled{cursor:not-allowed;opacity:.48}form.inline{display:inline}.field{display:grid;gap:6px;margin-top:14px}.field label{font-weight:750}.field input,.field textarea{width:100%;border:1px solid #aebbb5;border-radius:10px;padding:10px 12px;background:white;color:var(--ink);font:inherit}.field textarea{min-height:105px;resize:vertical}.check{display:flex;gap:9px;align-items:center;margin:14px 0}.check input{width:18px;height:18px}
pre{white-space:pre-wrap;overflow:auto;background:#15241f;color:#d8f3e8;padding:16px;border-radius:12px;max-height:360px}.error,.success,.note{padding:14px;border-radius:12px}.error{background:var(--bad);border:1px solid #d88870}.success{background:var(--green-soft);border:1px solid #8bab63}.note{background:var(--warn);border:1px solid #d9b96f}.pipeline{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding:4px 0 10px}.agent-node{min-width:190px;flex:1;background:white;border:1px solid var(--line);border-radius:14px;padding:16px}.agent-node.disabled{opacity:.5}.connector{display:grid;place-items:center;min-width:34px;color:var(--green);font-size:1.4rem}.agent-node .stage{color:var(--green);font-size:.75rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.agent-node p{color:var(--muted);font-size:.86rem;margin:6px 0 0}
.activity{position:relative;padding-left:28px}.activity:before{content:"";position:absolute;left:8px;top:10px;bottom:10px;width:2px;background:var(--line)}.activity-item{position:relative;background:white;border-bottom:1px solid var(--line);padding:14px 16px;margin-bottom:10px;border-radius:12px}.activity-item:before{content:"";position:absolute;left:-25px;top:21px;width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px #f4f3ed}.activity-item.failed:before{background:#b84932}.activity-head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.io{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}.io p{margin:4px 0}.empty{padding:26px;text-align:center;color:var(--muted);border:1px dashed #aebbb5;border-radius:14px}details{margin-top:12px}summary{cursor:pointer;font-weight:700}
@media(max-width:760px){.grid.two,.io{grid-template-columns:1fr}.row{flex-direction:column}.pipeline{flex-direction:column;overflow:visible}.connector{transform:rotate(90deg);min-height:30px}.agent-node{min-width:0}.nav{overflow:auto}}
"""


class DashboardHandler(BaseHTTPRequestHandler):
    engine: Engine
    notice = ""
    error = ""

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path != "/":
            return self.send_error(HTTPStatus.NOT_FOUND)
        view = parse_qs(request.query).get("view", ["control"])[0]
        if view not in {"control", "agents", "activity"}:
            view = "control"
        message = self._message()
        content = {
            "control": self._control_view,
            "agents": self._agents_view,
            "activity": self._activity_view,
        }[view]()
        nav = "".join(
            f'<a class="{"active" if view == key else ""}" href="/?view={key}">{label}</a>'
            for key, label in (("control", "Control room"), ("agents", "Agent team"), ("activity", "Activity"))
        )
        body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>App Evolver</title><style>{STYLE}</style></head>
        <body><header><h1>App Evolver</h1><p>Compose agents. Observe decisions. Deliver through pull requests.</p><nav class="nav">{nav}</nav></header>
        <main>{message}{content}</main></body></html>"""
        encoded = body.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        length = min(int(self.headers.get("Content-Length", "0")), 32_768)
        values = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
        action = values.get("action", [""])[0]
        redirect_view = values.get("view", ["control"])[0]
        try:
            if action == "sync":
                count = self.engine.sync()
                observations = self.engine.triage()
                self.__class__.notice = f"Synced {count} new signals; {len(observations)} opportunity themes are ready."
            elif action == "select":
                observation_id = int(values["observation_id"][0])
                self.engine.select(observation_id)
                self.__class__.notice = f"Selected observation {observation_id}."
            elif action == "prepare_pr":
                pull_request = self.engine.prepare_pull_request(int(values["observation_id"][0]))
                self.__class__.notice = f"{pull_request['branch']} passed checks and is ready to open as a PR."
            elif action == "open_pr":
                url = self.engine.open_pull_request(values["pull_request_id"][0])
                self.__class__.notice = f"Opened pull request: {url}"
            elif action == "save_agent":
                self.engine.agents.update(
                    values["agent_id"][0],
                    name=values["name"][0],
                    enabled=values.get("enabled", [""])[0] == "on",
                    model=values["model"][0],
                    instructions=values["instructions"][0],
                )
                self.__class__.notice = f"Saved {values['name'][0]}."
            else:
                raise ValueError(f"Unknown action: {action}")
        except Exception as error:
            self.__class__.error = str(error)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?view={redirect_view}")
        self.end_headers()

    def _control_view(self) -> str:
        observations = self.engine.store.observations()
        pull_requests = self.engine.store.pull_requests()
        observation_cards = "".join(self._observation_card(item) for item in observations)
        pr_cards = "".join(self._pull_request_card(item) for item in pull_requests)
        hitl = self.engine.constitution["humanInTheLoop"]["observationSelection"]
        remote_ready = self.engine.pull_request_remote_ready()
        return f"""
        <h2>Evolution pipeline</h2>{self._pipeline()}
        <div class="policy"><span class="pill">Observation selection: {html.escape(hitl)}</span><span class="pill">Delivery: pull request only</span><span class="pill {'off' if not remote_ready else ''}">GitHub remote: {'ready' if remote_ready else 'not configured'}</span></div>
        <div class="toolbar"><form class="inline" method="post"><input type="hidden" name="action" value="sync"><input type="hidden" name="view" value="control"><button>Sync & triage</button></form><a class="button" href="/?view=activity">Observe agent behavior</a></div>
        <h2>Candidate observations</h2><div class="grid">{observation_cards or '<div class="empty">No observations yet. Sync the mock source to begin.</div>'}</div>
        <h2>Pull requests</h2><div class="grid">{pr_cards or '<div class="empty">No PR branches have been prepared.</div>'}</div>
        """

    def _agents_view(self) -> str:
        cards = "".join(self._agent_editor(agent) for agent in self.engine.agents.all())
        return f"""
        <h2>Agent composition</h2>{self._pipeline()}
        <p class="note">This prototype uses deterministic adapters. Names, instructions, and enabled state are persisted now; model-backed adapters can later consume the same instructions without changing the orchestration or PR workflow.</p>
        <div class="grid two">{cards}</div>
        """

    def _activity_view(self) -> str:
        activities = self.engine.store.activities()
        items = "".join(self._activity_item(item) for item in activities)
        completed = sum(item["status"] == "completed" for item in activities)
        failed = sum(item["status"] == "failed" for item in activities)
        return f"""
        <div class="row"><div><h2>Agent activity</h2><p class="muted">Inputs, outputs, status, duration, and shared run IDs make the composite observable.</p></div><div class="policy"><span class="pill">{completed} completed</span><span class="pill {'warn' if failed else 'off'}">{failed} failed</span></div></div>
        <div class="activity">{items or '<div class="empty">Run Sync & triage or prepare a PR to generate activity.</div>'}</div>
        """

    def _pipeline(self) -> str:
        nodes = []
        for index, agent in enumerate(self.engine.agents.all()):
            if index:
                nodes.append('<div class="connector" aria-hidden="true">→</div>')
            state = "enabled" if agent["enabled"] else "disabled"
            nodes.append(
                f'<div class="agent-node {"" if agent["enabled"] else "disabled"}"><span class="stage">{html.escape(agent["stage"])}</span><h3>{html.escape(agent["name"])}</h3><span class="pill {"" if agent["enabled"] else "off"}">{state}</span><p>{html.escape(agent["access"])}</p></div>'
            )
        nodes.append('<div class="connector" aria-hidden="true">→</div><div class="agent-node"><span class="stage">Deliver</span><h3>Pull request</h3><span class="pill">existing primitive</span><p>CI · review · merge · revert</p></div>')
        return f'<div class="pipeline" aria-label="Configured agent pipeline">{"".join(nodes)}</div>'

    def _observation_card(self, item: dict) -> str:
        evidence = item["evidence"]
        actions = ""
        if item["status"] == "candidate":
            actions = self._button("select", "Select", observation_id=item["id"])
        elif item["status"] == "selected":
            actions = self._button("prepare_pr", "Prepare PR branch", observation_id=item["id"])
        samples = "".join(f"<li>{html.escape(str(value))}</li>" for value in evidence.get("samples", []))
        return f"""<article class="card"><div class="row"><div><span class="pill">{html.escape(item['status'].replace('_', ' '))}</span><h3>{html.escape(item['theme'].replace('_', ' ').title())}</h3><p>{html.escape(item['summary'])}</p><details><summary>Evidence</summary><ul>{samples}</ul></details></div><div><div class="score">{item['score']:.0f}</div><p class="muted">signals</p>{actions}</div></div></article>"""

    def _pull_request_card(self, item: dict) -> str:
        remote_ready = self.engine.pull_request_remote_ready(item["app_id"])
        if item["pr_url"]:
            action = f'<a class="button" href="{html.escape(item["pr_url"])}">View PR #{item["pr_number"]}</a>'
        elif remote_ready:
            action = self._button("open_pr", "Open draft PR", pull_request_id=item["id"])
        else:
            action = '<button disabled>Open PR</button><p class="muted">Add an origin remote to enable</p>'
        return f"""<article class="card"><div class="row"><div><span class="pill">{html.escape(item['status'].replace('_', ' '))}</span><h3>{html.escape(item['branch'])}</h3><p><strong>Hypothesis:</strong> {html.escape(item['hypothesis'])}</p><p><strong>Success metric:</strong> {html.escape(item['success_metric'])}</p></div><div>{action}</div></div><details><summary>PR diff</summary><pre>{html.escape(item['diff'])}</pre></details><details><summary>Checks</summary><pre>{html.escape(item['validation'])}</pre></details></article>"""

    def _agent_editor(self, agent: dict) -> str:
        checked = " checked" if agent["enabled"] else ""
        return f"""<article class="card"><span class="pill">{html.escape(agent['stage'])}</span><h3>{html.escape(agent['name'])}</h3><p class="muted">{html.escape(agent['id'])} · {html.escape(agent['access'])}</p><form method="post"><input type="hidden" name="action" value="save_agent"><input type="hidden" name="view" value="agents"><input type="hidden" name="agent_id" value="{html.escape(agent['id'])}"><label class="check"><input type="checkbox" name="enabled"{checked}> Enabled in pipeline</label><div class="field"><label>Name<input name="name" value="{html.escape(agent['name'])}" required></label></div><div class="field"><label>Runtime adapter<input name="model" value="{html.escape(agent['model'])}" readonly></label></div><div class="field"><label>Instructions<textarea name="instructions" required>{html.escape(agent['instructions'])}</textarea></label></div><button>Save agent</button></form></article>"""

    def _activity_item(self, item: dict) -> str:
        return f"""<article class="activity-item {html.escape(item['status'])}"><div class="activity-head"><div><span class="pill">{html.escape(item['stage'])}</span><strong> {html.escape(item['agent_name'])}</strong></div><span class="muted">run {html.escape(item['run_id'])} · {item['duration_ms']} ms</span></div><div class="io"><div><strong>Input</strong><p>{html.escape(item['input_summary'])}</p></div><div><strong>Output · {html.escape(item['status'])}</strong><p>{html.escape(item['output_summary'])}</p></div></div></article>"""

    def _message(self) -> str:
        message = ""
        if self.error:
            message = f'<p class="error" role="alert">{html.escape(self.error)}</p>'
        elif self.notice:
            message = f'<p class="success" role="status">{html.escape(self.notice)}</p>'
        self.__class__.notice = self.__class__.error = ""
        return message

    @staticmethod
    def _button(action: str, label: str, **values: object) -> str:
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(str(value))}">'
            for key, value in values.items()
        )
        return f'<form class="inline" method="post"><input type="hidden" name="action" value="{html.escape(action)}"><input type="hidden" name="view" value="control">{hidden}<button>{html.escape(label)}</button></form>'

    def log_message(self, format: str, *args: object) -> None:
        print(f"app-evolver: {format % args}")


def serve(host: str = "127.0.0.1", port: int = 8100) -> None:
    DashboardHandler.engine = Engine()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"App Evolver is running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8100, type=int)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
