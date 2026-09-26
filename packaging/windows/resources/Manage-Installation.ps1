# NMR Companion per-user package manager. No elevation, host editing or autostart.
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Rollback', 'Recover', 'Verify', 'Uninstall')]
    [string]$Action = 'Verify',
    [string]$Bundle,
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'Programs\NMR Companion'),
    [switch]$RemoveDefaultProject,
    [string]$ConfirmDefaultProject
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$EntryPoints = @('Launch.ps1', 'nmr-mcp.cmd', 'NMR Companion.cmd', 'Rollback.cmd',
    'Verify.cmd', 'Uninstall.cmd', 'Recover.cmd', 'Manage-Installation.ps1')
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-NoReparse([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse points are not supported in package paths: $cursor"
            }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Resolve-Child([string]$Parent, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '[\\:]' -or
        $Relative.StartsWith('/') -or $Relative -match '(^|/)(\.|\.\.|)(/|$)' -or
        $Relative -match '(^|/)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|/|$)' -or
        $Relative -match '[ .](/|$)') {
        throw "Unsafe package-relative path: $Relative"
    }
    $base = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $resolved = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $resolved.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Package path escapes its owned directory: $Relative"
    }
    Assert-NoReparse $resolved
    return $resolved
}

function Get-Sha([string]$Path) {
    # Do not depend on PSModulePath inherited from an agent running PowerShell 7.
    # Windows PowerShell can otherwise resolve Utility without its hash function.
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Write-AtomicJson([string]$Path, $Value) {
    $temporary = $Path + '.new-' + [Guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 30), $Utf8)
        if (Test-Path -LiteralPath $Path) {
            [IO.File]::Replace($temporary, $Path, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $Path)
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

function Get-BytesSha([byte[]]$Bytes) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose() }
}

function Get-AdapterHashes($State) {
    $hashes = @{}
    if ($State -and $State.PSObject.Properties['adapter_hashes']) {
        foreach ($property in $State.adapter_hashes.PSObject.Properties) {
            if (-not $property.Name.StartsWith('codex-marketplace/', [StringComparison]::Ordinal) -or
                $property.Value -notmatch '^[a-f0-9]{64}$') {
                throw 'Invalid product-owned plugin adapter inventory.'
            }
            $null = Resolve-Child $Root $property.Name
            $hashes[$property.Name] = $property.Value
        }
    }
    return $hashes
}

function Get-AdapterFiles([string]$Directory, $Manifest) {
    $files = @{}
    $pluginPrefix = 'codex-marketplace/plugins/nmr-companion/'
    foreach ($property in $Manifest.files.PSObject.Properties) {
        if ($property.Name.StartsWith('plugin/', [StringComparison]::Ordinal)) {
            $relative = $property.Name.Substring(7)
            if ($relative -eq '.mcp.json') { throw 'The package must not ship a pre-bound MCP adapter.' }
            $source = Resolve-Child $Directory $property.Name
            $files[$pluginPrefix + $relative] = [IO.File]::ReadAllBytes($source)
        }
    }
    $pluginPath = Resolve-Child $Directory 'plugin/.codex-plugin/plugin.json'
    $plugin = Get-Content -LiteralPath $pluginPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($plugin.name -ne 'nmr-companion' -or $plugin.skills -ne './skills/' -or
        $plugin.mcpServers -ne './.mcp.json') {
        throw 'Unsupported source plugin identity or component paths.'
    }
    $catalog = Resolve-Child $Directory 'codex-marketplace-template.json'
    $files['codex-marketplace/.agents/plugins/marketplace.json'] = [IO.File]::ReadAllBytes($catalog)
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $mcp = [ordered]@{ mcpServers = [ordered]@{ 'nmr-companion' = [ordered]@{
        command = $powershell
        args = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $Root 'Launch.ps1'), '-Mode', 'mcp')
    } } }
    $files[$pluginPrefix + '.mcp.json'] = $Utf8.GetBytes(($mcp | ConvertTo-Json -Depth 8))
    return $files
}

