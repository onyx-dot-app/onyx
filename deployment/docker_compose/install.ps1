# Onyx Installer for Windows
# Usage: .\install.ps1 [OPTIONS]
# Remote (with params):
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.ps1))) -Lite -NoPrompt
# Remote (defaults only, configure via interaction during script):
#   irm https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.ps1 | iex

param(
    [switch]$Shutdown,
    [switch]$DeleteData,
    [switch]$IncludeCraft,
    [switch]$Lite,
    [switch]$Local,
    [switch]$NoPrompt,
    [switch]$DryRun,
    [switch]$ShowVerbose,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Runs a native command with stderr silenced and ErrorActionPreference=Continue.
function Invoke-NativeQuiet {
    param([scriptblock]$Command, [switch]$PassThru)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($PassThru) { & $Command 2>$null }
        else           { $null = & $Command 2>$null }
    } finally { $ErrorActionPreference = $prev }
}

$script:ExpectedDockerRamGB = 10
$script:ExpectedDiskGB = 32
$script:InstallRoot = if ($env:INSTALL_PREFIX) { $env:INSTALL_PREFIX } else { "onyx_data" }
$script:LiteComposeFile = "docker-compose.onyx-lite.yml"
$script:GitHubRawUrl = "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose"
$script:NginxBaseUrl = "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/data/nginx"
$script:CurrentStep = 0
$script:TotalSteps = 10
$script:ComposeCmdType = $null
$script:LiteMode = $Lite.IsPresent
$script:IncludeCraftMode = $IncludeCraft.IsPresent
$script:IsWindowsServer = (Get-CimInstance Win32_OperatingSystem).ProductType -ne 1

# ── Output Helpers ───────────────────────────────────────────────────────────

