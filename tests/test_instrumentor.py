import time
import tomllib
from pathlib import Path
from typing import Callable

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor

from .conftest import DataPoint, DataPoints, InMemoryMeterProvider

ROOT_DIR = next(p for p in Path(__file__).parents if p.joinpath("uv.lock").exists())


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


def test_trace_a_method(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    instrumentor._patch(DummyClass, "dummy_func", {"a": str})

    dummy = DummyClass()
    dummy.dummy_func("a", 1)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "tests.test_instrumentor.DummyClass:dummy_func"
    assert span.attributes == {"a": "a"}


def test_invalid_attrs_raise_errors(instrumentor: PlaywrightInstrumentor):
    with pytest.raises(AssertionError):
        instrumentor._patch(DummyClass, "dummy_func", {"c": str})


@pytest.mark.asyncio
async def test_trace_an_async_method(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    instrumentor._patch(DummyClass, "dummy_func_async", {"a": str})

    dummy = DummyClass()
    await dummy.dummy_func_async("a", 1)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "tests.test_instrumentor.DummyClass:dummy_func_async"
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


def test_trace_sync_context_manager(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    class DummySyncContextManager:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    instrumentor._patch_context_manager(DummySyncContextManager)
    with DummySyncContextManager():
        pass
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name.endswith(":__enter__")
    assert span.status.status_code == StatusCode.UNSET


def test_trace_sync_context_manager_error(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    class DummySyncContextManager:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    instrumentor._patch_context_manager(DummySyncContextManager)
    otel_exporter.clear()
    try:
        with DummySyncContextManager():
            raise ValueError("fail")
    except ValueError:
        pass
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is not None and "fail" in span.status.description


@pytest.mark.asyncio
async def test_trace_async_context_manager(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    class DummyAsyncContextManager:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    instrumentor._patch_async_context_manager(DummyAsyncContextManager)
    async with DummyAsyncContextManager():
        pass
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name.endswith(":__aenter__")
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.asyncio
async def test_trace_async_context_manager_error(
    instrumentor: PlaywrightInstrumentor, otel_exporter: InMemorySpanExporter
):
    class DummyAsyncContextManager:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    instrumentor._patch_async_context_manager(DummyAsyncContextManager)
    otel_exporter.clear()
    try:
        async with DummyAsyncContextManager():
            raise ValueError("fail async")
    except ValueError:
        pass
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert (
        span.status.description is not None and "fail async" in span.status.description
    )


@pytest.mark.asyncio
async def test_metrics_emitted_on_async_method_calls(
    instrumentor: PlaywrightInstrumentor,
    otel_meter_provider: InMemoryMeterProvider,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(time, "monotonic", monotonic())
    instrumentor._patch(DummyClass, "dummy_func_async", {"a": str})

    dummy = DummyClass()
    await dummy.dummy_func_async("a", 1)

    data_points = [dp for dp in otel_meter_provider.data_points if dp.values]

    assert data_points == [
        DataPoints(
            name="playwright.method.calls",
            unit="1",
            description="Number of Playwright method calls",
            values=[
                DataPoint(
                    value=1,
                    attributes={
                        "class": "tests.test_instrumentor.DummyClass",
                        "method": "dummy_func_async",
                        "sync_async": "async",
                    },
                )
            ],
        ),
        DataPoints(
            name="playwright.method.duration",
            unit="ms",
            description="Duration of Playwright method calls",
            values=[
                DataPoint(
                    value=1000,
                    attributes={
                        "class": "tests.test_instrumentor.DummyClass",
                        "method": "dummy_func_async",
                        "sync_async": "async",
                        "success": True,
                    },
                )
            ],
        ),
    ]


def test_metrics_emitted_on_sync_method_calls(
    instrumentor: PlaywrightInstrumentor,
    otel_meter_provider: InMemoryMeterProvider,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(time, "monotonic", monotonic())
    instrumentor._patch(DummyClass, "dummy_func", {"a": str})

    dummy = DummyClass()
    dummy.dummy_func("a", 1)

    data_points = [dp for dp in otel_meter_provider.data_points if dp.values]

    assert data_points == [
        DataPoints(
            name="playwright.method.calls",
            unit="1",
            description="Number of Playwright method calls",
            values=[
                DataPoint(
                    value=1,
                    attributes={
                        "class": "tests.test_instrumentor.DummyClass",
                        "method": "dummy_func",
                        "sync_async": "sync",
                    },
                )
            ],
        ),
        DataPoints(
            name="playwright.method.duration",
            unit="ms",
            description="Duration of Playwright method calls",
            values=[
                DataPoint(
                    value=1000,
                    attributes={
                        "class": "tests.test_instrumentor.DummyClass",
                        "method": "dummy_func",
                        "sync_async": "sync",
                        "success": True,
                    },
                )
            ],
        ),
    ]


def monotonic() -> Callable[[], float]:
    counter = 0

    def _monotonic():
        nonlocal counter
        counter += 1
        return counter

    return _monotonic
