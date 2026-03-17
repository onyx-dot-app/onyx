# Onyx Installer for Windows
# Usage: irm https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.ps1 | iex
# Or:    .\install.ps1 [OPTIONS]
# With params via pipe:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.ps1))) -Lite -NoPrompt

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

# ── Native Command Helper ────────────────────────────────────────────────────
# PowerShell can treat native command stderr as a terminating error when
# $ErrorActionPreference is "Stop". This wrapper runs a command with stderr
# silenced and ErrorActionPreference temporarily set to Continue so that
# non-zero exit codes and stderr output don't throw.
# Pass -PassThru to capture stdout instead of suppressing it.
function Invoke-NativeQuiet {
    param([scriptblock]$Command, [switch]$PassThru)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($PassThru) { & $Command 2>$null }
        else           { $null = & $Command 2>$null }
    } finally { $ErrorActionPreference = $prev }
}

# ── Constants ────────────────────────────────────────────────────────────────

$script:ExpectedDockerRamGB = 10
$script:ExpectedDiskGB = 32
$script:InstallRoot = if ($env:INSTALL_PREFIX) { $env:INSTALL_PREFIX } else { "onyx_data" }
$script:LiteComposeFile = "docker-compose.onyx-lite.yml"
$script:GitHubRawUrl = "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose"
$script:NginxBaseUrl = "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/data/nginx"
$script:CurrentStep = 0
$script:TotalSteps = 10
$script:ComposeCmdType = $null  # "plugin" or "standalone"
$script:LiteMode = $Lite.IsPresent
$script:IncludeCraftMode = $IncludeCraft.IsPresent
# ProductType: 1 = Workstation (Windows 10/11), 2 = Domain Controller, 3 = Server
$script:IsWindowsServer = (Get-CimInstance Win32_OperatingSystem).ProductType -ne 1

# ── Output Helpers ───────────────────────────────────────────────────────────

function Print-Success { param([string]$Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Print-OnyxError { param([string]$Message) Write-Host "[X]  $Message" -ForegroundColor Red }
function Print-Info { param([string]$Message) Write-Host "[i]  $Message" -ForegroundColor Yellow }
function Print-Warning { param([string]$Message) Write-Host "[!]  $Message" -ForegroundColor Yellow }

function Print-Step {
    param([string]$Title)
    $script:CurrentStep++
    Write-Host ""
    Write-Host "=== $Title - Step $($script:CurrentStep)/$($script:TotalSteps) ===" -ForegroundColor Cyan
    Write-Host ""
}

# ── Interactive Prompt Helpers ───────────────────────────────────────────────

function Test-Interactive {
    if ($NoPrompt) { return $false }
    try {
        # IsInputRedirected is false for interactive terminals (local, SSH, RDP)
        # but true for piped invocations (irm ... | iex)
        if ([Console]::IsInputRedirected) { return $false }
        return $true
    } catch {
        # If Console class is unavailable, fall back to UserInteractive
        return [Environment]::UserInteractive
    }
}

function Prompt-OrDefault {
    param([string]$PromptText, [string]$DefaultValue)
    if (-not (Test-Interactive)) { return $DefaultValue }
    $reply = Read-Host $PromptText
    if ([string]::IsNullOrWhiteSpace($reply)) { return $DefaultValue }
    return $reply
}

function Prompt-YnOrDefault {
    param([string]$PromptText, [string]$DefaultValue)
    if (-not (Test-Interactive)) { return $DefaultValue }
    $reply = Read-Host $PromptText
    if ([string]::IsNullOrWhiteSpace($reply)) { return $DefaultValue }
    return $reply
}

# ── Download Helpers ─────────────────────────────────────────────────────────

function Download-OnyxFile {
    param([string]$Url, [string]$Output)
    $maxRetries = 3
    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $Output -UseBasicParsing -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq $maxRetries) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Ensure-OnyxFile {
    param([string]$Path, [string]$Url, [string]$Description)
    if ($Local) {
        if (Test-Path $Path) {
            Print-Success "Using existing $Description"
            return $true
        }
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
        Print-Info "Please ensure you have internet connection and try again"
        return $false
    }
}

# ── .env File Helpers ────────────────────────────────────────────────────────

function Set-EnvFileValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value,
        [switch]$Uncomment
    )
    $lines = Get-Content $Path
    $found = $false
    $result = @()
    foreach ($line in $lines) {
        if ($Uncomment -and $line -match "^\s*#\s*${Key}=") {
            $result += "${Key}=${Value}"
            $found = $true
        } elseif ($line -match "^${Key}=") {
            $result += "${Key}=${Value}"
            $found = $true
        } else {
            $result += $line
        }
    }
    if (-not $found) {
        $result += "${Key}=${Value}"
    }
    $result | Set-Content $Path
}

function Get-EnvFileValue {
    param([string]$Path, [string]$Key)
    $match = Select-String -Path $Path -Pattern "^${Key}=(.*)" | Select-Object -First 1
    if ($match) {
        return $match.Matches.Groups[1].Value.Trim().Trim('"', "'")
    }
    return $null
}

function New-SecureSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''
}

# ── Docker Compose Helpers ───────────────────────────────────────────────────

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
    param(
        [switch]$AutoDetect,
        [Parameter(ValueFromRemainingArguments)]
        [string[]]$Arguments
    )
    $deployDir = Join-Path $script:InstallRoot "deployment"
    $fileArgs = Get-ComposeFileArgs -AutoDetect:$AutoDetect
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Push-Location $deployDir
    try {
        if ($script:ComposeCmdType -eq "plugin") {
            $allArgs = @("compose") + $fileArgs + $Arguments
            & docker @allArgs
        } else {
            $allArgs = $fileArgs + $Arguments
            & docker-compose @allArgs
        }
        return $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prev
    }
}

function Initialize-ComposeCommand {
    Invoke-NativeQuiet { docker compose version }
    if ($LASTEXITCODE -eq 0) {
        $script:ComposeCmdType = "plugin"
        return $true
    }
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $script:ComposeCmdType = "standalone"
        return $true
    }
    $script:ComposeCmdType = $null
    return $false
}

# ── Version Comparison ───────────────────────────────────────────────────────

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

# ── Port Checking ────────────────────────────────────────────────────────────

function Test-PortAvailable {
    param([int]$Port)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        return $false
    } catch {
        return $true
    }
}

function Find-AvailablePort {
    param([int]$StartPort = 3000)
    $port = $StartPort
    while ($port -le 65535) {
        if (Test-PortAvailable $port) { return $port }
        $port++
    }
    return $StartPort
}

# ── Docker Memory Detection ─────────────────────────────────────────────────

function Get-DockerMemoryMB {
    # Try Docker Desktop settings.json
    $settingsPaths = @(
        (Join-Path $env:APPDATA "Docker\settings.json"),
        (Join-Path $env:LOCALAPPDATA "Docker\settings.json")
    )
    foreach ($settingsPath in $settingsPaths) {
        if (Test-Path $settingsPath) {
            try {
                $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
                if ($settings.memoryMiB -and $settings.memoryMiB -gt 0) {
                    return [int]$settings.memoryMiB
                }
            } catch { }
        }
    }

    # Fall back to docker system info
    try {
        $dockerInfo = Invoke-NativeQuiet -PassThru { docker system info }
        $memLine = $dockerInfo | Where-Object { $_ -match "Total Memory" } | Select-Object -First 1
        if ($memLine -match '(\d+\.?\d*)\s*GiB') {
            return [int]([double]$Matches[1] * 1024)
        }
    } catch { }

    return 0
}

