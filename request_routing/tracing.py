"""OpenTelemetry tracing with a local file exporter, and a live view of it.

The instrumentation is real; only the destination differs. In production, swap the exporter for
`OTLPSpanExporter` to send spans to a collector (Logfire, Langfuse, Datadog, ...).

Follow the agents live in a second terminal: `uv run python -m request_routing.tracing`.
"""

import json
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from pydantic_ai import Agent, InstrumentationSettings
from rich.console import Console
from rich.markup import escape

from request_routing.config import TRACES_DIR


class JsonlSpanExporter(SpanExporter):
    """Write each finished span as one JSON line to `<directory>/<trace_id>.jsonl`."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            path = self.directory / f"{span.context.trace_id:032x}.jsonl"
            with path.open("a", encoding="utf-8") as f:
                f.write(span.to_json(indent=None) + "\n")
        return SpanExportResult.SUCCESS


def configure_tracing(directory: Path, *, include_content: bool = True) -> None:
    """Instrument all agents. Set include_content=False to keep customer text out of traces."""
    provider = TracerProvider(resource=Resource.create({"service.name": "request-routing"}))
    provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(directory)))
    trace.set_tracer_provider(provider)
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, include_content=include_content))


def follow(directory: Path) -> None:
    """Print one line per finished step of every new trace, as the exporter writes them."""
    console = Console(highlight=False)
    offsets = {path: path.stat().st_size for path in directory.glob("*.jsonl")}  # only show new spans
    shown = set(offsets)  # traces that already have their separator (or predate the viewer)
    console.print(f"[dim]Following {directory}. Ctrl+C to stop.[/]")
    while True:
        for path in sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            with path.open("rb") as f:
                f.seek(offsets.get(path, 0))
                chunk = f.read()
            complete = chunk[: chunk.rfind(b"\n") + 1]
            offsets[path] = offsets.get(path, 0) + len(complete)
            for line in complete.decode("utf-8").splitlines():
                if text := _describe(json.loads(line)):
                    if path not in shown:  # traces without agent steps (e.g. MCP connection setup) get no separator
                        console.rule(f"[dim]new message · trace {path.stem[:8]}[/]")
                        shown.add(path)
                    console.print(text)
        time.sleep(0.2)


def _describe(span: dict) -> str | None:
    name, attributes = span["name"], span.get("attributes", {})
    started, ended = (datetime.fromisoformat(span[key]) for key in ("start_time", "end_time"))
    prefix = f"[dim]{ended.astimezone():%H:%M:%S} {(ended - started).total_seconds():5.1f}s[/]"
    agent = attributes.get("gen_ai.agent.name", "")

    if name.startswith("chat "):
        tokens = f"{attributes.get('gen_ai.usage.input_tokens', 0)}+{attributes.get('gen_ai.usage.output_tokens', 0)}"
        line = f"{prefix}  model call      [magenta]{agent}[/] [dim]{tokens} tokens[/]"
        if agent == "router" and (message := _last_user_message(attributes)):
            line = f"[dim]{ended.astimezone():%H:%M:%S}{'':7}[/]  [bold]customer[/]        {message}\n{line}"
        return line
    if name.startswith("execute_tool final_result"):
        return None  # output functions also run on every partial chunk while streaming; the outcome is shown below
    if name.startswith("execute_tool "):
        tool = attributes.get("gen_ai.tool.name", name.removeprefix("execute_tool "))
        args = _short(attributes.get("gen_ai.tool.call.arguments", ""), 60)
        if attributes.get("pydantic_ai.tool.deferral.name") == "ApprovalRequired":
            return f"{prefix}  tool            [cyan]{tool}[/] {args} [yellow]→ waiting for customer confirmation[/]"
        result = _result_summary(attributes.get("gen_ai.tool.call.result", ""))
        return f"{prefix}  tool            [cyan]{tool}[/] {args} [dim]→ {result}[/]"
    if name.startswith("tools/call "):
        return f"{prefix}  MCP             [cyan]{name}[/] [dim](bank systems process)[/]"
    if name.startswith("invoke_agent "):
        result = json.loads(attributes.get("final_result") or "{}")
        if agent == "router":
            summary = f"{result.get('handling')} · {result.get('intent')}"
            if handoff := result.get("handoff"):
                summary += f" · {handoff['ticket_id']} ({handoff['priority']}, {handoff['reason']})"
            return f"{prefix}  [bold green]outcome[/]         {summary}"
        return f"{prefix}  agent done      [magenta]{agent}[/] [dim]→ {result.get('status', '')}[/]"
    return None


def _last_user_message(attributes: dict) -> str | None:
    messages = json.loads(attributes.get("gen_ai.input.messages") or "[]")
    for message in reversed(messages):
        if message.get("role") == "user":
            return _short(
                " ".join(p.get("content", "") for p in message.get("parts", []) if p.get("type") == "text"), 100
            )
    return None


def _result_summary(raw: str) -> str:
    """Status plus reference or citations for structured results (FAQ answers, bank results); else a snippet."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict) and "status" in data:
        detail = data.get("reference") or ", ".join(data.get("citations", []))
        return escape(f"{data['status']} {detail}".strip())
    return _short(raw, 70)


def _short(value, limit: int) -> str:
    text = " ".join(str(value).split())
    return escape(text if len(text) <= limit else text[: limit - 1] + "…")


if __name__ == "__main__":
    try:
        follow(TRACES_DIR)
    except KeyboardInterrupt:
        pass
