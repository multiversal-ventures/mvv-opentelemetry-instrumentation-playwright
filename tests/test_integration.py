from collections.abc import Iterable
from typing import Any

import playwright.async_api
import playwright.sync_api
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
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
    # First build a mapping of span ID to span info
    span_map = {}
    for span in spans:
        assert span.context is not None
        span_map[span.context.span_id] = {
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
            "children": [],
            "start_time": span.start_time or 0,
            "parent_id": span.parent.span_id if span.parent else None,
        }

    # Build trees by connecting parents and children
    roots = []
    for span_id, info in span_map.items():
        if info["parent_id"] is None:
            roots.append(info)
        else:
            parent = span_map.get(info["parent_id"])
            if parent:
                parent["children"].append(info)

    # Sort roots and children by start time
    def sort_and_cleanup(span_info):
        span_info["children"].sort(key=lambda x: x["start_time"])
        for child in span_info["children"]:
            sort_and_cleanup(child)
        # Remove temporary fields used for sorting/linking
        del span_info["start_time"]
        del span_info["parent_id"]
        # Only include non-empty fields
        if not span_info["attributes"]:
            del span_info["attributes"]
        if not span_info["children"]:
            del span_info["children"]
        if span_info["status"] is None:
            del span_info["status"]

    roots.sort(key=lambda x: x["start_time"])
    for info in roots:
        sort_and_cleanup(info)

    return roots
