from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import pytest
from opentelemetry.context import Context
from opentelemetry.metrics import (
    CallbackT,
    Counter,
    Histogram,
    Meter,
    MeterProvider,
    ObservableCounter,
    ObservableGauge,
    ObservableUpDownCounter,
    UpDownCounter,
)
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util.types import Attributes

from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor


@pytest.fixture(scope="function")
def tracer_provider():
    return TracerProvider()


@pytest.fixture(scope="function")
def otel_exporter(tracer_provider: TracerProvider):
    exporter = InMemorySpanExporter()
    span_processor = SimpleSpanProcessor(exporter)
    tracer_provider.add_span_processor(span_processor)
    yield exporter
    exporter.clear()


class Reporter(Protocol):
    def __call__(
        self,
        amount: int | float,
        attributes: Attributes | None = None,
    ) -> None: ...


class InMemoryCounter(Counter):
    def __init__(self, reporter: Reporter):
        self._reporter = reporter

    def add(
        self,
        amount: int | float,
        attributes: Attributes | None = None,
        context: Context | None = None,
    ) -> None:
        self._reporter(amount, attributes)


@dataclass
class DataPoint:
    value: int | float
    attributes: Attributes


@dataclass
class DataPoints:
    name: str
    unit: str | None
    description: str | None
    values: list[DataPoint]


class InMemoryHistogram(Histogram):
    def __init__(self, reporter: Reporter):
        self._reporter = reporter

    def record(
        self,
        amount: int | float,
        attributes: Attributes | None = None,
        context: Context | None = None,
    ) -> None:
        self._reporter(amount, attributes)


class InMemoryMeter(Meter):
    def __init__(
        self,
        parent: "InMemoryMeterProvider",
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
    ):
        super().__init__(name, version, schema_url)
        self._meter_provider = parent

    def _reporter(
        self, name: str, unit: str | None, description: str | None
    ) -> Reporter:
        values: list[DataPoint] = []
        data_points = DataPoints(name, unit, description, values)
        self._meter_provider.data_points.append(data_points)

        def reporter(
            amount: int | float,
            attributes: Attributes | None = None,
            context: Context | None = None,
        ) -> None:
            values.append(DataPoint(amount, attributes))

        return reporter

    def create_counter(
        self, name: str, unit: str | None = None, description: str | None = None
    ) -> Counter:
        return InMemoryCounter(self._reporter(name, unit, description))

    def create_up_down_counter(
        self, name: str, unit: str | None = None, description: str | None = None
    ) -> UpDownCounter:
        raise NotImplementedError()

    def create_observable_counter(
        self,
        name: str,
        callbacks: Sequence[CallbackT] | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> ObservableCounter:
        raise NotImplementedError()

    def create_histogram(
        self,
        name: str,
        unit: str | None = None,
        description: str | None = None,
        *,
        explicit_bucket_boundaries_advisory: Sequence[float] | None = None,
    ) -> Histogram:
        return InMemoryHistogram(self._reporter(name, unit, description))

    def create_observable_gauge(
        self,
        name: str,
        callbacks: Sequence[CallbackT] | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> ObservableGauge:
        raise NotImplementedError()

    def create_observable_up_down_counter(
        self,
        name: str,
        callbacks: Sequence[CallbackT] | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> ObservableUpDownCounter:
        raise NotImplementedError()


class InMemoryMeterProvider(MeterProvider):
    def __init__(self):
        super().__init__()
        self.data_points: list[DataPoints] = []

    def force_flush(self):
        pass

    def get_meter(
        self,
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> Meter:
        return InMemoryMeter(self, name, version, schema_url)


@pytest.fixture(scope="function")
def otel_meter_provider():
    return InMemoryMeterProvider()


@pytest.fixture(scope="function")
def instrumentor(
    tracer_provider: TracerProvider, otel_meter_provider: InMemoryMeterProvider
):
    instrumentor = PlaywrightInstrumentor(tracer_provider, otel_meter_provider)

    try:
        yield instrumentor
    finally:
        instrumentor._uninstrument()