# ── Health Check ─────────────────────────────────────────────────────────────

function Test-OnyxHealth {
    param([int]$Port)
    $maxAttempts = 600  # 10 minutes
    $attempt = 1
    Print-Info "Checking Onyx service health..."
    Write-Host "Containers are healthy, waiting for database migrations and service initialization to finish."
    Write-Host ""

    while ($attempt -le $maxAttempts) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$Port" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -in @(200, 301, 302, 303, 307, 308)) {
                return $true
            }
        } catch [System.Net.WebException] {
            # Connection refused or timeout - expected during startup
        } catch { }

        $minutes = [math]::Floor($attempt / 60)
        $seconds = $attempt % 60
        $dots = "." * (($attempt % 3) + 1)
        $padding = " " * (3 - $dots.Length)
        Write-Host -NoNewline "`rChecking Onyx service${dots}${padding} (${minutes}m ${seconds}s elapsed)"

        Start-Sleep -Seconds 1
        $attempt++
    }
    Write-Host ""
    return $false
}

# ── Help ─────────────────────────────────────────────────────────────────────

function Show-OnyxHelp {
    Write-Host "Onyx Installation Script for Windows"
    Write-Host ""
    Write-Host "Usage: .\install.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -IncludeCraft  Enable Onyx Craft (AI-powered web app building)"
    Write-Host "  -Lite          Deploy Onyx Lite (no Vespa, Redis, or model servers)"
    Write-Host "  -Local         Use existing config files instead of downloading from GitHub"
    Write-Host "  -Shutdown      Stop (pause) Onyx containers"
    Write-Host "  -DeleteData    Remove all Onyx data (containers, volumes, and files)"
    Write-Host "  -NoPrompt      Run non-interactively with defaults (for CI/automation)"
    Write-Host "  -DryRun        Show what would be done without making changes"
    Write-Host "  -ShowVerbose   Show detailed output for debugging"
    Write-Host "  -Help          Show this help message"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\install.ps1                    # Install Onyx"
    Write-Host "  .\install.ps1 -Lite              # Install Onyx Lite (minimal deployment)"
    Write-Host "  .\install.ps1 -IncludeCraft      # Install Onyx with Craft enabled"
    Write-Host "  .\install.ps1 -Shutdown          # Pause Onyx services"
    Write-Host "  .\install.ps1 -DeleteData        # Completely remove Onyx and all data"
    Write-Host "  .\install.ps1 -Local             # Re-run using existing config files on disk"
    Write-Host "  .\install.ps1 -NoPrompt          # Non-interactive install with defaults"
}

# ── Shutdown Mode ────────────────────────────────────────────────────────────

function Invoke-OnyxShutdown {
    Write-Host ""
    Write-Host "=== Shutting down Onyx ===" -ForegroundColor Cyan
    Write-Host ""

    $deployDir = Join-Path $script:InstallRoot "deployment"
    if (-not (Test-Path $deployDir)) {
        Print-Warning "Onyx data directory not found. Nothing to shutdown."
        return
    }

    $composePath = Join-Path $deployDir "docker-compose.yml"
    if (-not (Test-Path $composePath)) {
        Print-Warning "docker-compose.yml not found in $deployDir"
        return
    }

    Print-Info "Stopping Onyx containers..."
    if (-not (Initialize-ComposeCommand)) {
        Print-OnyxError "Docker Compose not found. Cannot stop containers."
        exit 1
    }

    $result = Invoke-Compose -AutoDetect stop
    if ($result -eq 0) {
        Print-Success "Onyx containers stopped (paused)"
    } else {
        Print-OnyxError "Failed to stop containers"
        exit 1
    }

    Write-Host ""
    Print-Success "Onyx shutdown complete!"
}

# ── Delete Data Mode ─────────────────────────────────────────────────────────

function Invoke-OnyxDeleteData {
    Write-Host ""
    Write-Host "=== WARNING: This will permanently delete all Onyx data ===" -ForegroundColor Red
    Write-Host ""
    Print-Warning "This action will remove:"
    Write-Host "  - All Onyx containers and volumes"
    Write-Host "  - All downloaded files and configurations"
    Write-Host "  - All user data and documents"
    Write-Host ""

    if (Test-Interactive) {
        $confirm = Read-Host "Are you sure you want to continue? Type 'DELETE' to confirm"
        Write-Host ""
        if ($confirm -ne "DELETE") {
            Print-Info "Operation cancelled."
            return
        }
    } else {
        Print-OnyxError "Cannot confirm destructive operation in non-interactive mode."
        Print-Info "Run interactively or remove the $($script:InstallRoot) directory manually."
        exit 1
    }

    Print-Info "Removing Onyx containers and volumes..."

    $deployDir = Join-Path $script:InstallRoot "deployment"
    if (Test-Path $deployDir) {
        $composePath = Join-Path $deployDir "docker-compose.yml"
        if (Test-Path $composePath) {
            if (Initialize-ComposeCommand) {
                $result = Invoke-Compose -AutoDetect down -v
                if ($result -eq 0) {
                    Print-Success "Onyx containers and volumes removed"
                } else {
                    Print-OnyxError "Failed to remove containers and volumes"
                }
            } else {
                Print-OnyxError "Docker Compose not found. Cannot remove containers."
            }
        }
    }

    Print-Info "Removing data directories..."
    if (Test-Path $script:InstallRoot) {
        Remove-Item -Recurse -Force $script:InstallRoot
        Print-Success "Data directories removed"
    } else {
        Print-Warning "No $($script:InstallRoot) directory found"
    }

    Write-Host ""
    Print-Success "All Onyx data has been permanently deleted!"
}

