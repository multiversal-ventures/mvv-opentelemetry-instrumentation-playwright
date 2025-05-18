from collections.abc import Iterable
from typing import Any

import playwright.async_api
import playwright.sync_api
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from opentelemetry.util.types import Attributes
from pytest_insta import SnapshotFixture

from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor


def playwright_available():
    try:
        with playwright.sync_api.sync_playwright() as p:
            with p.chromium.launch(headless=True) as _:
                return True
    except Exception:
        return False


requires_playwright = pytest.mark.skipif(
    not playwright_available(), reason="playwright not installed"
)


@requires_playwright
def test_sync(
    otel_exporter: InMemorySpanExporter,
    instrumentor: PlaywrightInstrumentor,
    snapshot: SnapshotFixture,
):
    instrumentor._instrument()

    with playwright.sync_api.sync_playwright() as p:
        with p.chromium.launch(headless=True) as b:
            with b.new_page(user_agent="test", is_mobile=False) as page:
                _ = page.title()

    assert snapshot("json") == spans(otel_exporter.get_finished_spans())


@requires_playwright
@pytest.mark.asyncio
async def test_async(
    otel_exporter: InMemorySpanExporter,
    instrumentor: PlaywrightInstrumentor,
    snapshot: SnapshotFixture,
):
    instrumentor._instrument()

    async with playwright.async_api.async_playwright() as p:
        async with await p.chromium.launch(headless=True) as browser:
            async with await browser.new_page(
                user_agent="test", is_mobile=False
            ) as page:
                _ = await page.title()

    assert snapshot("json") == spans(otel_exporter.get_finished_spans())


@requires_playwright
def test_sync_context_manager_with_error(
    otel_exporter: InMemorySpanExporter,
    instrumentor: PlaywrightInstrumentor,
    snapshot: SnapshotFixture,
):
    instrumentor._instrument()

    with playwright.sync_api.sync_playwright() as p:
        with pytest.raises(ValueError):
            with p.chromium.launch(headless=True):
                raise ValueError("An error occurred")

    assert snapshot("json") == spans(otel_exporter.get_finished_spans())


@requires_playwright
@pytest.mark.asyncio
async def test_async_context_manager_with_error(
    otel_exporter: InMemorySpanExporter,
    instrumentor: PlaywrightInstrumentor,
    snapshot: SnapshotFixture,
):
    instrumentor._instrument()

    async with playwright.async_api.async_playwright() as p:
        with pytest.raises(ValueError):
            async with await p.chromium.launch(headless=True):
                raise ValueError("An error occurred")

    assert snapshot("json") == spans(otel_exporter.get_finished_spans())


def spans(spans: Iterable[ReadableSpan]) -> list[dict[str, Any]]:
    return [
        {
            "name": span.name,
            "status": (
                {
                    "status_code": span.status.status_code.name,
                    "description": span.status.description,
                }
                if span.status.status_code != StatusCode.UNSET
                else None
            ),
            "attributes": {k: v for k, v in (span.attributes or {}).items()},
        }
        for span in sorted(spans, key=lambda s: s.start_time or 0)
    ]
