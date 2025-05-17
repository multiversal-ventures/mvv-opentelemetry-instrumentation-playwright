import inspect
import typing
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Type, Union

import black
import playwright.async_api
import pytest


@dataclass
class Target:
    type: Type
    exclude: Sequence[str] = ()

    @property
    def name(self) -> str:
        return self.type.__name__


@dataclass
class Attr:
    name: str
    type: Type


@dataclass
class Method:
    name: str
    attrs: Sequence[Attr]


@dataclass
class Instrumentation:
    module: str
    type_name: str
    methods: Sequence[Method]


TARGETS = [
    Target(playwright.async_api.BrowserType),
    Target(playwright.async_api.Page),
    Target(playwright.async_api.Browser),
    Target(playwright.async_api.Frame),
    Target(playwright.async_api.ElementHandle),
    Target(playwright.async_api.Locator),
]


def test_targets_list_is_up_to_date():
    """
    The Playwright API is massive, so instead of manually maintaining a list of
    methods to instrument, we'll use reflection and codegen to build it.

    In general, we only want to instrument "slow" functions that have
    side-effects. Once nice aspect of the async API is that these functions are
    all marked as `async` functions.

    From there, we can use type hints to figure out the arguments that we can
    attach to the span.

    Once we've done all of that, we'll generate a big `*.py` file which gets
    consumed by the instrumentor to do our monkeypatching.
    """
    methods_by_type = {target.name: methods(target) for target in TARGETS}

    instrumented = [
        Instrumentation(
            module=module,
            type_name=target.name,
            methods=methods_by_type[target.name],
        )
        for module in ["playwright.async_api", "playwright.sync_api"]
        for target in TARGETS
    ]

    rendered = render(instrumented)

    root_dir = next(p for p in Path(__file__).parents if p.joinpath("uv.lock").exists())
    targets_py = root_dir.joinpath(
        "src", "opentelemetry", "instrumentation", "playwright", "targets.py"
    )
    original_text = targets_py.read_text()
    expected = update_tagged_section(original_text, "METHODS", rendered)
    expected = black.format_str(expected, mode=black.Mode())
    ensure_file_contains(targets_py, expected)


def ensure_file_contains(path: Path, expected: str):
    src = path.read_text()
    if expected in src:
        return

    _ = path.write_text(expected)
    raise AssertionError(
        f'Updated "{path}" to contain "{expected}". Please commit the changes and re-run the test.'
    )


def update_tagged_section(text: str, tag: str, content: str) -> str:
    """
    Look for a section of text between `# START:{tag}` and `# END:{tag}`, and
    replace it with the given content.

    If no such section is found, append the content to the end of the text.
    """
    start_tag = f"# START:{tag}"
    end_tag = f"# END:{tag}"
    lines = text.splitlines()

    # Find the start and end indices of the tagged section
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == start_tag:
            start_idx = i
        elif line.strip() == end_tag:
            end_idx = i
            break

    # If we found a tagged section, replace it
    if start_idx >= 0 and end_idx >= 0:
        new_lines = lines[: start_idx + 1]
        new_lines.extend(content.splitlines())
        new_lines.extend(lines[end_idx:])
        return "\n".join(new_lines)

    # Otherwise append the content with tags
    lines.extend(["", start_tag, *content.splitlines(), end_tag])
    return "\n".join(lines)


def methods(target: Target) -> Sequence[Method]:
    all_methods: list[Method] = []

    for member_name, member in inspect.getmembers(target.type):
        if not inspect.iscoroutinefunction(member) or member_name.startswith("_"):
            continue

        signature = inspect.signature(member)
        attrs: list[Attr] = []

        for param_name, param in signature.parameters.items():
            if param_name == "self" or param.annotation is inspect.Parameter.empty:
                continue

            if constructor := attr_constructor(param.annotation):
                attrs.append(Attr(param_name, constructor))

        method = Method(member_name, sorted(attrs, key=lambda a: a.name))
        all_methods.append(method)

    return sorted(all_methods, key=lambda m: m.name)


primitives: set[Type] = {str, int, float, bool}
convertible: dict[Type, Type] = {
    Path: str,
}


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (str, str),
        (int, int),
        (float, float),
        (bool, bool),
        (Path, str),
        (Optional[str], str),
        (Union[str, type(None)], str),
        # Ambiguous, can't infer which constructor to use
        (Union[str, int], None),
    ],
)
def test_attr_constructor(annotation: Any, expected: Type | None):
    assert attr_constructor(annotation) == expected


def attr_constructor(annotation: Any) -> Type | None:
    if annotation in primitives:
        return annotation

    if base := convertible.get(annotation):
        return base

    if typing.get_origin(annotation) is Union:
        return attr_constructor_for_union(annotation)

    return None


def attr_constructor_for_union(annotation: Any) -> Type | None:
    assert typing.get_origin(annotation) is Union

    args = [a for a in typing.get_args(annotation) if a != type(None)]

    if len(args) == 2 and type(None) in args:
        # Treat Optional[T] as T
        return attr_constructor(args[0])

    constructors = [attr_constructor(a) for a in args]
    constructors = [c for c in constructors if c is not None]

    if len(constructors) == 0:
        return None

    first, *rest = constructors

    # Note: All variants of a union must use the same attribute constructor
    # otherwise it's ambiguous
    if all(c == first for c in rest):
        return first
    else:
        return None


class Renderer:
    def __init__(self):
        self.buffer: list[str] = []
        self.prefix: str = ""

    def _print(self, value: str):
        if self.buffer and self.buffer[-1] == "\n":
            self.buffer.append(self.prefix)

        self.buffer.append(value)

    def print(self, *values: str):
        for value in values:
            self._print(value)

    def println(self, *values: str):
        self.print(*values)
        self.newline()

    def newline(self):
        self.buffer.append("\n")

    @contextmanager
    def indent(self, indent: str = "     "):
        old_prefix = self.prefix
        self.prefix += indent
        try:
            yield
        finally:
            self.prefix = old_prefix

    def write(self, text: str):
        self.buffer.append(self.prefix + text)

    def finish(self) -> str:
        return "".join(self.buffer)


def render_instrumentation(r: Renderer, instrumentation: Instrumentation):
    r.println(instrumentation.module, ".", instrumentation.type_name, ": (")

    with r.indent():
        for method in instrumentation.methods:
            render_method(r, method)

    r.println("),")


def render_method(r: Renderer, method: Method):
    r.print("(")

    with r.indent():
        r.print('"', method.name, '", ')
        render_attrs(r, method.attrs)

    r.println("),")


def render_attrs(r: Renderer, attrs: Sequence[Attr]):
    r.print("{")

    with r.indent():
        for attr in attrs:
            render_attr(r, attr)
            r.print(", ")

    r.print("}")


def render_attr(r: Renderer, attr: Attr):
    r.print('"', attr.name, '": ', attr.type.__name__)


def render(instrumented: Sequence[Instrumentation]) -> str:
    r = Renderer()
    r.println(
        "METHODS: dict[Type, tuple[tuple[str, dict[str, AttrConstructor]], ...]] = {"
    )

    with r.indent():
        for instrumentation in instrumented:
            render_instrumentation(r, instrumentation)

    r.println("}")

    return r.finish()
