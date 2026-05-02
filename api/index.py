"""Vercel serverless ASGI entrypoint."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_app():
    current_file = Path(__file__).resolve()
    search_roots = [current_file.parent, *current_file.parents]

    for root in search_roots:
        candidate = root / "main.py"
        if candidate.exists() and candidate != current_file:
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)

            spec = importlib.util.spec_from_file_location("main", candidate)
            if spec is None or spec.loader is None:
                break

            module = importlib.util.module_from_spec(spec)
            sys.modules["main"] = module
            spec.loader.exec_module(module)
            return module.app

    searched = ", ".join(str(root / "main.py") for root in search_roots)
    raise RuntimeError(f"Could not locate FastAPI main.py. Searched: {searched}")


app = _load_app()