# ── Admin Elevation ──────────────────────────────────────────────────────────

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedRelaunch {
    if (Test-IsAdmin) { return $false }

    Print-Info "Administrator privileges are required to install Docker Desktop."
    Print-Info "Relaunching as Administrator (you may see a UAC prompt)..."

    $scriptPath = $PSCommandPath
    if (-not $scriptPath) {
        Print-Warning "Cannot determine script path for elevation. Please re-run as Administrator manually."
        return $false
    }

    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$scriptPath`"")
    if ($Shutdown)       { $argList += "-Shutdown" }
    if ($DeleteData)     { $argList += "-DeleteData" }
    if ($IncludeCraft)   { $argList += "-IncludeCraft" }
    if ($Lite)           { $argList += "-Lite" }
    if ($Local)          { $argList += "-Local" }
    if ($NoPrompt)       { $argList += "-NoPrompt" }
    if ($DryRun)         { $argList += "-DryRun" }
    if ($ShowVerbose)    { $argList += "-ShowVerbose" }

    try {
        $proc = Start-Process powershell -ArgumentList $argList -Verb RunAs -Wait -PassThru
        exit $proc.ExitCode
    } catch {
        Print-Warning "UAC elevation was declined or failed."
        return $false
    }
}

# ── Docker Daemon Startup ────────────────────────────────────────────────────

function Wait-ForDockerDaemon {
    param([int]$MaxWait = 60)
    Print-Info "Waiting for Docker daemon to become ready (up to ${MaxWait} seconds)..."
    $waited = 0
    $lastError = ""
    $unchangedErrorCount = 0
    while ($waited -lt $MaxWait) {
        Start-Sleep -Seconds 3
        $waited += 3

        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $dockerOutput = & docker info 2>&1
        $ErrorActionPreference = $prev
        $errRecords = @($dockerOutput | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
        $currentError = ""
        if ($errRecords.Count -gt 0) { $currentError = $errRecords[0].ToString() }

        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Print-Success "Docker daemon is running"
            return $true
        }

        if ($currentError) {
            if ($currentError -eq $lastError) { $unchangedErrorCount++ }
            else { $unchangedErrorCount = 0; $lastError = $currentError }

            if ($unchangedErrorCount -ge 5) {
                Write-Host ""
                Print-OnyxError "Docker daemon is not starting. Persistent error after ${waited}s:"
                Write-Host "    $lastError" -ForegroundColor Red
                return $false
            }
        }

        $dots = "." * (($waited / 3 % 3) + 1)
        $padding = " " * (3 - $dots.Length)
        Write-Host -NoNewline "`rWaiting for Docker daemon${dots}${padding} (${waited}s elapsed)"
    }
    Write-Host ""
    Print-OnyxError "Docker daemon did not respond within ${MaxWait} seconds."
    if ($lastError) {
        Print-Info "Last error: $lastError"
    }
    return $false
}

function Fix-DockerCredStore {
    # Docker Desktop sets credsStore to "desktop" which doesn't work on Server.
    # Switch to no credential store (uses config.json for auth tokens).
    $configDir = Join-Path $env:USERPROFILE ".docker"
    $configFile = Join-Path $configDir "config.json"
    if (-not (Test-Path $configFile)) { return }

    try {
        $config = Get-Content $configFile -Raw | ConvertFrom-Json
        if ($config.credsStore -eq "desktop") {
            Print-Info "Fixing Docker credential store (removing 'desktop' credsStore)..."
            $config.credsStore = ""
            $config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
            Print-Success "Docker credential store fixed"
        }
    } catch {
        Print-Warning "Could not update Docker config: $_"
    }
}

