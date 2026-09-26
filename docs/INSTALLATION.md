# Windows installation and recovery

The Windows x64 prerelease includes Python 3.12, the locked scientific libraries,
and the NMR Companion workbench/MCP core. Routine use needs no source checkout,
Git, uv, separately installed Python, paid model service or native Mnova.
Windows 10/11 x64 with Windows PowerShell 5.1 is the package target; actual device
and host acceptance is recorded separately from a successful package build.

## Install and use

1. Download the Windows x64 ZIP and its `.sha256` file from the same GitHub Release.
   Compare the ZIP's SHA-256 before running it (PowerShell: `Get-FileHash -Algorithm
   SHA256 .\nmr-companion-VERSION-windows-x64.zip`). Checksums establish integrity,
   not code signing. The prerelease is not Authenticode signed.
2. Extract the entire ZIP into a local folder and double-click `Install.cmd`.
   Installation is for the current user at `%LOCALAPPDATA%\Programs\NMR Companion`.
   It does not need administrator privileges. Windows may display its normal
   downloaded-file warning; organization policies may disallow unsigned scripts.
   Do not disable those policies to use this package.
3. Open `NMR Companion.cmd` in the reported installation folder. The desktop
   entrypoint opens the workbench and shares the same project as MCP. Its process
   ends when the **Close workbench** control is used or an explicit stop is requested.
   Closing only the browser tab leaves the server running until it is stopped. The package
   manager does not create a background supervisor or start anything at logon.

The default project is `%USERPROFILE%\NMR Companion\workspace.nmrproj`. The CLI
creates the desktop default only when absent. Existing projects remain unchanged
until the user or agent commits an explicit edit. `NMR_COMPANION_PROJECT` can set a
shared alternative. A launcher `-Project` argument takes precedence. Custom
projects, source data and exports should remain outside the runtime directory.

This preview uses a double-click command entrypoint and console installer. It has
no graphical setup wizard, automatic updater, Start Menu registration or file
association. An installed agent host still needs its supported connection step.

## Connect an agent host

Installation generates a product-owned local Codex marketplace at
`INSTALL_ROOT\codex-marketplace`. It includes the source plugin identity and skills,
plus a thin MCP configuration bound to this installation's stable `Launch.ps1`.
The generated command uses an absolute Windows PowerShell path. It does not need
global Python, a command on PATH, a checkout, or a second scientific core.

The installer only prepares these files. It does **not** register or install a
Codex plugin, modify host configuration/caches, or start a host process. After
installing the runtime, use the supported Codex CLI (or the host's plugin UI):

```powershell
$nmrRoot = Join-Path $env:LOCALAPPDATA 'Programs\NMR Companion'
codex plugin marketplace add "$nmrRoot\codex-marketplace" --json
codex plugin list --marketplace nmr-companion-local --available --json
codex plugin add nmr-companion@nmr-companion-local --json
codex plugin list --marketplace nmr-companion-local --json
```

Use the actual installation directory if it differs from the default. Confirm
that the installed plugin version matches the generated
`plugins\nmr-companion\.codex-plugin\plugin.json`. Refresh the host or start a new
chat as required, then verify both the `nmr-workflow` skill and a fresh NMR tool
catalog. Call `nmr_project` and perform an authorized bounded edit/export/reopen
workflow. Command success or plugin listing alone is not end-to-end acceptance.

The same host-neutral MCP core is available for other hosts supporting **stdio**.
Register this executable and argument list, replacing `INSTALL_ROOT`:

```text
command: C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
arguments:
  -NoLogo
  -NoProfile
  -ExecutionPolicy
  Bypass
  -File
  INSTALL_ROOT\Launch.ps1
  -Mode
  mcp