function Assert-AdapterOwnership($State, $NewFiles, [switch]$Recovery) {
    $oldHashes = Get-AdapterHashes $State
    foreach ($relative in $oldHashes.Keys) {
        $path = Resolve-Child $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            if ($Recovery -and -not (Test-Path -LiteralPath $path)) { continue }
            throw "Installed plugin adapter missing or changed; preserved: $relative"
        }
        $hash = Get-Sha $path
        $newMatches = $Recovery -and $NewFiles.ContainsKey($relative) -and
            $hash -eq (Get-BytesSha $NewFiles[$relative])
        if ($hash -ne $oldHashes[$relative] -and -not $newMatches) {
            throw "Installed plugin adapter changed; preserved: $relative"
        }
    }
    foreach ($relative in $NewFiles.Keys) {
        $path = Resolve-Child $Root $relative
        $newHash = Get-BytesSha $NewFiles[$relative]
        if (-not $oldHashes.ContainsKey($relative) -and (Test-Path -LiteralPath $path)) {
            if (-not $Recovery -or -not (Test-Path -LiteralPath $path -PathType Leaf) -or
                (Get-Sha $path) -ne $newHash) {
                throw "Unowned plugin adapter path would be replaced; preserved: $relative"
            }
        }
        if (Test-Path -LiteralPath ($path + '.new')) {
            if (-not $Recovery -or (Get-Sha ($path + '.new')) -ne $newHash) {
                throw "Unknown plugin adapter staging file was preserved: $relative.new"
            }
        }
    }
}

function Write-AdapterFiles($Files) {
    foreach ($relative in ($Files.Keys | Sort-Object)) {
        $path = Resolve-Child $Root $relative
        $temporary = $path + '.new'
        # Any recovered staging file was checked before the activation receipt.
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
        [IO.File]::WriteAllBytes($temporary, $Files[$relative])
        if (Test-Path -LiteralPath $path) {
            [IO.File]::Replace($temporary, $path, [NullString]::Value)
        } else { [IO.File]::Move($temporary, $path) }
    }
}

