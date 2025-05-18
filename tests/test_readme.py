import io
import re
import sys
from pathlib import Path

import pytest

from .test_integration import requires_playwright

README_PATH = Path(__file__).parent.parent / "README.md"


def examples_from_readme() -> list[str]:
    readme_text = README_PATH.read_text(encoding="utf-8")

    # Matches ```python ... ``` or ````python ... ```` blocks
    code_block_pattern = re.compile(
        r"```python\s+([\s\S]*?)```|````python\s+([\s\S]*?)````", re.MULTILINE
    )
    matches = code_block_pattern.findall(readme_text)
    # Each match is a tuple, only one group will be non-empty
    code_blocks = [m[0] or m[1] for m in matches]
    return code_blocks


@pytest.mark.parametrize("code_block", examples_from_readme())
@requires_playwright
def test_readme_code_block_executes(code_block: str):
    """
    This test will execute each Python code block from the README.md and fail if
    any raise an exception.
    """
    # Note: Use a minimal globals dict with minimal builtins, but allow imports
    exec_globals = {"__builtins__": __builtins__}

    captured = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = captured
    try:
        exec(code_block, exec_globals)
    finally:
        sys.stdout = sys_stdout