```

The execution-policy flag applies to this launched process only; it does not
change the machine's saved execution policy or override organizational policy.
The stable `INSTALL_ROOT\nmr-mcp.cmd` is also available to hosts supporting CMD
entrypoints. For a custom project, append `-Project` and its full path. Keep the
GUI and host project arguments identical so both edit one authoritative database.

If a host installation does not offer plugin installation, the supported Codex
MCP-only fallback is:

```powershell
codex mcp add nmr-companion -- powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\NMR Companion\Launch.ps1" -Mode mcp
codex mcp get nmr-companion --json
```

That fallback adds MCP tools only; it does not install the bundled skill or a
Codex plugin. Choose one connection route so the same server is not registered
twice. Read the current CLI help before use. Package integrity, host registration,
fresh tool discovery, a real model call and exported-file delivery are separate
checks. Local stdio does not provide a remote ChatGPT connector or establish
cloud-host support. The local marketplace uses the supported
[plugin packaging format](https://developers.openai.com/plugins/build/plugins).

## Upgrade, rollback and interrupted installation

Close the workbench and disconnect the NMR MCP server before installation changes.
Shared launch locks and checks of runtime executable paths reject active product
processes. The installer never kills an existing process or native application.

Run the new release's `Install.cmd`. Each verified package lives in its own
`releases\VERSION-MANIFEST_HASH` directory. Reinstalling identical bytes is
idempotent. The prior version remains available. `installation.json` selects the
active and prior package; do not edit it manually. No package files are copied
into another plugin, account configuration or the system Python installation.
Generated marketplace, skill, manifest and MCP-adapter files have their own hashes
in `installation.json`. Changes to owned files block replacement/removal and are
preserved for review. Unknown files are retained; a new release refuses to replace
an unowned file at a newly required path.

Double-click `Rollback.cmd` to switch back to the prior package, including its
launcher resources. It does not undo scientific edits or migrate databases.
The generated plugin metadata and skills are restored with the runtime version.
After an upgrade or rollback, reinstall/refresh the named plugin through the
supported `codex plugin add` or host UI flow and read back its version; host plugin
state is not changed automatically by runtime installation. If a host requires
removal before reinstall, remove only `nmr-companion@nmr-companion-local` through
its supported interface. Verify the fresh skill and tool catalog afterward.
Export/back up important projects before upgrades; older software must reject an
unsupported database schema instead of modifying it. Retain earlier ZIP releases
for recovery if the installation directory itself is lost.

An activation interruption leaves `pending.json` and blocks launch. Run
`Recover.cmd`; if first installation had not yet created that entrypoint, run
the extracted package's manager with `-Action Recover -Root INSTALL_ROOT`.
Recovery finishes only the recorded, hash-verified package activation. It does
not rerun a scientific command. A failure before activation can leave an inert
`.staging-*` directory; preserve it for diagnosis or install into a new empty
directory. Unknown or modified files are preserved and require explicit repair.

`Verify.cmd` checks all installed manifests, files and entrypoint hashes. Launch
checks the active manifest and interpreter; full verification is not repeated on
every tool call. Checksums detect changes against local records, and do not defend
against a malicious user who can rewrite both files and those records.
Verification also checks that the generated plugin binds to this installation
path and active release. If an installation directory was moved, reinstall the
verified package with `-Root` set to its new directory, then re-add/refresh the
marketplace and plugin through supported host commands. That regenerates the
absolute binding while preserving projects; moving files alone cannot update
the host's installed plugin copy.

## Remove the runtime or retained data

Disconnect the host's NMR connection, then use its supported removal interface:

```powershell
codex plugin remove nmr-companion@nmr-companion-local --json
codex plugin marketplace remove nmr-companion-local --json
```

For the MCP-only fallback, use `codex mcp remove nmr-companion` instead. Then run
`Uninstall.cmd`. Uninstall verifies ownership and hashes before deleting runtime
versions, launchers and generated adapter files. It preserves all projects,
exports, unknown/modified files and host settings. It never calls Codex or removes
another plugin's configuration. Empty product-owned adapter directories are
removed; directories containing unknown files remain.

To explicitly remove the default workspace as part of uninstall, use the following
only after backing up data you want to keep:

```powershell
& "INSTALL_ROOT\Manage-Installation.ps1" -Action Uninstall -Root "INSTALL_ROOT" -RemoveDefaultProject -ConfirmDefaultProject "$env:USERPROFILE\NMR Companion\workspace.nmrproj"
```

That opt-in removes only the exact default database; it refuses reparse points or
SQLite sidecars that may indicate an active project. It never removes a custom
project or recursively deletes the user's project folder. After an ordinary
uninstall, retained data can be deleted explicitly with File Explorer at the
chosen project location. Keep original instrument data unless you intend to
delete it separately.

## Maintainer build

On Windows x64, with the product's Python 3.12/uv development environment:

```powershell
uv run python scripts/build_windows_bundle.py
```

The builder verifies the reviewed SHA-256 in `packaging/windows/python-runtime.json`,
extracts the pinned Astral python-build-standalone runtime, exports `uv.lock`
without development dependencies, installs hash-locked wheels, and installs the
fresh product wheel. `--python-archive PATH` reuses a downloaded archive but still
requires its pinned hash. `--output PATH` selects a fresh build directory; existing
ZIPs are never overwritten. Runtime and Python package license notices are retained.
`runtime/LICENSE.txt` includes redistribution conditions for bundled Microsoft
runtime components; those conditions also apply to recipients who redistribute
the package. Dependencies retain their own licenses in the installed metadata.
`THIRD-PARTY-RUNTIME-NOTICES` also retains the pinned runtime library notices and
their immutable upstream URLs/hashes.

The isolated `python312._pth` uses relative application-local paths. No venv,
absolute console-script launchers, pip, uv or development checkout is shipped.
The build relocates the runtime into a path containing spaces and Unicode, probes
its installed metadata and runs `python -m nmr_companion self-test`. The manifest
records source commit/dirty state, source and lock hashes, product wheel hash,
runtime provenance, dependency versions and every package file's size/hash.
Source plugin identity/version and all skill files are included as adapter inputs;
device-specific absolute MCP paths are generated only during installation. They
are not baked into public release files. Build inputs changing during packaging
cause the build to fail.
`build-evidence.json` and the adjacent `.build.json` report measured import,
CLI startup (`--help`), self-test and package size. Installed launcher/GUI/MCP, clean-device and host-model
tests remain separate acceptance work.

The runtime is from the verified upstream
[Astral python-build-standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901),
the same redistribution family used by
[uv managed Python](https://docs.astral.sh/uv/concepts/python-versions/#cpython-distributions).
Review the runtime pin when Python security updates become available; changing the
product lock does not update the interpreter automatically.