function Remove-EmptyAdapterDirectories($RelativePaths) {
    $adapterRoot = Resolve-Child $Root 'codex-marketplace'
    $directories = @{}
    foreach ($relative in $RelativePaths) {
        $cursor = [IO.Path]::GetDirectoryName((Resolve-Child $Root $relative))
        while ($cursor -eq $adapterRoot -or
            $cursor.StartsWith($adapterRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            $directories[$cursor] = $true
            $cursor = [IO.Path]::GetDirectoryName($cursor)
        }
    }
    foreach ($directory in ($directories.Keys | Sort-Object Length -Descending)) {
        Assert-NoReparse $directory
        if ((Test-Path -LiteralPath $directory -PathType Container) -and
            @(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) {
            Remove-Item -LiteralPath $directory
        }
    }
}

function Read-Manifest([string]$Directory, [string]$ExpectedHash = '') {
    Assert-NoReparse $Directory
    $manifestPath = Join-Path $Directory 'manifest.json'
    if ($ExpectedHash -and (Get-Sha $manifestPath) -ne $ExpectedHash) {
        throw 'Installed release manifest hash changed; files were preserved.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.product -ne 'nmr-companion' -or $manifest.schema_version -ne 1 -or
        $manifest.version -notmatch '^[A-Za-z0-9][A-Za-z0-9.+-]*$') {
        throw 'Unsupported NMR Companion package manifest.'
    }
    $expected = @{}
    foreach ($property in $manifest.files.PSObject.Properties) {
        $path = Resolve-Child $Directory $property.Name
        if ($expected.ContainsKey($property.Name)) { throw 'Duplicate package path.' }
        $expected[$property.Name] = $true
        if ($property.Value.sha256 -notmatch '^[a-f0-9]{64}$' -or
            -not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-Item -LiteralPath $path).Length -ne $property.Value.size -or
            (Get-Sha $path) -ne $property.Value.sha256) {
            throw "Package file missing or changed: $($property.Name)"
        }
    }
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Recurse -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Package contains a reparse point.'
        }
        if (-not $item.PSIsContainer -and $item.FullName -ne $manifestPath) {
            $relative = $item.FullName.Substring($Directory.TrimEnd('\').Length + 1).Replace('\', '/')
            if (-not $expected.ContainsKey($relative)) {
                throw "Unexpected package file; preserved: $relative"
            }
        }
    }
    $actualNames = @($manifest.launchers.PSObject.Properties.Name | Sort-Object)
    if (($actualNames -join '|') -ne (($EntryPoints | Sort-Object) -join '|')) {
        throw 'Package launcher contract is incomplete or unsupported.'
    }
    foreach ($property in $manifest.launchers.PSObject.Properties) {
        if (-not $expected.ContainsKey([string]$property.Value)) {
            throw 'Launcher is not covered by the package manifest.'
        }
    }
    if (-not $expected.ContainsKey('runtime/python.exe')) { throw 'Bundled runtime is missing.' }
    foreach ($required in @('plugin/.codex-plugin/plugin.json',
        'plugin/skills/nmr-workflow/SKILL.md', 'codex-marketplace-template.json')) {
        if (-not $expected.ContainsKey($required)) { throw "Plugin adapter source is missing: $required" }
    }
    return $manifest
}

function Read-State([string]$Directory) {
    $path = Join-Path $Directory 'installation.json'
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.product -ne 'nmr-companion' -or $state.schema_version -ne 1) {
        throw 'This directory is not a supported NMR Companion installation.'
    }
    $ids = @{}
    foreach ($release in $state.releases) {
        if ($release.id -notmatch '^[A-Za-z0-9][A-Za-z0-9.+-]*-[a-f0-9]{12}$' -or
            $release.manifest_sha256 -notmatch '^[a-f0-9]{64}$' -or $ids.ContainsKey($release.id)) {
            throw 'Installation release inventory is invalid; files were preserved.'
        }
        $ids[$release.id] = $true
        $null = Resolve-Child $Directory ('releases/' + $release.id)
    }
    if (-not $ids.ContainsKey($state.active) -or
        ($state.previous -and -not $ids.ContainsKey($state.previous))) {
        throw 'Installation active/rollback pointer is invalid.'
    }
    return $state
}

function Assert-Launchers($State) {
    if (-not $State) { return }
    foreach ($name in $EntryPoints) {
        $path = Resolve-Child $Root $name
        $expected = $State.launcher_hashes.PSObject.Properties[$name].Value
        if (-not (Test-Path -LiteralPath $path) -or (Get-Sha $path) -ne $expected) {
            throw "Installed launcher changed; preserved: $name"
        }
    }
}

function Assert-Stopped {
    # The shared file lock covers supported launchers. Executable identity also
    # catches a runtime started directly or surviving a terminated launcher.
    Import-Module (Join-Path $PSHOME 'Modules\CimCmdlets\CimCmdlets.psd1') -ErrorAction Stop
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($process in $processes) {
        $currentProcess = $process
        if ($currentProcess.Name -in @('python.exe', 'pythonw.exe') -and -not $currentProcess.ExecutablePath) {
            # A process may exit between the OS snapshot and executable lookup.
            # Reconcile that PID once; this never spawns/stops/replays any work.
            $observed = @(Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $currentProcess.ProcessId) -ErrorAction Stop)
            if ($observed.Count -eq 0) { continue }
            $currentProcess = $observed[0]
        }
        if ($currentProcess.Name -in @('python.exe', 'pythonw.exe') -and -not $currentProcess.ExecutablePath) {
            throw 'A Python process has an unreadable executable identity. Installation changes are blocked until its ownership is resolved; no process was stopped.'
        }
        if ($currentProcess.ExecutablePath -and
            $currentProcess.ExecutablePath.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "NMR runtime is active (PID $($currentProcess.ProcessId)). Close its GUI or disconnect its host before changing installation."
        }
    }
}

