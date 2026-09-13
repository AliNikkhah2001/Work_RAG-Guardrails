"""FastAPI application entry point for Guardrails service."""

from __future__ import annotations

from .service import create_app

app = create_app()

if __name__ == "__main__":
    from .service import main
    main()