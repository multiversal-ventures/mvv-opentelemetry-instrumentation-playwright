import tomllib
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor

ROOT_DIR = next(p for p in Path(__file__).parents if p.joinpath("uv.lock").exists())


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


class DummyClass:
    def dummy_func(self, a: str, b: int):
        pass

    async def dummy_func_async(self, a: str, b: int):
        pass


def test_instrumented_version_is_in_sync_with_pyproject_toml(
    instrumentor: PlaywrightInstrumentor,
):
    with open(ROOT_DIR.joinpath("pyproject.toml"), "rb") as f:
        pyproject = tomllib.load(f)

    for dep in instrumentor.instrumentation_dependencies():
        assert dep in pyproject["project"]["dependencies"]


def test_instrumentation_is_valid(instrumentor: PlaywrightInstrumentor):
    # This would throw if we tried to instrument a method that doesn't exist,
    # or we try to record attributes that are not in the method signature.
    instrumentor.instrument()


def test_instrument_a_method(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    instrumentor._patch(DummyClass, "dummy_func", {"a": str})

    dummy = DummyClass()
    dummy.dummy_func("a", 1)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "test_instrumentor.DummyClass:dummy_func"
    assert span.attributes == {"a": "a"}


def test_invalid_attrs_raise_errors(instrumentor: PlaywrightInstrumentor):
    with pytest.raises(AssertionError):
        instrumentor._patch(DummyClass, "dummy_func", {"c": str})


@pytest.mark.asyncio
async def test_instrument_an_async_method(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    instrumentor._patch(DummyClass, "dummy_func_async", {"a": str})

    dummy = DummyClass()
    await dummy.dummy_func_async("a", 1)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "test_instrumentor.DummyClass:dummy_func_async"
    assert span.attributes == {"a": "a"}


def test_clear_instrumentation(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    dummy = DummyClass()

    # First, instrument the method and make sure we get a span
    instrumentor._patch(DummyClass, "dummy_func", {"a": str})
    dummy.dummy_func("a", 1)
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1

    # Then, clear the instrumentation and make sure we don't get any new spans
    instrumentor._uninstrument()
    dummy.dummy_func("a", 1)
    assert otel_exporter.get_finished_spans() == spans