function Activate-Release($NewState, [string]$Directory, $Manifest, [switch]$Recovery) {
    $oldState = Read-State $Root
    $adapterFiles = Get-AdapterFiles $Directory $Manifest
    Assert-AdapterOwnership $oldState $adapterFiles -Recovery:$Recovery
    $adapterHashes = [ordered]@{}
    foreach ($relative in ($adapterFiles.Keys | Sort-Object)) {
        $adapterHashes[$relative] = Get-BytesSha $adapterFiles[$relative]
    }
    $NewState | Add-Member -MemberType NoteProperty -Name adapter_hashes -Value $adapterHashes -Force
    $hashes = [ordered]@{}
    foreach ($name in $EntryPoints) {
        $relative = $Manifest.launchers.PSObject.Properties[$name].Value
        $hashes[$name] = $Manifest.files.PSObject.Properties[$relative].Value.sha256
    }
    $NewState.launcher_hashes = $hashes
    Write-AtomicJson (Join-Path $Root 'pending.json') $NewState
    foreach ($name in $EntryPoints) {
        $source = Resolve-Child $Directory $Manifest.launchers.PSObject.Properties[$name].Value
        $target = Resolve-Child $Root $name
        $temporary = $target + '.new'
        if (Test-Path -LiteralPath $temporary) { throw "Unexpected staging file: $temporary" }
        Copy-Item -LiteralPath $source -Destination $temporary
        if (Test-Path -LiteralPath $target) {
            [IO.File]::Replace($temporary, $target, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $target)
        }
    }
    Write-AdapterFiles $adapterFiles
    $oldAdapterHashes = Get-AdapterHashes $oldState
    foreach ($relative in $oldAdapterHashes.Keys) {
        if (-not $adapterFiles.ContainsKey($relative)) {
            $path = Resolve-Child $Root $relative
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
        }
    }
    Remove-EmptyAdapterDirectories $oldAdapterHashes.Keys
    Write-AtomicJson (Join-Path $Root 'installation.json') $NewState
    Remove-Item -LiteralPath (Join-Path $Root 'pending.json')
}

