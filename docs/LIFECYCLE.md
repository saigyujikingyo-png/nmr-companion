# Lifecycle declaration — contract 1.0
Status: prerelease implementation; actual installed-host and OS-event evidence is recorded in ACCEPTANCE.md.

Components are on_demand_local_companion: an explicitly launched loopback web
workbench and an MCP stdio frontend. No native session, tunnel, paid model call,
autostart registration, background supervisor or durable job service is needed.

Owner: current OS user and canonical project database path. Each process owns
only itself. Multiple GUI/MCP frontends may open one database: SQLite transactions,
expected revisions and request IDs serialize writes. There is no exclusive
numerical process owner or hidden daemon. Each HTTP listener owns its port;
a bind failure is a failure, never a reason to kill an existing process.

Readiness: CLI announces the actual loopback URL only after binding. MCP
initialize/list_tools/real calls are separate protocol evidence. A saved project
is not runtime health. EOF ends stdio; Ctrl+C or the authenticated Close workbench action ends the web listener; neither closes
other software. All computations are bounded synchronous operations. Loss of a
frontend may interrupt uncommitted work. Committed state survives reopen; query
the request ID before retrying a response with an uncertain outcome. Identical
requests replay their stored result; changed reuse fails. No automatic replay
on reconnect, crash, network recovery, wake or boot.

No boot/logon start. Shutdown/logoff/crash stop execution; SQLite transaction
recovery restores the last committed revision on explicit reopen. Sleep pauses
execution and local network is not needed by the numerical core. No promise of
continuous execution through shutdown. Crash/power-loss OS acceptance is pending.

The Windows package includes a pinned isolated Python runtime and locked dependencies.
Versioned installation, upgrade, integrity checks, recovery and rollback preserve
user projects. Shared launcher locks and scoped process checks reject activation
while this product runs; no process is killed automatically. The installer generates
a product-owned local Codex marketplace adapter, but host registration uses the
host's supported CLI separately. It never edits host caches or account files.

Schema 1 reads and committed-request replay do not migrate a project. Before the
first schema 2 write, a closed and integrity-checked schema 1 backup is prepared
under the write transaction. It is published beside the project only after the
new state passes validation. Failed edits remove only their unpublished temporary
backup. Unknown schema versions fail explicitly. Software rollback does not
downgrade scientific data; reopen the retained old-schema backup with old software.

Uninstall removes only hash-verified product-owned runtime and adapter files.
Projects, exports, unknown files, host settings and other software remain. Explicit
default-project deletion is separate and narrowly checked. No startup registration
or supervisor is installed. Closing a browser tab alone does not stop the process.
See INSTALLATION.md for supported commands and the remaining clean-device gates.

Accountable scope: one Product Max coordinator. Bounded contributors do not
acquire product ownership. Actual execution model/effort and governance review
are recorded separately; a title alone is not evidence.
