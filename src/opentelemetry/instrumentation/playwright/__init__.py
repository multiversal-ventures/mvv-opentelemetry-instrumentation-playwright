import inspect
from collections.abc import Callable, Collection
from contextlib import ExitStack
from functools import wraps
from typing import Any, ParamSpec, Type, TypedDict, TypeVar, Unpack, override
from unittest.mock import patch

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.metrics import MeterProvider, get_meter_provider
from opentelemetry.trace import Tracer, TracerProvider, get_tracer_provider
from opentelemetry.util.types import Attributes

from .targets import METHODS, AttrConstructor

__all__ = ["PlaywrightInstrumentor"]
__version__ = "0.1.0"


class _InstrumentationArgs(TypedDict, total=False):
    tracer_provider: TracerProvider
    meter_provider: MeterProvider


_P = ParamSpec("_P")
_Ret = TypeVar("_Ret")


class PlaywrightInstrumentor(BaseInstrumentor):
    def __init__(self):
        self._exit_stack = ExitStack()
        self._tracer_provider: TracerProvider = get_tracer_provider()
        self._meter_provider: MeterProvider = get_meter_provider()

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ["playwright~=1.52.0"]

    @override
    def _instrument(self, **kwargs: Unpack[_InstrumentationArgs]):
        if tp := kwargs.get("tracer_provider"):
            self._tracer_provider = tp
        if mp := kwargs.get("meter_provider"):
            self._meter_provider = mp

        for parent, methods in METHODS.items():
            for method, attrs in methods:
                self._patch(parent, method, attrs)

    @override
    def _uninstrument(self, **kwargs: Any):
        # Note: We use pop_all() so we can call all destructors and reset the
        # instrumentor back to a usable state.
        self._exit_stack.pop_all().close()

    def _patch(self, parent: Type, method: str, attrs: dict[str, AttrConstructor]):
        """Patches a method on a Playwright class to add OpenTelemetry instrumentation.

        This is the core instrumentation function that:
        1. Gets the original method from the parent class
        2. Creates a wrapper that starts a new span before calling the original method
        3. Patches the original method with the wrapper using unittest.mock.patch

        The wrapper will:
        - Create a span named "{parent_class}:{method_name}"
        - Extract attributes from the method arguments based on the attrs dict
        - Call the original method within the span context
        - Handle both sync and async methods automatically

        Args:
            parent: The Playwright class containing the method to patch
            method: The name of the method to patch
            attrs: A dict mapping argument names to functions that convert the arg value
                  to an OpenTelemetry attribute value
        """
        func = getattr(parent, method)
        assert isinstance(func, Callable)
        get_attrs = _attr_maker(func, attrs)
        span_name = _type_name(parent) + ":" + func.__name__

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with self.tracer.start_as_current_span(
                name=span_name,
                attributes=get_attrs(*args, **kwargs),
            ):
                return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with self.tracer.start_as_current_span(
                name=span_name,
                attributes=get_attrs(*args, **kwargs),
            ):
                return await func(*args, **kwargs)

        wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

        self._exit_stack.enter_context(patch.object(parent, method, wrapper))

    @property
    def tracer(self) -> Tracer:
        return self._tracer_provider.get_tracer(
            __name__,
            __version__,
        )


def _attr_maker(
    func: Callable, attributes: dict[str, AttrConstructor]
) -> Callable[..., Attributes]:
    """
    Get a callable which, when called with the same arguments as the original
    function, returns a dictionary of attributes to attach to the span.

    The attributes are a dictionary of attribute name to a callable which takes
    the value of the attribute and returns an AttributeValue.
    """
    signature = inspect.signature(func)

    for attr_name in attributes:
        assert (
            attr_name in signature.parameters
        ), f"Argument '{attr_name}' not found in {func.__name__}{signature}"

    def maker(*args: Any, **kwargs: Any) -> Attributes:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        attrs: Attributes = {}

        for name, constructor in attributes.items():
            value = bound.arguments[name]
            if value is None:
                continue
            attrs[name] = constructor(value)

        return attrs

    return maker


def _type_name(ty: Type) -> str:
    return f"{ty.__module__}.{ty.__qualname__}"
