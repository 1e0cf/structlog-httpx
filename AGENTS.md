# Agent Instructions

## Commands
- **Build**: `uv build`
- **Lint**: `ruff check .` (Recommended)
- **Test**: `pytest` (Note: `tests/` directory currently missing; create if needed)
- **Single Test**: `pytest tests/test_name.py::test_func`

## Code Style & Conventions
- **Truth Source**: Code in `src/` uses `wrapt` for patching; `README.md` describes `event_hooks`. Trust the code.
- **Typing**: Strictly use `typing` module (e.g., `typing.List`, `typing.Optional`) to match existing file conventions.
- **Formatting**: Adhere to Black/Ruff standard formatting.
- **Naming**: `snake_case` for variables/functions, `PascalCase` for classes.
- **Imports**: Group: stdlib, third-party, local.
- **Safety**: Instrumentors must catch exceptions to avoid breaking the application (see `wrapper_sync`).

## Structure
- Source located in `src/structlog_httpx/`.
- No existing tests or examples directory found.
