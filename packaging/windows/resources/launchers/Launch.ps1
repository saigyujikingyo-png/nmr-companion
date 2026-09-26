[CmdletBinding()]
param(
    [ValidateSet('mcp', 'desktop', 'export', 'self-test')][string]$Mode = 'mcp',
    [string]$Project,
    [int]$Revision = -1,
    [string]$Output
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$lock = $null
function Get-Sha([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}
try {
    # Multiple frontends share read handles; package changes need an exclusive one.
    $lock = [IO.File]::Open((Join-Path $root '.installation.lock'), 'Open', 'Read', 'Read')
    if (Test-Path -LiteralPath (Join-Path $root 'pending.json')) {
        throw 'An installation was interrupted. Run Recover.cmd first.'
    }
    $state = Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.product -ne 'nmr-companion' -or $state.schema_version -ne 1 -or
        $state.active -notmatch '^[A-Za-z0-9][A-Za-z0-9.+-]*-[a-f0-9]{12}$') {
        throw 'Invalid NMR Companion installation pointer.'
    }
    $directory = [IO.Path]::GetFullPath((Join-Path $root ('releases\' + $state.active)))
    if (-not $directory.StartsWith($root + '\releases\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Runtime path escapes the installation.'
    }
    $python = Join-Path $directory 'runtime\python.exe'
    $cursor = $python
    while ($cursor) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Runtime path contains a reparse point.'
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $release = @($state.releases | Where-Object { $_.id -eq $state.active })
    $manifestPath = Join-Path $directory 'manifest.json'
    if ($release.Count -ne 1 -or
        (Get-Sha $manifestPath) -ne $release[0].manifest_sha256) {
        throw 'Runtime manifest changed. Run Verify.cmd and reinstall a verified release.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ((Get-Sha $python) -ne
        $manifest.files.'runtime/python.exe'.sha256) {
        throw 'Runtime executable changed. Reinstall a verified release.'
    }
    $runArgs = @('-I', '-B', '-m', 'nmr_companion')
    if ($Project) { $runArgs += @('--project', $Project) }
    $runArgs += $Mode
    if ($Mode -eq 'export') {
        if ($Revision -lt 0 -or -not $Output) { throw 'Export requires -Revision and -Output.' }
        $runArgs += @('--revision', [string]$Revision, '--output', $Output)
    }
    # Direct invocation preserves stdio, including clean MCP EOF, and waits for exit.
    & $python @runArgs
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('NMR Companion: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
