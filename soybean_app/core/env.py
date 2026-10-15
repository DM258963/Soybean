import os
import re
from pathlib import Path


_LOADED_PATHS: set[Path] = set()
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()

    return value.strip()


def _unquote(value: str) -> str:
    if len(value) < 2:
        return value

    quote = value[0]
    if quote not in {"'", '"'} or value[-1] != quote:
        return value

    inner = value[1:-1]
    if quote == "'":
        return inner

    return (
        inner.replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\"", '"')
        .replace(r"\\", "\\")
    )


def load_project_env(env_path: str | Path | None = None, *, override: bool = False) -> None:
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().parents[2] / ".env"
    path = path.resolve()
    if path in _LOADED_PATHS or not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            continue

        parsed_value = _unquote(_strip_inline_comment(value.strip()))
        if override or key not in os.environ:
            os.environ[key] = parsed_value

    _LOADED_PATHS.add(path)
