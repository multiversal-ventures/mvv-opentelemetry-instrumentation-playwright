import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor


@pytest.fixture(scope="function")
def provider():
    return TracerProvider()


@pytest.fixture(scope="function")
def otel_exporter(provider: TracerProvider):
    exporter = InMemorySpanExporter()
    span_processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(span_processor)
    yield exporter
    exporter.clear()


@pytest.fixture(scope="function")
def instrumentor(provider: TracerProvider):
    instrumentor = PlaywrightInstrumentor()
    instrumentor._tracer_provider = provider

    try:
        yield instrumentor
    finally:
        instrumentor._uninstrument()
