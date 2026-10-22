"""OpenTelemetry tracing with a local file exporter.

The instrumentation is real; only the destination differs. In production, swap the exporter for
`OTLPSpanExporter` to send spans to a collector (Logfire, Langfuse, Datadog, ...).
"""

from collections.abc import Sequence
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from pydantic_ai import Agent, InstrumentationSettings


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
