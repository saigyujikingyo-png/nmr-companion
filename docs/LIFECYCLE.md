# Lifecycle declaration — contract 1.0
Status: implementation in progress; installed host and OS-event acceptance pending.

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
is not runtime health. EOF ends stdio; Ctrl+C ends the workbench; neither closes
other software. All computations are bounded synchronous operations. Loss of a
frontend may interrupt uncommitted work. Committed state survives reopen; query
the request ID before retrying a response with an uncertain outcome. Identical
requests replay their stored result; changed reuse fails. No automatic replay
on reconnect, crash, network recovery, wake or boot.

No boot/logon start. Shutdown/logoff/crash stop execution; SQLite transaction
recovery restores the last committed revision on explicit reopen. Sleep pauses
execution and local network is not needed by the numerical core. No promise of
continuous execution through shutdown. Crash/power-loss OS acceptance is pending.

Developer installation uses a locked isolated environment. Upgrade retains
project files; unsupported schema versions fail without migration. Uninstall
removes only this package/environment and retains user projects. No registry,
account, startup or native application state is modified. Bundled GUI installer,
upgrade/rollback/removal and actual multi-host acceptance remain delivery gates.

Accountable scope: one Product Max coordinator. Bounded contributors do not
acquire product ownership. Actual execution model/effort and governance review
are recorded separately; a title alone is not evidence.