function Print-Success  { param([string]$Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Print-OnyxError{ param([string]$Message) Write-Host "[X]  $Message" -ForegroundColor Red }
function Print-Info     { param([string]$Message) Write-Host "[i]  $Message" -ForegroundColor Yellow }
function Print-Warning  { param([string]$Message) Write-Host "[!]  $Message" -ForegroundColor Yellow }

function Print-Step {
    param([string]$Title)
    $script:CurrentStep++
    Write-Host "`n=== $Title - Step $($script:CurrentStep)/$($script:TotalSteps) ===`n" -ForegroundColor Cyan
}

function Test-Interactive {
    return -not $NoPrompt
}

function Prompt-OrDefault {
    param([string]$PromptText, [string]$DefaultValue)
    if (-not (Test-Interactive)) { return $DefaultValue }
    $reply = Read-Host $PromptText
    if ([string]::IsNullOrWhiteSpace($reply)) { return $DefaultValue }
    return $reply
}

function Confirm-Action {
    param([string]$Description)
    $reply = Prompt-OrDefault "Install $Description? (Y/n) [default: Y]" "Y"
    if ($reply -match '^[Nn]') {
        Print-Warning "Skipping: $Description"
        return $false
    }
    return $true
}

function Prompt-VersionTag {
    Print-Info "Which tag would you like to deploy?"
    if ($script:IncludeCraftMode) {
        Write-Host "  - Press Enter for craft-latest (recommended for Craft)"
        Write-Host "  - Type a specific tag (e.g., craft-v1.0.0)"
        $version = Prompt-OrDefault "Enter tag [default: craft-latest]" "craft-latest"
    } else {
        Write-Host "  - Press Enter for edge (recommended)"
        Write-Host "  - Type a specific tag (e.g., v0.1.0)"
        $version = Prompt-OrDefault "Enter tag [default: edge]" "edge"
    }
    if     ($script:IncludeCraftMode -and $version -eq "craft-latest") { Print-Info "Selected: craft-latest (Craft enabled)" }
    elseif ($version -eq "edge") { Print-Info "Selected: edge (latest nightly)" }
    else   { Print-Info "Selected: $version" }
    return $version
}

function Prompt-DeploymentMode {
    param([string]$LiteOverlayPath)
    if ($script:LiteMode) { Print-Info "Deployment mode: Lite (set via -Lite flag)"; return }
    Print-Info "Which deployment mode would you like?"
    Write-Host "  1) Lite      - Minimal deployment (no Vespa, Redis, or model servers)"
    Write-Host "                  LLM chat, tools, file uploads, and Projects still work"
    Write-Host "  2) Standard  - Full deployment with search, connectors, and RAG"
    $modeChoice = Prompt-OrDefault "Choose a mode (1 or 2) [default: 1]" "1"
    if ($modeChoice -eq "2") {
        Print-Info "Selected: Standard mode"
    } else {
        $script:LiteMode = $true
        Print-Info "Selected: Lite mode"
        if (-not (Ensure-OnyxFile $LiteOverlayPath "$($script:GitHubRawUrl)/$($script:LiteComposeFile)" $script:LiteComposeFile)) { exit 1 }
    }
}

function Assert-NotCraftLite {
    param([string]$Tag)
    if (-not ($script:LiteMode -and $Tag -match '^craft-')) { return }
    Print-OnyxError "Cannot use a craft image tag ($Tag) with Lite mode."
    Print-Info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
    exit 1
}

function Refresh-PathFromRegistry {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Get-NativeVersionString {
    param([scriptblock]$Command)
    $output = Invoke-NativeQuiet -PassThru $Command
    $match = [regex]::Match(($output -join ""), '(\d+\.\d+\.\d+)')
    if ($match.Success) { return $match.Value }
    return "unknown"
}

# ── Download Helpers ─────────────────────────────────────────────────────────

function Download-OnyxFile {
    param([string]$Url, [string]$Output)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $Output -UseBasicParsing -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Ensure-OnyxFile {
    param([string]$Path, [string]$Url, [string]$Description)
    if ($Local) {
        if (Test-Path $Path) { Print-Success "Using existing $Description"; return $true }
        Print-OnyxError "Required file missing: $Description ($Path)"
        return $false
    }
    Print-Info "Downloading $Description..."
    try {
        Download-OnyxFile -Url $Url -Output $Path
        Print-Success "$Description downloaded"
        return $true
    } catch {
        Print-OnyxError "Failed to download $Description"
        return $false
    }
}

# ── .env File Helpers ────────────────────────────────────────────────────────

function Set-EnvFileValue {
    param([string]$Path, [string]$Key, [string]$Value, [switch]$Uncomment)
    $lines = Get-Content $Path
    $found = $false
    $result = @()
    foreach ($line in $lines) {
        if ($Uncomment -and $line -match "^\s*#\s*${Key}=") {
            $result += "${Key}=${Value}"; $found = $true
        } elseif ($line -match "^${Key}=") {
            $result += "${Key}=${Value}"; $found = $true
        } else { $result += $line }
    }
    if (-not $found) { $result += "${Key}=${Value}" }
    Write-Utf8NoBom -Path $Path -Content (($result -join "`n") + "`n")
}

function Get-EnvFileValue {
    param([string]$Path, [string]$Key)
    $match = Select-String -Path $Path -Pattern "^${Key}=(.*)" | Select-Object -First 1
    if ($match) { return $match.Matches.Groups[1].Value.Trim().Trim('"', "'") }
    return $null
}

function New-SecureSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''
}

# ── Docker Compose ───────────────────────────────────────────────────────────

function Get-ComposeFileArgs {
    param([switch]$AutoDetect)
    $fileArgs = @("-f", "docker-compose.yml")
    $litePath = Join-Path $script:InstallRoot "deployment\$($script:LiteComposeFile)"
    if ($script:LiteMode -or ($AutoDetect -and (Test-Path $litePath))) {
        $fileArgs += @("-f", $script:LiteComposeFile)
    }
    return $fileArgs
}

function Invoke-Compose {
    param([switch]$AutoDetect, [Parameter(ValueFromRemainingArguments)][string[]]$Arguments)
    $deployDir = Join-Path $script:InstallRoot "deployment"
    $fileArgs = Get-ComposeFileArgs -AutoDetect:$AutoDetect
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $deployDir
    try {
        if ($script:ComposeCmdType -eq "plugin") { & docker @(@("compose") + $fileArgs + $Arguments) }
        else { & docker-compose @($fileArgs + $Arguments) }
        return $LASTEXITCODE
    } finally { Pop-Location; $ErrorActionPreference = $prev }
}

function Initialize-ComposeCommand {
    Invoke-NativeQuiet { docker compose version }
    if ($LASTEXITCODE -eq 0) { $script:ComposeCmdType = "plugin"; return $true }
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) { $script:ComposeCmdType = "standalone"; return $true }
    $script:ComposeCmdType = $null; return $false
}

# ── Utilities ────────────────────────────────────────────────────────────────

function Compare-SemVer {
    param([string]$Version1, [string]$Version2)
    $parts1 = ($Version1 -split '\.') + @("0","0","0")
    $parts2 = ($Version2 -split '\.') + @("0","0","0")
    for ($i = 0; $i -lt 3; $i++) {
        $v1 = 0; $v2 = 0
        [void][int]::TryParse($parts1[$i], [ref]$v1)
        [void][int]::TryParse($parts2[$i], [ref]$v2)
        if ($v1 -lt $v2) { return -1 }
        if ($v1 -gt $v2) { return 1 }
    }
    return 0
}

function Test-PortAvailable {
    param([int]$Port)
    try { $tcp = New-Object System.Net.Sockets.TcpClient; $tcp.Connect("127.0.0.1", $Port); $tcp.Close(); return $false }
    catch { return $true }
}

function Find-AvailablePort {
    param([int]$StartPort = 3000)
    for ($port = $StartPort; $port -le 65535; $port++) {
        if (Test-PortAvailable $port) { return $port }
    }
    return $StartPort
}

function Get-DockerMemoryMB {
    foreach ($p in @((Join-Path $env:APPDATA "Docker\settings.json"), (Join-Path $env:LOCALAPPDATA "Docker\settings.json"))) {
        if (-not (Test-Path $p)) { continue }
        try {
            $s = Get-Content $p -Raw | ConvertFrom-Json
            if ($s.memoryMiB -and $s.memoryMiB -gt 0) { return [int]$s.memoryMiB }
        } catch { }
    }
    try {
        $info = Invoke-NativeQuiet -PassThru { docker system info }
        $mem = $info | Where-Object { $_ -match "Total Memory" } | Select-Object -First 1
        if ($mem -match '(\d+\.?\d*)\s*GiB') { return [int]([double]$Matches[1] * 1024) }
    } catch { }
    return 0
}

function Test-OnyxHealth {
    param([int]$Port)
    Print-Info "Checking Onyx service health..."
    Write-Host "Containers are healthy, waiting for database migrations and service initialization to finish."
    for ($attempt = 1; $attempt -le 600; $attempt++) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:$Port" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -in @(200, 301, 302, 303, 307, 308)) { return $true }
        } catch { }
        $m = [math]::Floor($attempt / 60); $s = $attempt % 60
        $dots = "." * (($attempt % 3) + 1); $pad = " " * (3 - $dots.Length)
        Write-Host -NoNewline "`rChecking Onyx service${dots}${pad} (${m}m ${s}s elapsed)"
        Start-Sleep -Seconds 1
    }
    Write-Host ""; return $false
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedRelaunch {
    if (Test-IsAdmin) { return $false }
    Print-Info "Administrator privileges required. Relaunching as Administrator..."
    if (-not $PSCommandPath) { Print-Warning "Cannot determine script path. Please re-run as Administrator."; return $false }
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($Shutdown)     { $argList += "-Shutdown" }
    if ($DeleteData)   { $argList += "-DeleteData" }
    if ($IncludeCraft) { $argList += "-IncludeCraft" }
    if ($Lite)         { $argList += "-Lite" }
    if ($Local)        { $argList += "-Local" }
    if ($NoPrompt)     { $argList += "-NoPrompt" }
    if ($DryRun)       { $argList += "-DryRun" }
    if ($ShowVerbose)  { $argList += "-ShowVerbose" }
    try { $proc = Start-Process powershell -ArgumentList $argList -Verb RunAs -Wait -PassThru; exit $proc.ExitCode }
    catch { Print-Warning "UAC elevation was declined or failed."; return $false }
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

# ── Help / Shutdown / Delete ─────────────────────────────────────────────────

function Show-OnyxHelp {
    $help = "Onyx Installation Script for Windows`n"
    $help += "`nUsage: .\install.ps1 [OPTIONS]`n"
    $help += "`nOptions:"
    $help += "`n  -IncludeCraft  Enable Onyx Craft (AI-powered web app building)"
    $help += "`n  -Lite          Deploy Onyx Lite (no Vespa, Redis, or model servers)"
    $help += "`n  -Local         Use existing config files instead of downloading from GitHub"
    $help += "`n  -Shutdown      Stop (pause) Onyx containers"
    $help += "`n  -DeleteData    Remove all Onyx data (containers, volumes, and files)"
    $help += "`n  -NoPrompt      Run non-interactively with defaults (for CI/automation)"
    $help += "`n  -DryRun        Show what would be done without making changes"
    $help += "`n  -ShowVerbose   Show detailed output for debugging"
    $help += "`n  -Help          Show this help message"
    $help += "`n`nExamples:"
    $help += "`n  .\install.ps1                    # Install Onyx"
    $help += "`n  .\install.ps1 -Lite              # Install Onyx Lite"
    $help += "`n  .\install.ps1 -IncludeCraft      # Install with Craft enabled"
    $help += "`n  .\install.ps1 -Shutdown          # Pause Onyx services"
    $help += "`n  .\install.ps1 -DeleteData        # Completely remove Onyx"
    $help += "`n  .\install.ps1 -Local             # Re-run using existing config"
    $help += "`n  .\install.ps1 -NoPrompt          # Non-interactive install"
    Write-Host $help
}

function Invoke-OnyxShutdown {
    Write-Host "`n=== Shutting down Onyx ===`n" -ForegroundColor Cyan
    $deployDir = Join-Path $script:InstallRoot "deployment"
    if (-not (Test-Path (Join-Path $deployDir "docker-compose.yml"))) {
        Print-Warning "Onyx deployment not found. Nothing to shutdown."
        return
    }
    if (-not (Initialize-ComposeCommand)) { Print-OnyxError "Docker Compose not found."; exit 1 }
    $stopArgs = @("stop")
    $result = Invoke-Compose -AutoDetect @stopArgs
    if ($result -ne 0) { Print-OnyxError "Failed to stop containers"; exit 1 }
    Print-Success "Onyx containers stopped (paused)"
}

function Invoke-OnyxDeleteData {
    Write-Host "`n=== WARNING: This will permanently delete all Onyx data ===`n" -ForegroundColor Red
    Print-Warning "This action will remove all Onyx containers, volumes, files, and user data."
    if (Test-Interactive) {
        $confirm = Read-Host "Type 'DELETE' to confirm"
        if ($confirm -ne "DELETE") { Print-Info "Operation cancelled."; return }
    } else {
        Print-OnyxError "Cannot confirm destructive operation in non-interactive mode."
        exit 1
    }
    $deployDir = Join-Path $script:InstallRoot "deployment"
    if ((Test-Path (Join-Path $deployDir "docker-compose.yml")) -and (Initialize-ComposeCommand)) {
        $downArgs = @("down", "-v")
        $result = Invoke-Compose -AutoDetect @downArgs
        if ($result -eq 0) { Print-Success "Containers and volumes removed" }
        else { Print-OnyxError "Failed to remove containers" }
    }
    if (Test-Path $script:InstallRoot) {
        Remove-Item -Recurse -Force $script:InstallRoot
        Print-Success "Data directories removed"
    }
    Print-Success "All Onyx data has been permanently deleted!"
}

# ── Docker Daemon ────────────────────────────────────────────────────────────

function Wait-ForDockerDaemon {
    param([int]$MaxWait = 60)
    Print-Info "Waiting for Docker daemon to become ready (up to ${MaxWait} seconds)..."
    $waited = 0; $lastError = ""; $unchangedErrorCount = 0
    while ($waited -lt $MaxWait) {
        Start-Sleep -Seconds 3; $waited += 3
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $dockerOutput = & docker info 2>&1
        $ErrorActionPreference = $prevEAP
        $errRecords = @($dockerOutput | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
        $currentError = if ($errRecords.Count -gt 0) { $errRecords[0].ToString() } else { "" }
        if ($LASTEXITCODE -eq 0) { Write-Host ""; Print-Success "Docker daemon is running"; return $true }
        if ($currentError) {
            if ($currentError -eq $lastError) { $unchangedErrorCount++ } else { $unchangedErrorCount = 0; $lastError = $currentError }
            if ($unchangedErrorCount -ge 5) {
                Write-Host ""; Print-OnyxError "Docker daemon is not starting. Persistent error after ${waited}s:"
                Write-Host "    $lastError" -ForegroundColor Red; return $false
            }
        }
        $dots = "." * (($waited / 3 % 3) + 1); $pad = " " * (3 - $dots.Length)
        Write-Host -NoNewline "`rWaiting for Docker daemon${dots}${pad} (${waited}s elapsed)"
    }
    Write-Host ""; Print-OnyxError "Docker daemon did not respond within ${MaxWait} seconds."
    if ($lastError) { Print-Info "Last error: $lastError" }
    return $false
}

function Fix-DockerCredStore {
    $configFile = Join-Path $env:USERPROFILE ".docker\config.json"
    if (-not (Test-Path $configFile)) { return }
    try {
        $rawBytes = [System.IO.File]::ReadAllBytes($configFile)
        $hasBom = $rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF
        $raw = [System.IO.File]::ReadAllText($configFile).TrimStart([char]0xFEFF)
        $config = $raw | ConvertFrom-Json
        $needsRewrite = $hasBom
        # Check property existence (not truthiness -- "" is falsy in PS)
        if ($null -ne $config.PSObject.Properties['credsStore']) {
            Print-Info "Removing credsStore='$($config.credsStore)' from Docker config..."
            $config.PSObject.Properties.Remove('credsStore')
            $needsRewrite = $true
        }
        if ($null -ne $config.PSObject.Properties['credHelpers']) {
            Print-Info "Removing credHelpers from Docker config..."
            $config.PSObject.Properties.Remove('credHelpers')
            $needsRewrite = $true
        }
        if ($needsRewrite) {
            Write-Utf8NoBom -Path $configFile -Content ($config | ConvertTo-Json -Depth 10)
            Print-Success "Docker credential config cleaned"
        }
    } catch {
        Print-Warning "Could not update Docker config: $_"
        try { Write-Utf8NoBom -Path $configFile -Content '{}'; Print-Success "Docker config reset" }
        catch { Print-Warning "Could not reset Docker config: $_" }
    }

}

function Register-DockerService {
    if (Get-Service docker -ErrorAction SilentlyContinue) { return $true }
    Print-Info "Docker service not registered. Looking for dockerd.exe..."
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\dockerd.exe"),
        (Join-Path $env:ProgramFiles "Docker\dockerd.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\dockerd.exe")
    )
    $dockerExe = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerExe) { $candidates = @((Join-Path (Split-Path $dockerExe.Source) "dockerd.exe")) + $candidates }
    $dockerdPath = $null
    foreach ($c in $candidates) { if (Test-Path $c) { $dockerdPath = $c; break } }
    if (-not $dockerdPath) {
        Print-OnyxError "Could not find dockerd.exe to register as a service."
        return $false
    }
    Print-Info "Found dockerd at: $dockerdPath"
    Invoke-NativeQuiet { & $dockerdPath --register-service }
    if ($LASTEXITCODE -ne 0) {
        Print-Warning "dockerd --register-service failed (code $LASTEXITCODE), trying sc.exe..."
        Invoke-NativeQuiet { sc.exe create docker binPath= "`"$dockerdPath`" --run-service" start= auto }
    }
    if (-not (Get-Service docker -ErrorAction SilentlyContinue)) {
        Print-OnyxError "Failed to register Docker as a Windows service."
        return $false
    }
    Print-Success "Docker service registered"
    return $true
}

function Start-DockerDaemon {
    Invoke-NativeQuiet { docker info }
    if ($LASTEXITCODE -eq 0) { return $true }

    if ($script:IsWindowsServer) {
        Print-Info "Windows Server detected - starting Docker..."
        # Prefer Docker Desktop if installed (provides Linux containers);
        # native dockerd on Windows Server only supports Windows containers.
        $ddExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $ddExe) {
            Print-Info "Docker Desktop is installed - using it for Linux container support."
            # Stop native Docker service if running to avoid pipe conflicts
            $svc = Get-Service docker -ErrorAction SilentlyContinue
            if ($svc -and $svc.Status -eq 'Running') {
                Print-Info "Stopping native Docker Engine service to avoid conflicts..."
                Stop-Service docker -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
            }
            Fix-DockerCredStore
            Start-Process $ddExe
            if (Wait-ForDockerDaemon -MaxWait 120) { return $true }
            Print-Warning "Docker Desktop did not start. Falling back to Docker Engine service..."
        }
        # Fallback: native dockerd service (Windows containers only)
        if (-not (Register-DockerService)) { return $false }
        Fix-DockerCredStore
        try { Start-Service docker -ErrorAction Stop; Print-Success "Docker service started" }
        catch { Print-Warning "Failed to start Docker service: $_"; return $false }
        return (Wait-ForDockerDaemon -MaxWait 60)
    }

    # Windows Desktop - start Docker Desktop
    Print-Info "Starting Docker Desktop..."
    $launchPath = $null
    foreach ($path in @(
        "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "${env:LOCALAPPDATA}\Docker\Docker Desktop.exe"
    )) {
        if (Test-Path $path) { Start-Process $path; $launchPath = $path; break }
    }
    if (-not $launchPath) {
        try { Start-Process "Docker Desktop" -ErrorAction Stop }
        catch { Print-Warning "Could not find Docker Desktop executable."; return $false }
    }
    if (-not (Wait-ForDockerDaemon -MaxWait 120)) {
        $proc = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
        if ($proc) { Print-Info "Docker Desktop IS running (PID: $($proc.Id)), but the daemon is not responding." }
        else { Print-Warning "Docker Desktop process is NOT running - it may have crashed." }
        Print-Info "Try starting Docker Desktop manually, check WSL2 status, or restart your computer."
        return $false
    }
    Print-Info "Waiting 15 seconds for Docker Desktop to fully stabilize..."
    Start-Sleep -Seconds 15
    return $true
}

# ── Docker Install ───────────────────────────────────────────────────────────

function Install-DockerEngine {
    Print-Info "Windows Server detected - Docker Engine is required."
    if (-not (Confirm-Action "Docker Engine (Windows Server)")) { exit 1 }
    if (-not (Test-IsAdmin)) { Invoke-ElevatedRelaunch }

    try {
        $feature = Get-WindowsFeature -Name Containers -ErrorAction Stop
        if ($feature.InstallState -ne 'Installed') {
            Print-Info "Installing Windows Containers feature..."
            $result = Install-WindowsFeature -Name Containers -ErrorAction Stop
            if ($result.RestartNeeded -eq 'Yes') {
                Print-Warning "A reboot is required. Please restart and re-run this script."
                exit 0
            }
            Print-Success "Containers feature installed"
        }
    } catch { Print-Warning "Could not check/install Containers feature: $_" }

    $installed = $false

    if (-not $installed) {
        Print-Info "Attempting Docker install via DockerMsftProvider..."
        try {
            if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
                Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
            }
            if (-not (Get-Module DockerMsftProvider -ListAvailable -ErrorAction SilentlyContinue)) {
                Install-Module -Name DockerMsftProvider -Repository PSGallery -Force
            }
            Install-Package -Name docker -ProviderName DockerMsftProvider -Force | Out-Null
            $installed = $true
            Print-Success "Docker installed via DockerMsftProvider"
        } catch { Print-Warning "DockerMsftProvider failed: $_" }
    }

    if (-not $installed) {
        Print-Info "Downloading Docker binaries directly..."
        try {
            $page = Invoke-WebRequest -Uri "https://download.docker.com/win/static/stable/x86_64/" -UseBasicParsing -ErrorAction Stop
            $latestZip = $page.Links | Where-Object { $_.href -match '^docker-\d+.*\.zip$' } |
                Sort-Object href -Descending | Select-Object -First 1
            if (-not $latestZip) { throw "Could not find Docker zip" }
            $zipPath = Join-Path $env:TEMP "docker-ce.zip"
            Download-OnyxFile -Url "https://download.docker.com/win/static/stable/x86_64/$($latestZip.href)" -Output $zipPath
            Expand-Archive -Path $zipPath -DestinationPath $env:ProgramFiles -Force
            Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
            $dockerPath = Join-Path $env:ProgramFiles "docker"
            $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            if ($machinePath -notlike "*$dockerPath*") {
                [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$dockerPath", "Machine")
            }
            Refresh-PathFromRegistry
            & "$dockerPath\dockerd.exe" --register-service
            $installed = $true
            Print-Success "Docker installed and registered as service"
        } catch { Print-Warning "Direct binary install failed: $_" }
    }

    if (-not $installed) {
        Print-OnyxError "Could not install Docker Engine on Windows Server."
        Print-Info "Install manually: https://docs.docker.com/engine/install/binaries/#install-server-and-client-binaries-on-windows"
        exit 1
    }

    try { Start-Service docker -ErrorAction Stop; Print-Success "Docker service started" }
    catch { Print-OnyxError "Failed to start Docker service: $_"; exit 1 }
    Install-ComposePlugin
    if (-not (Wait-ForDockerDaemon -MaxWait 30)) { Print-OnyxError "Docker installed but daemon not responding."; exit 1 }
    Print-Success "Docker Engine installed and running on Windows Server"
}

function Install-ComposePlugin {
    Invoke-NativeQuiet { docker compose version }
    if ($LASTEXITCODE -eq 0) { return }
    if (-not (Confirm-Action "Docker Compose plugin")) { return }
    Print-Info "Installing Docker Compose plugin..."
    $dest = Join-Path $env:ProgramFiles "docker\cli-plugins"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    try {
        Download-OnyxFile -Url "https://github.com/docker/compose/releases/latest/download/docker-compose-windows-x86_64.exe" -Output (Join-Path $dest "docker-compose.exe")
        Print-Success "Docker Compose plugin installed"
    } catch {
        Print-Warning "Failed to install Docker Compose plugin: $_"
    }
}

function Install-Wsl {
    Invoke-NativeQuiet { wsl --status }
    if ($LASTEXITCODE -eq 0) { Print-Success "WSL2 is available"; return $true }
    if (-not (Confirm-Action "WSL2 (required for Docker)")) { return $false }
    Print-Info "Installing WSL2..."
    try {
        $proc = Start-Process wsl -ArgumentList "--install", "--no-distribution" -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0) { Print-Success "WSL2 installed"; return $true }
        Print-Warning "WSL2 install exited with code $($proc.ExitCode). A reboot may be required."
        return $false
    } catch { Print-Warning "Failed to install WSL2: $_"; return $false }
}

function Install-DockerDesktop {
    Print-Info "Docker Desktop is required but not installed."
    if (-not (Confirm-Action "Docker Desktop")) { exit 1 }
    if (-not (Test-IsAdmin)) { Invoke-ElevatedRelaunch }
    $wslReady = Install-Wsl
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Print-Info "Installing Docker Desktop via winget..."
        winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { Print-Success "Docker Desktop installed via winget"; $installed = $true }
    }

    if (-not $installed -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Print-Info "Installing Docker Desktop via Chocolatey..."
        choco install docker-desktop -y
        if ($LASTEXITCODE -eq 0) { Print-Success "Docker Desktop installed via Chocolatey"; $installed = $true }
    }

    if (-not $installed) {
        Print-Info "Downloading Docker Desktop installer directly..."
        $installerPath = Join-Path $env:TEMP "DockerDesktopInstaller_$([System.IO.Path]::GetRandomFileName().Split('.')[0]).exe"
        try {
            Download-OnyxFile -Url "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" -Output $installerPath
            $proc = Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -PassThru -NoNewWindow
            if ($proc.ExitCode -eq 0) {
                Print-Success "Docker Desktop installed via direct download"; $installed = $true
            } elseif ($proc.ExitCode -eq 3) {
                Print-Warning "Prerequisites not met."
                if (-not $wslReady) { Print-OnyxError "WSL2 is required. Run: wsl --install --no-distribution, then reboot." }
                else { Print-Info "A reboot may be needed. Restart and re-run this script." }
            } else {
                Print-Warning "Installer exited with code $($proc.ExitCode)."
                if (-not (Test-IsAdmin)) { Print-Info "Try re-running as Administrator." }
            }
        } catch { Print-Warning "Direct download failed: $_" }
        finally { Remove-Item -Force $installerPath -ErrorAction SilentlyContinue }
    }

    if (-not $installed) {
        Print-OnyxError "Could not install Docker Desktop automatically."
        Print-Info "Install manually: https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }

    Refresh-PathFromRegistry
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Print-OnyxError "Docker installed but 'docker' command not available. Restart your terminal and re-run."
        exit 1
    }
    if (-not (Start-DockerDaemon)) {
        Print-OnyxError "Docker Desktop installed but could not be started. Launch it from the Start Menu and re-run."
        exit 1
    }
    Print-Success "Docker Desktop installed and running"
}

function Invoke-WslInstall {
    Print-Info "Native Docker on Windows Server only supports Windows containers."
    Print-Info "Onyx will be installed via WSL2 (Windows Subsystem for Linux)."
    if (-not (Confirm-Action "Onyx via WSL2 (installs WSL2 + Ubuntu + Docker inside Linux)")) { exit 1 }
    if (-not (Test-IsAdmin)) { Invoke-ElevatedRelaunch }

    # Free memory by stopping the Windows Docker service (not needed once we use WSL2)
    $svc = Get-Service docker -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Print-Info "Stopping Windows Docker service to free memory for WSL2..."
        Stop-Service docker -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }

    # Check available memory before proceeding
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        Print-Info "System memory: ${totalGB}GB total, ${freeGB}GB free"
        if ($totalGB -lt 4) {
            Print-OnyxError "Onyx requires at least 4GB RAM (Lite mode) or 10GB RAM (Standard mode)."
            Print-Info "This machine has ${totalGB}GB total. Consider using a larger instance."
            exit 1
        }
    } catch {}

    # Ensure WSL2 is available
    Invoke-NativeQuiet { wsl --status }
    if ($LASTEXITCODE -ne 0) {
        Print-Info "Installing WSL2..."
        try {
            $proc = Start-Process wsl -ArgumentList "--install", "--no-distribution" -Wait -PassThru -NoNewWindow
            if ($proc.ExitCode -ne 0) {
                Print-OnyxError "WSL2 installation failed (code $($proc.ExitCode)). A reboot may be needed."
                Print-Info "After rebooting, re-run this script."
                exit 1
            }
        } catch {
            Print-OnyxError "Could not install WSL2: $_"
            exit 1
        }
    }
    Print-Success "WSL2 is available"

    # Ensure Ubuntu is installed in WSL
    $distros = (Invoke-NativeQuiet -PassThru { wsl -l -q }) -join "`n"
    if ($distros -notmatch "Ubuntu") {
        Print-Info "Installing Ubuntu in WSL2..."
        $proc = Start-Process wsl -ArgumentList "--install", "-d", "Ubuntu" -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -ne 0) {
            Print-OnyxError "Ubuntu installation failed. Try manually: wsl --install -d Ubuntu"
            Print-Info "If this is a memory error, this machine needs at least 4GB RAM."
            exit 1
        }
    }
    Print-Success "Ubuntu is available in WSL2"

    # Build the install.sh invocation to run inside WSL2
    Print-Info "Handing off to the Linux install script inside WSL2..."
    $bashArgs = @()
    if ($script:LiteMode) { $bashArgs += "--lite" }
    if ($script:IncludeCraftMode) { $bashArgs += "--include-craft" }
    if ($NoPrompt) { $bashArgs += "--no-prompt" }
    if ($ShowVerbose) { $bashArgs += "--verbose" }

    $installUrl = "$($script:GitHubRawUrl)/install.sh"
    $bashCmd = "curl -fsSL '$installUrl' | bash -s -- $($bashArgs -join ' ')"
    Print-Info "Running: $bashCmd"
    wsl -d Ubuntu -- bash -c $bashCmd
    $wslExit = $LASTEXITCODE

    if ($wslExit -eq 0) {
        Print-Success "Onyx installation complete (via WSL2)"
        # Determine the port Onyx is running on inside WSL
        Print-Info "Onyx should be accessible at http://localhost:3000"
        Print-Info "WSL2 automatically forwards ports to the Windows host."
    } else {
        Print-OnyxError "Installation inside WSL2 exited with code $wslExit"
        Print-Info "You can debug by running: wsl -d Ubuntu"
    }
    exit $wslExit
}

function Install-Docker {
    if ($script:IsWindowsServer) { Install-DockerEngine } else { Install-DockerDesktop }
}

# ── Main Installation Flow ───────────────────────────────────────────────────

function Main {
    if ($Help) { Show-OnyxHelp; return }
    if ($PSVersionTable.PSVersion.Major -lt 5) { Print-OnyxError "PowerShell 5+ required (found $($PSVersionTable.PSVersion))"; exit 1 }
    if ($script:LiteMode -and $script:IncludeCraftMode) {
        Print-OnyxError "-Lite and -IncludeCraft cannot be used together."
        exit 1
    }
    if ($script:LiteMode) { $script:ExpectedDockerRamGB = 4; $script:ExpectedDiskGB = 16 }
    if ($Shutdown)   { Invoke-OnyxShutdown; return }
    if ($DeleteData) { Invoke-OnyxDeleteData; return }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Install-Docker }

    # Banner
    $edition = if ($script:IsWindowsServer) { "Windows Server" } else { "Windows Desktop" }
    Write-Host "`n   ____`n  / __ \`n | |  | |_ __  _   ___  __`n | |  | | '_ \| | | \ \/ /`n | |__| | | | | |_| |>  < `n  \____/|_| |_|\__, /_/\_\`n                __/ |`n               |___/" -ForegroundColor Cyan
    Write-Host "Welcome to Onyx Installation Script (Windows)"
    Write-Host "=============================================="
    Print-Success "$edition detected"
    Write-Host "This script will:" -ForegroundColor Yellow
    Write-Host "1. Download deployment files for Onyx into a new '$($script:InstallRoot)' directory"
    Write-Host "2. Check your system resources (Docker, memory, disk space)"
    Write-Host "3. Guide you through deployment options (version, authentication)"

    if (Test-Interactive) {
        Write-Host "`nPlease acknowledge and press Enter to continue..." -ForegroundColor Yellow
        Read-Host | Out-Null
    } else {
        Write-Host "`nRunning in non-interactive mode - proceeding automatically..." -ForegroundColor Yellow
    }

    if ($DryRun) {
        Print-Info "Dry run mode - showing what would happen:"
        Write-Host "  - Install root: $($script:InstallRoot)  Lite: $($script:LiteMode)  Craft: $($script:IncludeCraftMode)"
        Write-Host "  - OS: Windows $([System.Environment]::OSVersion.Version)  PS: $($PSVersionTable.PSVersion)"
        Print-Success "Dry run complete (no changes made)"
        return
    }
    if ($ShowVerbose) { Print-Info "Verbose mode enabled" }

    # ── Step 1: Verify Docker ─────────────────────────────────────────────
    Print-Step "Verifying Docker installation"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Install-Docker }
    $dockerVersion = Get-NativeVersionString { docker --version }
    Print-Success "Docker $dockerVersion is installed"

    if (-not (Initialize-ComposeCommand)) {
        if ($script:IsWindowsServer) {
            Install-ComposePlugin
            if (-not (Initialize-ComposeCommand)) { Print-OnyxError "Docker Compose could not be installed."; exit 1 }
        } else {
            Print-OnyxError "Docker Compose is not installed. Docker Desktop includes it."
            Print-Info "Visit: https://docs.docker.com/desktop/install/windows-install/"
            exit 1
        }
    }
    $composeVersion = Get-NativeVersionString { if ($script:ComposeCmdType -eq "plugin") { docker compose version } else { docker-compose --version } }
    Print-Success "Docker Compose $composeVersion is installed ($($script:ComposeCmdType))"

    Invoke-NativeQuiet { docker info }
    if ($LASTEXITCODE -ne 0) {
        $label = if ($script:IsWindowsServer) { "Docker service" } else { "Docker Desktop" }
        Print-Info "Docker daemon is not running. Starting $label..."
        if (-not (Start-DockerDaemon)) { Print-OnyxError "Could not start Docker. Start it manually and re-run."; exit 1 }
    }
    Print-Success "Docker daemon is running"
    if ($script:IsWindowsServer) { Fix-DockerCredStore }

    # Verify Docker is running Linux containers (Onyx images are Linux-based)
    $osType = ((Invoke-NativeQuiet -PassThru { docker info --format '{{.OSType}}' }) -join "").Trim()
    if ($osType -eq "windows") {
        Print-Warning "Docker is running in Windows containers mode, but Onyx requires Linux containers."
        $switchCli = Join-Path $env:ProgramFiles "Docker\Docker\DockerCli.exe"
        $switched = $false
        if (Test-Path $switchCli) {
            Print-Info "Attempting to switch to Linux containers via DockerCli..."
            try { & $switchCli -SwitchLinuxEngine 2>$null } catch {}
            Start-Sleep -Seconds 15
            for ($w = 0; $w -lt 12; $w++) {
                Invoke-NativeQuiet { docker info }
                if ($LASTEXITCODE -eq 0) { break }
                Start-Sleep -Seconds 5
            }
            $osType2 = ((Invoke-NativeQuiet -PassThru { docker info --format '{{.OSType}}' }) -join "").Trim()
            $switched = ($osType2 -eq "linux")
        }
        if ($switched) {
            Print-Success "Switched to Linux containers"
        } else {
            Print-Info "Native Docker on Windows Server only supports Windows containers."
            Print-Info "Switching to WSL2 approach for Linux container support..."
            Invoke-WslInstall
        }
    }

    # ── Step 2: Verify Resources ──────────────────────────────────────────
    Print-Step "Verifying Docker resources"
    $memoryMB = Get-DockerMemoryMB
    if ($memoryMB -gt 0) {
        $memoryGB = [math]::Round($memoryMB / 1024, 1)
        $memoryDisplay = if ($memoryGB -ge 1) { "~${memoryGB}GB" } else { "${memoryMB}MB" }
        Print-Info "Docker memory allocation: $memoryDisplay"
    } else {
        Print-Warning "Could not determine memory allocation"
        $memoryDisplay = "unknown"
    }

    $diskAvailableGB = [math]::Floor((Get-PSDrive -Name (Get-Location).Drive.Name).Free / 1GB)
    Print-Info "Available disk space: ${diskAvailableGB}GB"

    $resourceWarning = $false
    if ($memoryMB -gt 0 -and $memoryMB -lt ($script:ExpectedDockerRamGB * 1024)) {
        Print-Warning "Less than $($script:ExpectedDockerRamGB)GB RAM available (found: $memoryDisplay)"
        $resourceWarning = $true
    }
    if ($diskAvailableGB -lt $script:ExpectedDiskGB) {
        Print-Warning "Less than $($script:ExpectedDiskGB)GB disk space available (found: ${diskAvailableGB}GB)"
        $resourceWarning = $true
    }
    if ($resourceWarning) {
        Print-Warning "Onyx recommends at least $($script:ExpectedDockerRamGB)GB RAM and $($script:ExpectedDiskGB)GB disk for standard mode."
        Print-Warning "Lite mode requires less (1-4GB RAM, 8-16GB disk) but has no vector database."
        $reply = Prompt-OrDefault "Do you want to continue anyway? (Y/n)" "y"
        if ($reply -notmatch '^[Yy]') { Print-Info "Installation cancelled."; exit 1 }
        Print-Info "Proceeding despite resource limitations..."
    }

    # ── Step 3: Create Directories ────────────────────────────────────────
    Print-Step "Creating directory structure"
    if (Test-Path $script:InstallRoot) { Print-Info "Using existing $($script:InstallRoot) directory" }
    $deploymentDir = Join-Path $script:InstallRoot "deployment"
    New-Item -ItemType Directory -Force -Path $deploymentDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $script:InstallRoot "data\nginx\local") | Out-Null
    Print-Success "Directory structure created"

    # ── Step 4: Download Config Files ─────────────────────────────────────
    if ($Local) { Print-Step "Verifying existing configuration files" }
    else { Print-Step "Downloading Onyx configuration files" }

    $composeDest = Join-Path $deploymentDir "docker-compose.yml"
    if (-not (Ensure-OnyxFile $composeDest "$($script:GitHubRawUrl)/docker-compose.yml" "docker-compose.yml")) { exit 1 }

    if ($composeVersion -ne "unknown" -and (Compare-SemVer $composeVersion "2.24.0") -lt 0) {
        Print-Warning "Docker Compose $composeVersion is older than 2.24.0 (required for env_file format)."
        Print-Info "Update Docker Desktop or install a newer Docker Compose. Installation may fail."
        $reply = Prompt-OrDefault "Continue anyway? (Y/n)" "y"
        if ($reply -notmatch '^[Yy]') { exit 1 }
    }

    $liteOverlayPath = Join-Path $deploymentDir $script:LiteComposeFile
    if ($script:LiteMode) {
        if (-not (Ensure-OnyxFile $liteOverlayPath "$($script:GitHubRawUrl)/$($script:LiteComposeFile)" $script:LiteComposeFile)) { exit 1 }
    }

    $envTemplateDest = Join-Path $deploymentDir "env.template"
    if (-not (Ensure-OnyxFile $envTemplateDest "$($script:GitHubRawUrl)/env.template" "env.template")) { exit 1 }
    if (-not (Ensure-OnyxFile (Join-Path $script:InstallRoot "data\nginx\app.conf.template") "$($script:NginxBaseUrl)/app.conf.template" "nginx/app.conf.template")) { exit 1 }
    if (-not (Ensure-OnyxFile (Join-Path $script:InstallRoot "data\nginx\run-nginx.sh") "$($script:NginxBaseUrl)/run-nginx.sh" "nginx/run-nginx.sh")) { exit 1 }
    if (-not (Ensure-OnyxFile (Join-Path $script:InstallRoot "README.md") "$($script:GitHubRawUrl)/README.md" "README.md")) { exit 1 }

    $gitkeep = Join-Path $script:InstallRoot "data\nginx\local\.gitkeep"
    if (-not (Test-Path $gitkeep)) { New-Item -ItemType File -Force -Path $gitkeep | Out-Null }
    Print-Success "All configuration files ready"

    # ── Step 5: Deployment Config ─────────────────────────────────────────
    Print-Step "Setting up deployment configs"
    $envFile = Join-Path $deploymentDir ".env"

    # Check if services are already running
    if ((Test-Path $composeDest) -and (Initialize-ComposeCommand)) {
        $running = @()
        $psArgs = @("ps", "-q")
        try { $running = @(Invoke-Compose -AutoDetect @psArgs 2>$null | Where-Object { $_ }) } catch { }
        if ($running.Count -gt 0) {
            Print-OnyxError "Onyx services are currently running!"
            Print-Info "Run '.\install.ps1 -Shutdown' first, then re-run this script."
            exit 1
        }
    }

    $version = "latest"

    if (Test-Path $envFile) {
        Print-Info "Existing .env file found. What would you like to do?"
        Write-Host "  - Press Enter to restart with current configuration"
        Write-Host "  - Type 'update' to update to a newer version"
        $reply = Prompt-OrDefault "Choose an option [default: restart]" ""

        Prompt-DeploymentMode -LiteOverlayPath $liteOverlayPath

        if ($reply -eq "update") {
            $version = Prompt-VersionTag
            Assert-NotCraftLite $version
            Set-EnvFileValue -Path $envFile -Key "IMAGE_TAG" -Value $version
            Print-Success "Updated IMAGE_TAG to $version"
            if ($version -match '^craft-') {
                Set-EnvFileValue -Path $envFile -Key "ENABLE_CRAFT" -Value "true" -Uncomment
            }
        } else {
            Assert-NotCraftLite (Get-EnvFileValue -Path $envFile -Key "IMAGE_TAG")
            Print-Info "Keeping existing configuration"
        }
        if ($script:LiteMode) {
            $profiles = Get-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES"
            if ($profiles -and $profiles -match 's3-filestore') {
                Set-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES" -Value ""
            }
        }
    } else {
        Print-Info "No existing .env file found. Setting up new deployment..."
        Prompt-DeploymentMode -LiteOverlayPath $liteOverlayPath
        if ($script:LiteMode -and $script:IncludeCraftMode) {
            Print-OnyxError "-IncludeCraft cannot be used with Lite mode."
            exit 1
        }
        if ($script:LiteMode) { $script:ExpectedDockerRamGB = 4; $script:ExpectedDiskGB = 16 }

        $version = Prompt-VersionTag
        Assert-NotCraftLite $version

        Copy-Item -Path $envTemplateDest -Destination $envFile -Force
        Set-EnvFileValue -Path $envFile -Key "IMAGE_TAG" -Value $version
        Print-Success "IMAGE_TAG set to $version"
        if ($script:LiteMode) { Set-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES" -Value "" }
        Set-EnvFileValue -Path $envFile -Key "AUTH_TYPE" -Value "basic"
        Print-Success "Basic authentication enabled"
        Set-EnvFileValue -Path $envFile -Key "USER_AUTH_SECRET" -Value "`"$(New-SecureSecret)`""
        Print-Success "Generated secure USER_AUTH_SECRET"
        if ($script:IncludeCraftMode -or $version -match '^craft-') {
            Set-EnvFileValue -Path $envFile -Key "ENABLE_CRAFT" -Value "true" -Uncomment
            Print-Success "Onyx Craft enabled"
        } else {
            Print-Info "Onyx Craft disabled (use -IncludeCraft to enable)"
        }
        Print-Success ".env file created"
        Print-Info "You can customize .env later for OAuth/SAML, AI models, domain settings, and Craft."
    }

    # Clean up stale lite overlay if standard mode was selected
    if (-not $script:LiteMode -and (Test-Path $liteOverlayPath)) {
        Remove-Item -Force $liteOverlayPath
        Print-Info "Removed previous lite overlay (switching to standard mode)"
    }

    # ── Step 6: Check Ports ───────────────────────────────────────────────
    Print-Step "Checking for available ports"
    $availablePort = Find-AvailablePort 3000
    if ($availablePort -ne 3000) { Print-Info "Port 3000 in use, using port $availablePort" }
    else { Print-Info "Port 3000 is available" }
    $env:HOST_PORT = $availablePort
    Print-Success "Using port $availablePort for nginx"

    $currentImageTag = Get-EnvFileValue -Path $envFile -Key "IMAGE_TAG"
    $useLatest = ($currentImageTag -eq "edge" -or $currentImageTag -eq "latest" -or $currentImageTag -match '^craft-')
    if ($useLatest) { Print-Info "Using '$currentImageTag' tag - will force pull and recreate containers" }

    # For pinned version tags, re-download config files from that tag so the
    # compose file matches the images being pulled (the initial download used main).
    if (-not $useLatest -and -not $Local) {
        $pinnedBase = "https://raw.githubusercontent.com/onyx-dot-app/onyx/$currentImageTag/deployment"
        Print-Info "Fetching config files matching tag $currentImageTag..."
        try {
            Download-OnyxFile "$pinnedBase/docker_compose/docker-compose.yml" $composeDest
            try { Download-OnyxFile "$pinnedBase/data/nginx/app.conf.template" (Join-Path $script:InstallRoot "data\nginx\app.conf.template") } catch {}
            try { Download-OnyxFile "$pinnedBase/data/nginx/run-nginx.sh" (Join-Path $script:InstallRoot "data\nginx\run-nginx.sh") } catch {}
            if ($script:LiteMode) {
                try { Download-OnyxFile "$pinnedBase/docker_compose/$($script:LiteComposeFile)" $liteOverlayPath } catch {}
            }
            Print-Success "Config files updated to match $currentImageTag"
        } catch {
            Print-Warning "Tag $currentImageTag not found on GitHub - using main branch configs"
        }
    }

    # ── Step 7: Pull Images ───────────────────────────────────────────────
    Print-Step "Pulling Docker images"
    Print-Info "This may take several minutes depending on your internet connection..."

    $pullArgs = @("pull"); if (-not $ShowVerbose) { $pullArgs += "--quiet" }
    if ((Invoke-Compose @pullArgs) -ne 0) { Print-OnyxError "Failed to download Docker images"; exit 1 }
    Print-Success "Docker images downloaded successfully"

    # ── Step 8: Start Services ────────────────────────────────────────────
    Print-Step "Starting Onyx services"
    Print-Info "Launching containers..."
    $upArgs = @("up", "-d")
    if ($useLatest) { $upArgs += @("--pull", "always", "--force-recreate") }
    $upResult = Invoke-Compose @upArgs
    if ($upResult -ne 0) { Print-OnyxError "Failed to start Onyx services"; exit 1 }

    # ── Step 9: Container Health ──────────────────────────────────────────
    Print-Step "Verifying container health"
    Start-Sleep -Seconds 10
    $restartIssues = $false
    $containerIds = @()
    $psArgs = @("ps", "-q")
    try { $containerIds = @(Invoke-Compose @psArgs 2>$null | Where-Object { $_ }) } catch { }

    foreach ($cid in $containerIds) {
        if ([string]::IsNullOrWhiteSpace($cid)) { continue }
        $name = (& docker inspect --format '{{.Name}}' $cid 2>$null).TrimStart('/')
        $restarts = 0; try { $restarts = [int](& docker inspect --format '{{.RestartCount}}' $cid 2>$null) } catch { }
        $status = & docker inspect --format '{{.State.Status}}' $cid 2>$null
        if ($status -eq "running" -and $restarts -gt 2) {
            Print-OnyxError "$name is in a restart loop (restarted $restarts times)"; $restartIssues = $true
        } elseif ($status -eq "running") { Print-Success "$name is healthy" }
        elseif ($status -eq "restarting") { Print-OnyxError "$name is stuck restarting"; $restartIssues = $true }
        else { Print-Warning "$name status: $status" }
    }

    if ($restartIssues) {
        Print-OnyxError "Some containers are experiencing issues!"
        $cmd = if ($script:ComposeCmdType -eq "plugin") { "docker compose" } else { "docker-compose" }
        Print-Info "Check logs: cd `"$(Join-Path $script:InstallRoot 'deployment')`" && $cmd $((Get-ComposeFileArgs) -join ' ') logs"
        Print-Info "For help, contact: founders@onyx.app"
        exit 1
    }

    # ── Step 10: Complete ─────────────────────────────────────────────────
    Print-Step "Installation Complete!"
    Print-Success "All containers are running successfully!"
    $port = if ($env:HOST_PORT) { $env:HOST_PORT } else { 3000 }

    if (Test-OnyxHealth -Port $port) {
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "   Onyx service is ready!                   " -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
    } else {
        Print-Warning "Health check timed out after 10 minutes"
        Print-Info "Containers are running, but the web service may still be initializing."
        Write-Host "============================================" -ForegroundColor Yellow
        Write-Host "   Onyx containers are running              " -ForegroundColor Yellow
        Write-Host "============================================" -ForegroundColor Yellow
    }

    Print-Info "Access Onyx at: http://localhost:$port"
    Print-Info "Visit http://localhost:$port/auth/signup to create your admin account"
    Print-Info "The first user created will automatically have admin privileges"

    if ($script:LiteMode) {
        Print-Info "Running in Lite mode - Vespa, Redis, model servers, and background workers are NOT started."
        Print-Info "Connectors and RAG search are disabled. LLM chat, tools, Projects still work."
    }

    Print-Info "See the README in $($script:InstallRoot) for more information."
    Print-Info "For help or issues, contact: founders@onyx.app"
}

Main