$lock = $null
$completedRemoval = $false
try {
    $Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ($Root -notmatch '^[A-Za-z]:\\') { throw 'Choose a directory on a local Windows drive.' }
    if ($Root -eq [IO.Path]::GetPathRoot($Root).TrimEnd('\')) { throw 'A drive root is not an installation directory.' }
    Assert-NoReparse $Root
    $state = Read-State $Root
    if (-not $state -and $Action -ne 'Install' -and $Action -ne 'Recover') {
        throw 'No owned installation was found at this path.'
    }
    if (-not $state -and $Action -eq 'Install' -and (Test-Path -LiteralPath $Root) -and
        @(Get-ChildItem -LiteralPath $Root -Force).Count -gt 0) {
        throw 'A new installation requires an empty product directory; existing files were preserved.'
    }
    if ($Action -eq 'Install') {
        if (-not $Bundle) { throw 'Install requires -Bundle with the extracted release directory.' }
        $Bundle = [IO.Path]::GetFullPath($Bundle).TrimEnd('\')
        if ($Bundle -eq $Root -or $Bundle.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $Root.StartsWith($Bundle + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Source package and installation directory must be separate.'
        }
        $manifest = Read-Manifest $Bundle
    }
    if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root | Out-Null }
    try {
        $lock = [IO.File]::Open((Join-Path $Root '.installation.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch {
        throw 'An NMR launcher or installer is active. Close/disconnect it before changing installation.'
    }
    # Re-read after the lock so simultaneous installers cannot activate stale state.
    $state = Read-State $Root
    $pendingPath = Join-Path $Root 'pending.json'
    if ((Test-Path -LiteralPath $pendingPath) -and $Action -ne 'Recover') {
        throw 'A previous installation was interrupted. Run Recover.cmd before continuing.'
    }
    if ($Action -ne 'Recover') {
        Assert-Launchers $state
        Assert-AdapterOwnership $state @{}
    }
    Assert-Stopped

    if ($Action -eq 'Install') {
        $digest = Get-Sha (Join-Path $Bundle 'manifest.json')
        $id = $manifest.version + '-' + $digest.Substring(0, 12)
        Assert-AdapterOwnership $state (Get-AdapterFiles $Bundle $manifest)
        $releases = Resolve-Child $Root 'releases'
        if (-not (Test-Path -LiteralPath $releases)) { New-Item -ItemType Directory -Path $releases | Out-Null }
        $destination = Resolve-Child $Root ('releases/' + $id)
        if (-not (Test-Path -LiteralPath $destination)) {
            $staging = Resolve-Child $Root ('.staging-' + [Guid]::NewGuid().ToString('N'))
            Copy-Item -LiteralPath $Bundle -Destination $staging -Recurse
            $null = Read-Manifest $staging $digest
            Move-Item -LiteralPath $staging -Destination $destination
        } else { $null = Read-Manifest $destination $digest }
        $known = @()
        $previous = $null
        if ($state) { $known = @($state.releases); $previous = $state.active }
        if ($state -and $state.active -eq $id) { $previous = $state.previous }
        if (-not @($known | Where-Object { $_.id -eq $id }).Count) {
            $known += [pscustomobject]@{ id = $id; manifest_sha256 = $digest }
        }
        $next = [pscustomobject]@{ schema_version = 1; product = 'nmr-companion';
            active = $id; previous = $previous; releases = @($known); launcher_hashes = $null }
        Activate-Release $next $destination $manifest
        [pscustomobject]@{ action = 'installed'; version = $manifest.version; root = $Root;
            rollback = $previous; project_data = 'retained'; host_registration = 'unchanged' } | ConvertTo-Json
    } elseif ($Action -eq 'Rollback' -or $Action -eq 'Recover') {
        if ($Action -eq 'Recover') {
            if (-not (Test-Path -LiteralPath $pendingPath)) { throw 'No interrupted activation was found.' }
            $next = Get-Content -LiteralPath $pendingPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($next.product -ne 'nmr-companion' -or $next.schema_version -ne 1) { throw 'Invalid recovery record.' }
        } else {
            if (-not $state.previous) { throw 'No earlier installed version is available for rollback.' }
            $priorActive = $state.active
            $next = $state
            $next.active = $state.previous
            $next.previous = $priorActive
        }
        $release = @($next.releases | Where-Object { $_.id -eq $next.active })
        if ($release.Count -ne 1) { throw 'Recovery or rollback release is missing.' }
        $directory = Resolve-Child $Root ('releases/' + $release[0].id)
        $manifest = Read-Manifest $directory $release[0].manifest_sha256
        if ($Action -eq 'Recover') {
            foreach ($name in $EntryPoints) {
                $path = Resolve-Child $Root $name
                $newHash = $manifest.files.PSObject.Properties[$manifest.launchers.PSObject.Properties[$name].Value].Value.sha256
                if (Test-Path -LiteralPath $path) {
                    $actual = Get-Sha $path
                    $oldHash = if ($state) { $state.launcher_hashes.PSObject.Properties[$name].Value } else { '' }
                    if ($actual -ne $newHash -and $actual -ne $oldHash) { throw "Modified entrypoint was preserved: $name" }
                }
                $temporary = $path + '.new'
                if (Test-Path -LiteralPath $temporary) {
                    if ((Get-Sha $temporary) -ne $newHash) { throw 'Unknown activation staging file was preserved.' }
                    Remove-Item -LiteralPath $temporary
                }
            }
        }
        Activate-Release $next $directory $manifest -Recovery:($Action -eq 'Recover')
        [pscustomobject]@{ action = $Action.ToLowerInvariant(); active = $next.active; project_data = 'retained' } | ConvertTo-Json
    } elseif ($Action -eq 'Verify') {
        $activeManifest = $null
        $activeDirectory = $null
        foreach ($release in $state.releases) {
            $directory = Resolve-Child $Root ('releases/' + $release.id)
            $verified = Read-Manifest $directory $release.manifest_sha256
            if ($release.id -eq $state.active) { $activeManifest = $verified; $activeDirectory = $directory }
        }
        $expectedAdapter = Get-AdapterFiles $activeDirectory $activeManifest
        $ownedAdapter = Get-AdapterHashes $state
        if (($expectedAdapter.Keys | Sort-Object) -join '|' -cne (($ownedAdapter.Keys | Sort-Object) -join '|')) {
            throw 'Plugin adapter inventory differs from the active release.'
        }
        foreach ($relative in $expectedAdapter.Keys) {
            if ((Get-BytesSha $expectedAdapter[$relative]) -ne $ownedAdapter[$relative]) {
                throw 'Plugin adapter binding differs from this installation path or active release. Reinstall from the verified package and refresh the host plugin.'
            }
        }
        [pscustomobject]@{ action = 'verified'; active = $state.active; releases = @($state.releases).Count;
            scope = 'Package bytes, entrypoints and generated plugin binding; not host or scientific acceptance' } | ConvertTo-Json
    } elseif ($Action -eq 'Uninstall') {
        $defaultProject = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'NMR Companion\workspace.nmrproj'
        if ($RemoveDefaultProject) {
            if (-not $ConfirmDefaultProject -or
                [IO.Path]::GetFullPath($ConfirmDefaultProject) -ne $defaultProject) {
                throw 'Data removal requires -ConfirmDefaultProject with the exact default workspace path.'
            }
            Assert-NoReparse $defaultProject
            foreach ($suffix in @('-wal', '-shm', '-journal')) {
                if (Test-Path -LiteralPath ($defaultProject + $suffix)) { throw 'Workspace has SQLite sidecars; preserve it until all project frontends are closed.' }
            }
        }
        # Verify every removal target completely before deleting any runtime.
        foreach ($release in $state.releases) {
            $null = Read-Manifest (Resolve-Child $Root ('releases/' + $release.id)) $release.manifest_sha256
        }
        foreach ($release in $state.releases) {
            $directory = Resolve-Child $Root ('releases/' + $release.id)
            Remove-Item -LiteralPath $directory -Recurse
        }
        $adapterHashes = Get-AdapterHashes $state
        foreach ($relative in $adapterHashes.Keys) {
            Remove-Item -LiteralPath (Resolve-Child $Root $relative)
        }
        Remove-EmptyAdapterDirectories $adapterHashes.Keys
        foreach ($name in $EntryPoints) { Remove-Item -LiteralPath (Resolve-Child $Root $name) }
        Remove-Item -LiteralPath (Join-Path $Root 'installation.json')
        if ($RemoveDefaultProject -and (Test-Path -LiteralPath $defaultProject)) {
            Remove-Item -LiteralPath $defaultProject
        }
        $releaseRoot = Resolve-Child $Root 'releases'
        if (@(Get-ChildItem -LiteralPath $releaseRoot -Force).Count -eq 0) { Remove-Item -LiteralPath $releaseRoot }
        $completedRemoval = $true
        [pscustomobject]@{ action = 'uninstalled'; default_project_removed = [bool]$RemoveDefaultProject;
            custom_projects = 'retained'; other_files = 'retained'; host_registration = 'unchanged' } | ConvertTo-Json
    }
} catch {
    [Console]::Error.WriteLine('NMR Companion: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
    if ($completedRemoval) {
        Remove-Item -LiteralPath (Join-Path $Root '.installation.lock')
        if (@(Get-ChildItem -LiteralPath $Root -Force).Count -eq 0) { Remove-Item -LiteralPath $Root }
    }
}
