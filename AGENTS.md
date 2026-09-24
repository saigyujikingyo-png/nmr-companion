# NMR Companion
Read DEVELOPMENT_PRINCIPLES.md, RUNTIME_LIFECYCLE.md, governance/OWNERSHIP.md,
docs/LIFECYCLE.md and docs/CONTRACT.md before implementation.
This is an independent open numerical product. Do not change Mnova Companion,
native software, licences, private course sources or university download tools.
Public content and fixtures are English and synthetic or appropriately licensed.
Both organic analysis and relaxation analysis belong to the first development batch.
Use Python 3.12 and uv. Setup: uv sync --locked --group dev.
Checks: uv run pytest; uv run ruff check .; uv build.
No numerical claim without units, provenance, explicit assumptions and tests.
The project database is authoritative for GUI and MCP: optimistic revisions,
stable object identities, atomic commits, durable request IDs, undo and reopen.
Delegate only independent files behind the documented contract. The coordinator
owns contracts, dependencies, persistence, integration and acceptance records.
