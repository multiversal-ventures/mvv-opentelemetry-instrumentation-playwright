import functools
import inspect
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

import playwright.async_api
import playwright.sync_api
from opentelemetry.util.types import AttributeValue

AttrConstructor = Callable[[Any], AttributeValue]

# Runtime discovery of instrumentable methods and attribute constructors

_PRIMITIVES: set[Type] = {str, int, float, bool}
_CONVERTIBLE: dict[Type, Type] = {Path: str}


def _attr_constructor(annotation: Any) -> Type | None:
    if annotation in _PRIMITIVES:
        return annotation
    if (base := _CONVERTIBLE.get(annotation)) is not None:
        return base
    if typing.get_origin(annotation) is typing.Union:
        return _attr_constructor_for_union(annotation)
    return None


def _attr_constructor_for_union(annotation: Any) -> Type | None:
    assert typing.get_origin(annotation) is typing.Union
    args = [a for a in typing.get_args(annotation) if a != type(None)]
    if len(args) == 2 and type(None) in args:
        # Optional[T] -> T
        return _attr_constructor(args[0])
    constructors = [_attr_constructor(a) for a in args]
    constructors = [c for c in constructors if c is not None]
    if len(constructors) == 0:
        return None
    first, *rest = constructors
    return first if all(c == first for c in rest) else None


@dataclass(frozen=True, kw_only=True)
class Method:
    name: str
    attrs: Mapping[str, AttrConstructor]


def _discover_methods_for_type(
    target_type: Type,
) -> Sequence[Method]:
    discovered: list[Method] = []
    for member_name, member in inspect.getmembers(target_type):
        if not inspect.iscoroutinefunction(member) or member_name.startswith("_"):
            continue
        signature = inspect.signature(member)
        attrs: dict[str, AttrConstructor] = {}
        for param_name, param in signature.parameters.items():
            if param_name == "self" or param.annotation is inspect.Parameter.empty:
                continue
            constructor = _attr_constructor(param.annotation)
            if constructor is not None:
                attrs[param_name] = constructor
        discovered.append(Method(name=member_name, attrs=dict(sorted(attrs.items()))))

    discovered.sort(key=lambda m: m.name)
    return discovered


@functools.cache
def annotated_methods() -> dict[Type, Sequence[Method]]:
    """
    Get a mapping of Playwright classes to their instrumentable methods.
    """
    methods_map: dict[Type, Sequence[Method]] = {}
    async_targets = [
        playwright.async_api.BrowserType,
        playwright.async_api.Page,
        playwright.async_api.Browser,
        playwright.async_api.Frame,
        playwright.async_api.ElementHandle,
        playwright.async_api.Locator,
    ]
    for async_type in async_targets:
        discovered = _discover_methods_for_type(async_type)
        methods_map[async_type] = discovered
        # Mirror to sync API using the same class name
        sync_type = getattr(playwright.sync_api, async_type.__name__)
        assert isinstance(sync_type, type)
        methods_map[sync_type] = discovered
    return methods_map