function Start-DockerDaemon {
    Invoke-NativeQuiet { docker info }
    if ($LASTEXITCODE -eq 0) { return $true }

    if ($script:IsWindowsServer) {
        Print-Info "Windows Server detected - starting Docker service..."

        # Check if the docker service exists; if not, register dockerd
        $svc = Get-Service docker -ErrorAction SilentlyContinue
        if (-not $svc) {
            Print-Info "Docker service not registered. Looking for dockerd.exe to register it..."
            $dockerdPath = $null

            # Check common locations for dockerd.exe
            $candidates = @(
                (Join-Path $env:ProgramFiles "Docker\Docker\resources\dockerd.exe"),
                (Join-Path $env:ProgramFiles "Docker\dockerd.exe"),
                (Join-Path $env:ProgramFiles "Docker\Docker\dockerd.exe")
            )
            # Also check next to wherever docker.exe lives
            $dockerExe = Get-Command docker -ErrorAction SilentlyContinue
            if ($dockerExe) {
                $dockerDir = Split-Path $dockerExe.Source
                $candidates = @((Join-Path $dockerDir "dockerd.exe")) + $candidates
            }

            foreach ($candidate in $candidates) {
                if (Test-Path $candidate) {
                    $dockerdPath = $candidate
                    break
                }
            }

            if (-not $dockerdPath) {
                Print-OnyxError "Could not find dockerd.exe to register as a service."
                Print-Info "Searched:"
                foreach ($c in $candidates) { Write-Host "    $c" -ForegroundColor Yellow }
                return $false
            }

            Print-Info "Found dockerd at: $dockerdPath"
            Print-Info "Registering Docker as a Windows service..."
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $dockerdPath --register-service 2>&1 | Out-Null
            $ErrorActionPreference = $prev
            if ($LASTEXITCODE -ne 0) {
                Print-Warning "dockerd --register-service exited with code $LASTEXITCODE"
                Print-Info "Trying alternative registration via sc.exe..."
                $prev2 = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                & sc.exe create docker binPath= "`"$dockerdPath`" --run-service" start= auto 2>&1 | Out-Null
                $ErrorActionPreference = $prev2
            }

            $svc = Get-Service docker -ErrorAction SilentlyContinue
            if (-not $svc) {
                Print-OnyxError "Failed to register Docker as a Windows service."
                return $false
            }
            Print-Success "Docker service registered"
        }

        # Fix credential store if Docker Desktop set it to "desktop" (doesn't work on Server)
        Fix-DockerCredStore

        try {
            Start-Service docker -ErrorAction Stop
            Print-Success "Docker service started"
        } catch {
            Print-Warning "Failed to start Docker service: $_"
            return $false
        }
        return (Wait-ForDockerDaemon -MaxWait 60)
    }

    # Windows Desktop - start Docker Desktop
    Print-Info "Starting Docker Desktop..."

    $dockerDesktopPaths = @(
        "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "${env:LOCALAPPDATA}\Docker\Docker Desktop.exe"
    )

    $launchPath = $null
    foreach ($path in $dockerDesktopPaths) {
        if (Test-Path $path) {
            Print-Info "Found Docker Desktop at: $path"
            Start-Process $path
            $launchPath = $path
            break
        }
    }

    if (-not $launchPath) {
        try {
            Start-Process "Docker Desktop" -ErrorAction Stop
            $launchPath = "(Start Menu shortcut)"
        } catch {
            Print-Warning "Could not find Docker Desktop executable."
            return $false
        }
    }

    if (-not (Wait-ForDockerDaemon -MaxWait 120)) {
        Write-Host ""
        $dockerProc = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
        if ($dockerProc) {
            Print-Info "Docker Desktop process IS running (PID: $($dockerProc.Id)), but the daemon is not responding."
        } else {
            Print-Warning "Docker Desktop process is NOT running - it may have crashed."
        }
        Write-Host ""
        Print-Info "Troubleshooting tips:"
        Write-Host "  1. Try starting Docker Desktop manually from the Start Menu"
        Write-Host "  2. Check if WSL2 is working: run 'wsl --status' in PowerShell"
        Write-Host "  3. Try restarting your computer"
        Write-Host ""
        return $false
    }

    Print-Info "Waiting 15 seconds for Docker Desktop to fully stabilize..."
    Start-Sleep -Seconds 15
    return $true
}

# ── Docker Engine Install (Windows Server) ───────────────────────────────────

function Install-DockerEngine {
    Write-Host ""
    Print-Info "Windows Server detected - installing Docker Engine..."
    Write-Host ""

    if (-not (Test-IsAdmin)) {
        Invoke-ElevatedRelaunch
    }

    # Install the Containers Windows feature if available
    try {
        $feature = Get-WindowsFeature -Name Containers -ErrorAction Stop
        if ($feature.InstallState -ne 'Installed') {
            Print-Info "Installing Windows Containers feature..."
            $result = Install-WindowsFeature -Name Containers -ErrorAction Stop
            if ($result.RestartNeeded -eq 'Yes') {
                Print-Warning "A reboot is required to finish enabling the Containers feature."
                Print-Info "Please restart your computer and re-run this script."
                exit 0
            }
            Print-Success "Containers feature installed"
        } else {
            Print-Success "Containers feature already installed"
        }
    } catch {
        Print-Warning "Could not check/install Containers feature (may not be needed): $_"
    }

    $installed = $false

    # Method 1: OneGet DockerMsftProvider
    if (-not $installed) {
        Print-Info "Attempting to install Docker via DockerMsftProvider..."
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
        } catch {
            Print-Warning "DockerMsftProvider install failed: $_"
        }
    }

    # Method 2: Direct binary download
    if (-not $installed) {
        Print-Info "Attempting to download Docker binaries directly..."
        $dockerZipUrl = "https://download.docker.com/win/static/stable/x86_64/"
        try {
            # Get the latest version from the download page
            $page = Invoke-WebRequest -Uri $dockerZipUrl -UseBasicParsing -ErrorAction Stop
            $latestZip = $page.Links | Where-Object { $_.href -match '^docker-\d+.*\.zip$' } |
                Sort-Object href -Descending | Select-Object -First 1
            if (-not $latestZip) { throw "Could not find Docker zip on download page" }

            $zipUrl = "${dockerZipUrl}$($latestZip.href)"
            $zipPath = Join-Path $env:TEMP "docker-ce.zip"
            Print-Info "Downloading $($latestZip.href)..."
            Download-OnyxFile -Url $zipUrl -Output $zipPath
            Print-Success "Docker binaries downloaded"

            Print-Info "Extracting to $env:ProgramFiles..."
            Expand-Archive -Path $zipPath -DestinationPath $env:ProgramFiles -Force
            Remove-Item -Force $zipPath -ErrorAction SilentlyContinue

            # Add to system PATH
            $dockerPath = Join-Path $env:ProgramFiles "docker"
            $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            if ($machinePath -notlike "*$dockerPath*") {
                [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$dockerPath", "Machine")
            }
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

            # Register as a Windows service
            Print-Info "Registering Docker as a Windows service..."
            & "$dockerPath\dockerd.exe" --register-service
            $installed = $true
            Print-Success "Docker installed and registered as service"
        } catch {
            Print-Warning "Direct binary install failed: $_"
        }
    }

    if (-not $installed) {
        Print-OnyxError "Could not install Docker Engine on Windows Server."
        Write-Host ""
        Print-Info "Please install Docker manually:"
        Write-Host "  https://docs.docker.com/engine/install/binaries/#install-server-and-client-binaries-on-windows" -ForegroundColor Cyan
        exit 1
    }

    # Start Docker service
    Print-Info "Starting Docker service..."
    try {
        Start-Service docker -ErrorAction Stop
        Print-Success "Docker service started"
    } catch {
        Print-Warning "Failed to start Docker service: $_"
        Print-Info "Try running: Start-Service docker"
        exit 1
    }

    # Install Docker Compose CLI plugin
    Install-ComposePlugin

    # Verify
    if (-not (Wait-ForDockerDaemon -MaxWait 30)) {
        Print-OnyxError "Docker was installed but the daemon is not responding."
        exit 1
    }

    Print-Success "Docker Engine installed and running on Windows Server"
}

function Install-ComposePlugin {
    Invoke-NativeQuiet { docker compose version }
    if ($LASTEXITCODE -eq 0) { return }

    Print-Info "Installing Docker Compose plugin..."
    $composePath = Join-Path $env:ProgramFiles "docker\cli-plugins"
    New-Item -ItemType Directory -Force -Path $composePath | Out-Null
    $composeUrl = "https://github.com/docker/compose/releases/latest/download/docker-compose-windows-x86_64.exe"
    $composeDest = Join-Path $composePath "docker-compose.exe"
    try {
        Download-OnyxFile -Url $composeUrl -Output $composeDest
        Print-Success "Docker Compose plugin installed"
    } catch {
        Print-Warning "Failed to install Docker Compose plugin: $_"
        Print-Info "You can install it manually from: https://docs.docker.com/compose/install/"
    }
}

# ── Docker Desktop Install (Windows Desktop) ────────────────────────────────

function Install-Wsl {
    Print-Info "Checking WSL2 prerequisite..."
    Invoke-NativeQuiet { wsl --status }
    if ($LASTEXITCODE -eq 0) {
        Print-Success "WSL2 is available"
        return $true
    }

    Print-Info "WSL2 is not installed. Docker Desktop requires WSL2."
    Print-Info "Installing WSL2 (this may take a few minutes)..."
    try {
        $proc = Start-Process wsl -ArgumentList "--install", "--no-distribution" -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0) {
            Print-Success "WSL2 installed successfully"
            return $true
        }
        Print-Warning "WSL2 install exited with code $($proc.ExitCode). A reboot may be required."
        return $false
    } catch {
        Print-Warning "Failed to install WSL2: $_"
        return $false
    }
}

function Install-DockerDesktop {
    Write-Host ""
    Print-Info "Docker is not installed. Attempting automatic installation..."
    Write-Host ""

    if (-not (Test-IsAdmin)) {
        Invoke-ElevatedRelaunch
    }

    $wslReady = Install-Wsl

    $installed = $false

    if (-not $installed -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Print-Info "Attempting to install Docker Desktop via winget..."
        winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            Print-Success "Docker Desktop installed via winget"
            $installed = $true
        }
    }

    if (-not $installed -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Print-Info "Attempting to install Docker Desktop via Chocolatey..."
        choco install docker-desktop -y
        if ($LASTEXITCODE -eq 0) {
            Print-Success "Docker Desktop installed via Chocolatey"
            $installed = $true
        }
    }

    if (-not $installed) {
        Print-Info "Attempting to download Docker Desktop installer directly..."
        $installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
        $installerPath = Join-Path $env:TEMP "DockerDesktopInstaller_$([System.IO.Path]::GetRandomFileName().Split('.')[0]).exe"
        try {
            Download-OnyxFile -Url $installerUrl -Output $installerPath
            Print-Success "Docker Desktop installer downloaded"
            Print-Info "Running Docker Desktop installer (this may take a few minutes)..."
            $proc = Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -PassThru -NoNewWindow
            if ($proc.ExitCode -eq 0) {
                Print-Success "Docker Desktop installed via direct download"
                $installed = $true
            } elseif ($proc.ExitCode -eq 3) {
                Print-Warning "Docker Desktop installer exited with code 3 (prerequisites not met)."
                if (-not $wslReady) {
                    Print-OnyxError "WSL2 is required but could not be installed."
                    Write-Host "  Please install WSL2 manually: wsl --install --no-distribution" -ForegroundColor Yellow
                    Write-Host "  Then restart your computer and re-run this script." -ForegroundColor Yellow
                } else {
                    Print-Info "A reboot may be needed. Restart your computer and re-run this script."
                }
            } else {
                Print-Warning "Docker Desktop installer exited with code $($proc.ExitCode)."
                if (-not (Test-IsAdmin)) {
                    Print-Info "Try re-running as Administrator (right-click PowerShell -> 'Run as Administrator')."
                }
            }
        } catch {
            Print-Warning "Direct download installation failed: $_"
        } finally {
            Remove-Item -Force $installerPath -ErrorAction SilentlyContinue
        }
    }

    if (-not $installed) {
        Write-Host ""
        Print-OnyxError "Could not install Docker Desktop automatically."
        Write-Host ""
        Write-Host "Please install Docker Desktop manually:" -ForegroundColor Yellow
        Write-Host "  https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Cyan
        exit 1
    }

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Print-OnyxError "Docker was installed but the 'docker' command is not yet available."
        Write-Host "Please restart your terminal and re-run this script."
        exit 1
    }

    if (-not (Start-DockerDaemon)) {
        Print-OnyxError "Docker Desktop was installed but could not be started."
        Write-Host "  Please launch Docker Desktop from the Start Menu and re-run this script." -ForegroundColor Yellow
        exit 1
    }

    Print-Success "Docker Desktop installed and running"
}

# ── Docker Install Router ────────────────────────────────────────────────────

function Install-Docker {
    if ($script:IsWindowsServer) {
        Install-DockerEngine
    } else {
        Install-DockerDesktop
    }
}

# ── Main Installation Flow ───────────────────────────────────────────────────

function Main {
    # Handle help
    if ($Help) {
        Show-OnyxHelp
        return
    }

    # Check PowerShell version
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Print-OnyxError "PowerShell 5+ required (found $($PSVersionTable.PSVersion))"
        exit 1
    }

    # Validate flag combinations
    if ($script:LiteMode -and $script:IncludeCraftMode) {
        Print-OnyxError "-Lite and -IncludeCraft cannot be used together."
        Write-Host "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
        exit 1
    }

    # Adjust resource thresholds for lite mode
    if ($script:LiteMode) {
        $script:ExpectedDockerRamGB = 4
        $script:ExpectedDiskGB = 16
    }

    # Handle shutdown mode
    if ($Shutdown) {
        Invoke-OnyxShutdown
        return
    }

    # Handle delete-data mode
    if ($DeleteData) {
        Invoke-OnyxDeleteData
        return
    }

    # Check/install Docker before the banner
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Install-Docker
    }

    # ── Banner ───────────────────────────────────────────────────────────
    Write-Host ""
    Write-Host "   ____                    " -ForegroundColor Cyan
    Write-Host "  / __ \                   " -ForegroundColor Cyan
    Write-Host " | |  | |_ __  _   ___  __" -ForegroundColor Cyan
    Write-Host " | |  | | '_ \| | | \ \/ /" -ForegroundColor Cyan
    Write-Host " | |__| | | | | |_| |>  < " -ForegroundColor Cyan
    Write-Host "  \____/|_| |_|\__, /_/\_\" -ForegroundColor Cyan
    Write-Host "                __/ |      " -ForegroundColor Cyan
    Write-Host "               |___/       " -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Welcome to Onyx Installation Script (Windows)"
    Write-Host "=============================================="
    Write-Host ""
    $editionLabel = if ($script:IsWindowsServer) { "Windows Server" } else { "Windows Desktop" }
    Write-Host "[OK] $editionLabel detected" -ForegroundColor Green
    Write-Host ""

    # User acknowledgment
    Write-Host "This script will:" -ForegroundColor Yellow
    Write-Host "1. Download deployment files for Onyx into a new '$($script:InstallRoot)' directory"
    Write-Host "2. Check your system resources (Docker, memory, disk space)"
    Write-Host "3. Guide you through deployment options (version, authentication)"
    Write-Host ""

    if (Test-Interactive) {
        Write-Host "Please acknowledge and press Enter to continue..." -ForegroundColor Yellow
        Read-Host | Out-Null
        Write-Host ""
    } else {
        Write-Host "Running in non-interactive mode - proceeding automatically..." -ForegroundColor Yellow
        Write-Host ""
    }

    # Dry-run: show plan and exit
    if ($DryRun) {
        Print-Info "Dry run mode - showing what would happen:"
        Write-Host "  - Install root: $($script:InstallRoot)"
        Write-Host "  - Lite mode: $($script:LiteMode)"
        Write-Host "  - Include Craft: $($script:IncludeCraftMode)"
        Write-Host "  - Verbose: $($ShowVerbose.IsPresent)"
        Write-Host "  - OS: Windows $([System.Environment]::OSVersion.Version)"
        Write-Host "  - PowerShell: $($PSVersionTable.PSVersion)"
        Write-Host ""
        Print-Success "Dry run complete (no changes made)"
        return
    }

    if ($ShowVerbose) {
        Print-Info "Verbose mode enabled - showing detailed output"
    }

    # ── Step 1: Verify Docker Installation ───────────────────────────────
    Print-Step "Verifying Docker installation"

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Install-Docker
    }

    $dockerVersionOutput = Invoke-NativeQuiet -PassThru { docker --version }
    $dockerVersionMatch = [regex]::Match($dockerVersionOutput, '(\d+\.\d+\.\d+)')
    $dockerVersion = if ($dockerVersionMatch.Success) { $dockerVersionMatch.Value } else { "unknown" }
    Print-Success "Docker $dockerVersion is installed"

    # Check Docker Compose
    if (-not (Initialize-ComposeCommand)) {
        if ($script:IsWindowsServer) {
            Print-Info "Docker Compose not found - installing plugin..."
            Install-ComposePlugin
            if (-not (Initialize-ComposeCommand)) {
                Print-OnyxError "Docker Compose could not be installed."
                Write-Host "Visit: https://docs.docker.com/compose/install/"
                exit 1
            }
        } else {
            Print-OnyxError "Docker Compose is not installed."
            Write-Host "Docker Desktop for Windows includes Docker Compose."
            Write-Host "Visit: https://docs.docker.com/desktop/install/windows-install/"
            exit 1
        }
    }

    $composeVersion = "unknown"
    if ($script:ComposeCmdType -eq "plugin") {
        $composeVersionOutput = Invoke-NativeQuiet -PassThru { docker compose version }
        $composeVersionMatch = [regex]::Match(($composeVersionOutput -join ""), '(\d+\.\d+\.\d+)')
        if ($composeVersionMatch.Success) { $composeVersion = $composeVersionMatch.Value }
        Print-Success "Docker Compose $composeVersion is installed (plugin)"
    } else {
        $composeVersionOutput = Invoke-NativeQuiet -PassThru { docker-compose --version }
        $composeVersionMatch = [regex]::Match(($composeVersionOutput -join ""), '(\d+\.\d+\.\d+)')
        if ($composeVersionMatch.Success) { $composeVersion = $composeVersionMatch.Value }
        Print-Success "Docker Compose $composeVersion is installed (standalone)"
    }

    # Check Docker daemon - try to start if it's not running
    Invoke-NativeQuiet { docker info }
    if ($LASTEXITCODE -ne 0) {
        if ($script:IsWindowsServer) {
            Print-Info "Docker daemon is not running. Starting Docker service..."
        } else {
            Print-Info "Docker daemon is not running. Starting Docker Desktop..."
        }
        if (-not (Start-DockerDaemon)) {
            Print-OnyxError "Could not start Docker. Please start it manually and re-run this script."
            exit 1
        }
    }
    Print-Success "Docker daemon is running"

    # ── Step 2: Verify Docker Resources ──────────────────────────────────
    Print-Step "Verifying Docker resources"

    $memoryMB = Get-DockerMemoryMB
    $memoryDisplay = "unknown"
    if ($memoryMB -gt 0) {
        $memoryGB = [math]::Round($memoryMB / 1024, 1)
        if ($memoryGB -ge 1) {
            $memoryDisplay = "~${memoryGB}GB"
        } else {
            $memoryDisplay = "${memoryMB}MB"
        }
        Print-Info "Docker memory allocation: $memoryDisplay"
    } else {
        Print-Warning "Could not determine memory allocation"
    }

    # Check disk space
    $driveName = (Get-Location).Drive.Name
    $drive = Get-PSDrive -Name $driveName
    $diskAvailableGB = [math]::Floor($drive.Free / 1GB)
    Print-Info "Available disk space: ${diskAvailableGB}GB"

    # Resource requirements check
    $resourceWarning = $false
    $expectedRamMB = $script:ExpectedDockerRamGB * 1024

    if ($memoryMB -gt 0 -and $memoryMB -lt $expectedRamMB) {
        Print-Warning "Less than $($script:ExpectedDockerRamGB)GB RAM available (found: $memoryDisplay)"
        $resourceWarning = $true
    }
    if ($diskAvailableGB -lt $script:ExpectedDiskGB) {
        Print-Warning "Less than $($script:ExpectedDiskGB)GB disk space available (found: ${diskAvailableGB}GB)"
        $resourceWarning = $true
    }

    if ($resourceWarning) {
        Write-Host ""
        Print-Warning "Onyx recommends at least $($script:ExpectedDockerRamGB)GB RAM and $($script:ExpectedDiskGB)GB disk space for optimal performance in standard mode."
        Print-Warning "Lite mode requires less resources (1-4GB RAM, 8-16GB disk depending on usage), but does not include a vector database."
        Write-Host ""
        $reply = Prompt-YnOrDefault "Do you want to continue anyway? (Y/n): " "y"
        if ($reply -notmatch '^[Yy]') {
            Print-Info "Installation cancelled. Please allocate more resources and try again."
            exit 1
        }
        Print-Info "Proceeding with installation despite resource limitations..."
    }

    # ── Step 3: Create Directory Structure ───────────────────────────────
    Print-Step "Creating directory structure"

    if (Test-Path $script:InstallRoot) {
        Print-Info "Directory structure already exists"
        Print-Success "Using existing $($script:InstallRoot) directory"
    }

    $deploymentDir = Join-Path $script:InstallRoot "deployment"
    $nginxDir = Join-Path $script:InstallRoot "data\nginx\local"
    New-Item -ItemType Directory -Force -Path $deploymentDir | Out-Null
    New-Item -ItemType Directory -Force -Path $nginxDir | Out-Null
    Print-Success "Directory structure created"

    # ── Step 4: Download Configuration Files ─────────────────────────────
    if ($Local) {
        Print-Step "Verifying existing configuration files"
    } else {
        Print-Step "Downloading Onyx configuration files"
        Print-Info "This step downloads all necessary configuration files from GitHub..."
    }

    $composeDest = Join-Path $deploymentDir "docker-compose.yml"
    if (-not (Ensure-OnyxFile $composeDest "$($script:GitHubRawUrl)/docker-compose.yml" "docker-compose.yml")) {
        exit 1
    }

    # Check Docker Compose version compatibility
    if ($composeVersion -ne "unknown" -and (Compare-SemVer $composeVersion "2.24.0") -lt 0) {
        Print-Warning "Docker Compose version $composeVersion is older than 2.24.0"
        Write-Host ""
        Print-Warning "The docker-compose.yml file uses the newer env_file format that requires Docker Compose 2.24.0 or later."
        Write-Host ""
        Print-Info "To use this configuration, please update Docker Desktop to the latest version."
        Write-Host "  Visit: https://docs.docker.com/desktop/install/windows-install/"
        Write-Host ""
        Print-Warning "The installation will continue, but may fail if Docker Compose cannot parse the file."
        Write-Host ""
        $reply = Prompt-YnOrDefault "Do you want to continue anyway? (Y/n): " "y"
        if ($reply -notmatch '^[Yy]') {
            Print-Info "Installation cancelled. Please upgrade Docker Desktop."
            exit 1
        }
        Print-Info "Proceeding with installation despite Docker Compose version compatibility issues..."
    }

    # Handle lite overlay
    $liteOverlayPath = Join-Path $deploymentDir $script:LiteComposeFile
    if ($script:LiteMode) {
        if (-not (Ensure-OnyxFile $liteOverlayPath "$($script:GitHubRawUrl)/$($script:LiteComposeFile)" $script:LiteComposeFile)) {
            exit 1
        }
    } elseif (Test-Path $liteOverlayPath) {
        $envFilePath = Join-Path $deploymentDir ".env"
        if (Test-Path $envFilePath) {
            Print-Warning "Existing lite overlay found but -Lite was not passed."
            $reply = Prompt-YnOrDefault "Remove lite overlay and switch to standard mode? (y/N): " "n"
            if ($reply -match '^[Yy]') {
                Remove-Item -Force $liteOverlayPath
                Print-Info "Removed lite overlay (switching to standard mode)"
            } else {
                Print-Info "Keeping existing lite overlay. Pass -Lite to keep using lite mode."
                $script:LiteMode = $true
            }
        } else {
            Remove-Item -Force $liteOverlayPath
            Print-Info "Removed previous lite overlay (switching to standard mode)"
        }
    }

    $envTemplateDest = Join-Path $deploymentDir "env.template"
    if (-not (Ensure-OnyxFile $envTemplateDest "$($script:GitHubRawUrl)/env.template" "env.template")) {
        exit 1
    }

    $nginxConfDest = Join-Path $script:InstallRoot "data\nginx\app.conf.template"
    if (-not (Ensure-OnyxFile $nginxConfDest "$($script:NginxBaseUrl)/app.conf.template" "nginx/app.conf.template")) {
        exit 1
    }

    $nginxRunDest = Join-Path $script:InstallRoot "data\nginx\run-nginx.sh"
    if (-not (Ensure-OnyxFile $nginxRunDest "$($script:NginxBaseUrl)/run-nginx.sh" "nginx/run-nginx.sh")) {
        exit 1
    }

    $readmeDest = Join-Path $script:InstallRoot "README.md"
    if (-not (Ensure-OnyxFile $readmeDest "$($script:GitHubRawUrl)/README.md" "README.md")) {
        exit 1
    }

    $gitkeepPath = Join-Path $script:InstallRoot "data\nginx\local\.gitkeep"
    if (-not (Test-Path $gitkeepPath)) {
        New-Item -ItemType File -Force -Path $gitkeepPath | Out-Null
    }
    Print-Success "All configuration files ready"

    # ── Step 5: Set Up Deployment Configs ────────────────────────────────
    Print-Step "Setting up deployment configs"

    $envFile = Join-Path $deploymentDir ".env"

    # Check if services are already running
    if ((Test-Path $composeDest)) {
        if (Initialize-ComposeCommand) {
            $runningContainers = @()
            try {
                $containerIds = Invoke-Compose -AutoDetect ps -q 2>$null
                $runningContainers = @($containerIds | Where-Object { $_ })
            } catch { }

            if ($runningContainers.Count -gt 0) {
                Print-OnyxError "Onyx services are currently running!"
                Write-Host ""
                Print-Info "To make configuration changes, you must first shut down the services."
                Write-Host ""
                Print-Info "Please run the following command to shut down Onyx:"
                Write-Host "   .\install.ps1 -Shutdown" -ForegroundColor White
                Write-Host ""
                Print-Info "Then run this script again to make your changes."
                exit 1
            }
        }
    }

    $version = "latest"

    if (Test-Path $envFile) {
        Print-Info "Existing .env file found. What would you like to do?"
        Write-Host ""
        Write-Host "  - Press Enter to restart with current configuration"
        Write-Host "  - Type 'update' to update to a newer version"
        Write-Host ""
        $reply = Prompt-OrDefault "Choose an option [default: restart]" ""
        Write-Host ""

        if ($reply -eq "update") {
            Print-Info "Update selected. Which tag would you like to deploy?"
            Write-Host ""
            Write-Host "  - Press Enter for latest (recommended)"
            Write-Host "  - Type a specific tag (e.g., v0.1.0)"
            Write-Host ""

            if ($script:IncludeCraftMode) {
                $version = Prompt-OrDefault "Enter tag [default: craft-latest]" "craft-latest"
            } else {
                $version = Prompt-OrDefault "Enter tag [default: latest]" "latest"
            }
            Write-Host ""

            if ($script:IncludeCraftMode -and $version -eq "craft-latest") {
                Print-Info "Selected: craft-latest (Craft enabled)"
            } elseif ($version -eq "latest") {
                Print-Info "Selected: Latest version"
            } else {
                Print-Info "Selected: $version"
            }

            # Reject craft image tags in lite mode
            if ($script:LiteMode -and $version -match '^craft-') {
                Print-OnyxError "Cannot use a craft image tag ($version) with -Lite."
                Print-Info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
                exit 1
            }

            Print-Info "Updating configuration for version $version..."
            Set-EnvFileValue -Path $envFile -Key "IMAGE_TAG" -Value $version
            Print-Success "Updated IMAGE_TAG to $version in .env file"

            if ($version -match '^craft-') {
                Set-EnvFileValue -Path $envFile -Key "ENABLE_CRAFT" -Value "true" -Uncomment
                Print-Success "ENABLE_CRAFT set to true"
            }
            Print-Success "Configuration updated for upgrade"
        } else {
            # Restart with existing config
            $existingTag = Get-EnvFileValue -Path $envFile -Key "IMAGE_TAG"
            if ($script:LiteMode -and $existingTag -match '^craft-') {
                Print-OnyxError "Cannot restart a craft deployment ($existingTag) with -Lite."
                Print-Info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
                exit 1
            }

            Print-Info "Keeping existing configuration..."
            Print-Success "Will restart with current settings"
        }

        # Clear COMPOSE_PROFILES for lite mode
        if ($script:LiteMode) {
            $existingProfiles = Get-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES"
            if ($existingProfiles -and $existingProfiles -match 's3-filestore') {
                Set-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES" -Value ""
                Print-Success "Cleared COMPOSE_PROFILES for lite mode"
            }
        }
    } else {
        Print-Info "No existing .env file found. Setting up new deployment..."
        Write-Host ""

        # Ask for deployment mode unless set via -Lite flag
        if (-not $script:LiteMode) {
            Print-Info "Which deployment mode would you like?"
            Write-Host ""
            Write-Host "  1) Standard  - Full deployment with search, connectors, and RAG"
            Write-Host "  2) Lite      - Minimal deployment (no Vespa, Redis, or model servers)"
            Write-Host "                  LLM chat, tools, file uploads, and Projects still work"
            Write-Host ""
            $modeChoice = Prompt-OrDefault "Choose a mode (1 or 2) [default: 1]" "1"
            Write-Host ""

            if ($modeChoice -eq "2") {
                $script:LiteMode = $true
                Print-Info "Selected: Lite mode"
                if (-not (Ensure-OnyxFile $liteOverlayPath "$($script:GitHubRawUrl)/$($script:LiteComposeFile)" $script:LiteComposeFile)) {
                    exit 1
                }
            } else {
                Print-Info "Selected: Standard mode"
            }
        } else {
            Print-Info "Deployment mode: Lite (set via -Lite flag)"
        }

        # Validate lite + craft combination (could now be set interactively)
        if ($script:LiteMode -and $script:IncludeCraftMode) {
            Print-OnyxError "-IncludeCraft cannot be used with Lite mode."
            Print-Info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
            exit 1
        }

        # Adjust resource expectations for lite mode
        if ($script:LiteMode) {
            $script:ExpectedDockerRamGB = 4
            $script:ExpectedDiskGB = 16
        }

        # Ask for version
        Print-Info "Which tag would you like to deploy?"
        Write-Host ""
        if ($script:IncludeCraftMode) {
            Write-Host "  - Press Enter for craft-latest (recommended for Craft)"
            Write-Host "  - Type a specific tag (e.g., craft-v1.0.0)"
            Write-Host ""
            $version = Prompt-OrDefault "Enter tag [default: craft-latest]" "craft-latest"
        } else {
            Write-Host "  - Press Enter for latest (recommended)"
            Write-Host "  - Type a specific tag (e.g., v0.1.0)"
            Write-Host ""
            $version = Prompt-OrDefault "Enter tag [default: latest]" "latest"
        }
        Write-Host ""

        if ($script:IncludeCraftMode -and $version -eq "craft-latest") {
            Print-Info "Selected: craft-latest (Craft enabled)"
        } elseif ($version -eq "latest") {
            Print-Info "Selected: Latest tag"
        } else {
            Print-Info "Selected: $version"
        }

        # Reject craft tags in lite mode
        if ($script:LiteMode -and $version -match '^craft-') {
            Print-OnyxError "Cannot use a craft image tag ($version) with -Lite."
            Print-Info "Craft requires services (Vespa, Redis, background workers) that lite mode disables."
            exit 1
        }

        # Create .env file from template
        Print-Info "Creating .env file with your selections..."
        Copy-Item -Path $envTemplateDest -Destination $envFile -Force

        Print-Info "Setting IMAGE_TAG to $version..."
        Set-EnvFileValue -Path $envFile -Key "IMAGE_TAG" -Value $version
        Print-Success "IMAGE_TAG set to $version"

        # Clear COMPOSE_PROFILES in lite mode
        if ($script:LiteMode) {
            Set-EnvFileValue -Path $envFile -Key "COMPOSE_PROFILES" -Value ""
            Print-Success "Cleared COMPOSE_PROFILES for lite mode"
        }

        # Configure basic authentication
        Set-EnvFileValue -Path $envFile -Key "AUTH_TYPE" -Value "basic"
        Print-Success "Basic authentication enabled in configuration"

        # Generate a secure USER_AUTH_SECRET
        $userAuthSecret = New-SecureSecret
        Set-EnvFileValue -Path $envFile -Key "USER_AUTH_SECRET" -Value "`"$userAuthSecret`""
        Print-Success "Generated secure USER_AUTH_SECRET"

        # Configure Craft
        if ($script:IncludeCraftMode -or $version -match '^craft-') {
            Set-EnvFileValue -Path $envFile -Key "ENABLE_CRAFT" -Value "true" -Uncomment
            Print-Success "Onyx Craft enabled (ENABLE_CRAFT=true)"
        } else {
            Print-Info "Onyx Craft disabled (use -IncludeCraft to enable)"
        }

        Print-Success ".env file created with your preferences"
        Write-Host ""
        Print-Info "IMPORTANT: The .env file has been configured with your selections."
        Print-Info "You can customize it later for:"
        Write-Host "  - Advanced authentication (OAuth, SAML, etc.)"
        Write-Host "  - AI model configuration"
        Write-Host "  - Domain settings (for production)"
        Write-Host "  - Onyx Craft (set ENABLE_CRAFT=true)"
        Write-Host ""
    }

    # ── Step 6: Check Ports ──────────────────────────────────────────────
    Print-Step "Checking for available ports"

    $availablePort = Find-AvailablePort 3000
    if ($availablePort -ne 3000) {
        Print-Info "Port 3000 is in use, found available port: $availablePort"
    } else {
        Print-Info "Port 3000 is available"
    }

    $env:HOST_PORT = $availablePort
    Print-Success "Using port $availablePort for nginx"

    # Determine if we should force-pull
    $currentImageTag = Get-EnvFileValue -Path $envFile -Key "IMAGE_TAG"
    $useLatest = ($currentImageTag -eq "latest" -or $currentImageTag -match '^craft-')
    if ($useLatest) {
        if ($currentImageTag -match '^craft-') {
            Print-Info "Using craft tag '$currentImageTag' - will force pull and recreate containers"
        } else {
            Print-Info "Using 'latest' tag - will force pull and recreate containers"
        }
    }

    # ── Step 7: Pull Docker Images ───────────────────────────────────────
    Print-Step "Pulling Docker images"
    Print-Info "This may take several minutes depending on your internet connection..."
    Write-Host ""
    Print-Info "Downloading Docker images (this may take a while)..."

    $pullArgs = @("pull")
    if (-not $ShowVerbose) { $pullArgs += "--quiet" }
    $pullResult = Invoke-Compose @pullArgs
    if ($pullResult -ne 0) {
        Print-OnyxError "Failed to download Docker images"
        exit 1
    }
    Print-Success "Docker images downloaded successfully"

    # ── Step 8: Start Services ───────────────────────────────────────────
    Print-Step "Starting Onyx services"
    Print-Info "Launching containers..."
    Write-Host ""

    if ($useLatest) {
        Print-Info "Force pulling latest images and recreating containers..."
        $upResult = Invoke-Compose up -d --pull always --force-recreate
    } else {
        $upResult = Invoke-Compose up -d
    }
    if ($upResult -ne 0) {
        Print-OnyxError "Failed to start Onyx services"
        exit 1
    }

    # ── Step 9: Verify Container Health ──────────────────────────────────
    Print-Step "Verifying container health"
    Print-Info "Waiting for containers to initialize (10 seconds)..."

    # Progress bar
    for ($i = 1; $i -le 10; $i++) {
        $filled = "#" * $i
        $empty = " " * (10 - $i)
        $pct = $i * 10
        Write-Host -NoNewline "`r[$filled$empty] $pct%"
        Start-Sleep -Seconds 1
    }
    Write-Host ""
    Write-Host ""

    # Check for restart loops
    Print-Info "Checking container health status..."
    $restartIssues = $false

    $containerIds = @()
    try {
        $ids = Invoke-Compose ps -q 2>$null
        $containerIds = @($ids | Where-Object { $_ })
    } catch { }

    foreach ($containerId in $containerIds) {
        if ([string]::IsNullOrWhiteSpace($containerId)) { continue }

        $containerName = (& docker inspect --format '{{.Name}}' $containerId 2>$null).TrimStart('/')
        $restartCount = 0
        try { $restartCount = [int](& docker inspect --format '{{.RestartCount}}' $containerId 2>$null) } catch { }
        $status = & docker inspect --format '{{.State.Status}}' $containerId 2>$null

        if ($status -eq "running") {
            if ($restartCount -gt 2) {
                Print-OnyxError "$containerName is in a restart loop (restarted $restartCount times)"
                $restartIssues = $true
            } else {
                Print-Success "$containerName is healthy"
            }
        } elseif ($status -eq "restarting") {
            Print-OnyxError "$containerName is stuck restarting"
            $restartIssues = $true
        } else {
            Print-Warning "$containerName status: $status"
        }
    }

    Write-Host ""

    if ($restartIssues) {
        Print-OnyxError "Some containers are experiencing issues!"
        Write-Host ""
        Print-Info "Please check the logs for more information:"
        $composeLogCmd = if ($script:ComposeCmdType -eq "plugin") { "docker compose" } else { "docker-compose" }
        $fileArgStr = (Get-ComposeFileArgs) -join " "
        Write-Host "  cd `"$(Join-Path $script:InstallRoot 'deployment')`" && $composeLogCmd $fileArgStr logs"
        Write-Host ""
        Print-Info "If the issue persists, please contact: founders@onyx.app"
        Write-Host "Include the output of the logs command in your message."
        exit 1
    }

    # ── Step 10: Installation Complete ───────────────────────────────────
    Print-Step "Installation Complete!"
    Print-Success "All containers are running successfully!"
    Write-Host ""

    $port = if ($env:HOST_PORT) { $env:HOST_PORT } else { 3000 }

    if (Test-OnyxHealth -Port $port) {
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "   Onyx service is ready!                   " -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
    } else {
        Print-Warning "Health check timed out after 10 minutes"
        Print-Info "Containers are running, but the web service may still be initializing (or something went wrong)"
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Yellow
        Write-Host "   Onyx containers are running              " -ForegroundColor Yellow
        Write-Host "============================================" -ForegroundColor Yellow
    }

    Write-Host ""
    Print-Info "Access Onyx at:"
    Write-Host "   http://localhost:$port" -ForegroundColor White
    Write-Host ""
    Print-Info "If authentication is enabled, you can create your admin account here:"
    Write-Host "   - Visit http://localhost:$port/auth/signup to create your admin account"
    Write-Host "   - The first user created will automatically have admin privileges"
    Write-Host ""

    if ($script:LiteMode) {
        Write-Host ""
        Print-Info "Running in Lite mode - the following services are NOT started:"
        Write-Host "  - Vespa (vector database)"
        Write-Host "  - Redis (cache)"
        Write-Host "  - Model servers (embedding/inference)"
        Write-Host "  - Background workers (Celery)"
        Write-Host ""
        Print-Info "Connectors and RAG search are disabled. LLM chat, tools, user file"
        Print-Info "uploads, Projects, Agent knowledge, and code interpreter still work."
    }

    Write-Host ""
    Print-Info "Refer to the README in the $($script:InstallRoot) directory for more information."
    Write-Host ""
    Print-Info "For help or issues, contact: founders@onyx.app"
    Write-Host ""
}

Main
