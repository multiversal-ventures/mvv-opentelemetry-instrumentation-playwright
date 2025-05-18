# OpenTelemetry Instrumentation for Playwright

Automatic tracing and metrics for your Playwright browser automation scripts
using OpenTelemetry.

This package supports both synchronous and asynchronous Playwright APIs,
enabling deep observability into your browser automation and testing workflows.

## Features

- **Automatic tracing** of Playwright browser, page, and element actions
- **Supports both sync and async Playwright APIs**
- **Rich span attributes** for method arguments and context
- **Easy integration** with OpenTelemetry SDKs and exporters
- **Customizable tracer and meter providers**

## Getting Started

First, add the `mvv-opentelemetry-instrumentation-playwright` package as a
dependency.

```console
uv add mvv-opentelemetry-instrumentation-playwright
```

If you haven't already, make sure Playwright is set up:

```console
uv run playwright install --with-deps
```

Then, instrument your application:

```python
from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor
import playwright.sync_api

# Instrument Playwright
PlaywrightInstrumentor().instrument()

with playwright.sync_api.sync_playwright() as p:
    with p.chromium.launch(headless=True) as browser:
        with browser.new_page(user_agent="test", is_mobile=False) as page:
            title = page.title()
            print("Page title:", title)
```

You can pass a custom tracer or meter provider:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor

provider = TracerProvider()
PlaywrightInstrumentor().instrument(tracer_provider=provider)
```

To uninstrument (remove all patches):

```python
from opentelemetry.instrumentation.playwright import PlaywrightInstrumentor

instrumentor = PlaywrightInstrumentor()
instrumentor.instrument()

# ...

instrumentor.uninstrument()
```

## Supported Playwright APIs

This package instruments a wide range of methods from the following Playwright
classes (sync and async):

- `BrowserType`
- `Browser`
- `Page`
- `Frame`
- `ElementHandle`
- `Locator`

Common actions like `launch`, `new_page`, `goto`, `click`, `type`, `screenshot`,
and many more are traced with relevant attributes.

See the [`targets.py`](src/opentelemetry/instrumentation/playwright/targets.py)
file for a full list of the methods that are instrumented, along with the
parameters that will be attached to the Open Telemetry span as parameters.

## License

This project is licensed under the MIT License. See the [LICENSE.md](LICENSE.md)
file for details.
