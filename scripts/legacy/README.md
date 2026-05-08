# Legacy Startup Entrypoints

Root-level `run_*.py`, `start_*.py`, and `start_services.bat` are retained only
as compatibility wrappers. They no longer contain service orchestration logic.

Official entrypoints:

- Local SQLite/dev stack: `python scripts/start_local.py` or `make dev`
- Container stack: `docker compose up -d` or `make stack`

The wrappers exist so old bookmarks, shortcuts, and documentation snippets fail
softly by redirecting users to the maintained startup paths.
