[CmdletBinding()]
param(
    [ValidateSet("up", "down", "restart", "logs", "ps", "build", "config")]
    [string]$Accion = "up",

    [switch]$ConS3,

    [switch]$SinBuild,

    [switch]$SinWait,

    [switch]$SoloBase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ComposeCli {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            & docker compose version 1> $null 2> $null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    Exe = "docker"
                    Prefix = @("compose")
                    SoportaWait = $true
                }
            }
        }
        catch {
        }
    }

    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        return @{
            Exe = "docker-compose"
            Prefix = @()
            SoportaWait = $false
        }
    }

    throw "No se encontró Docker Compose. Instalá Docker Desktop o el plugin 'docker compose'."
}

function Test-DockerDaemon {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "No se encontró el comando 'docker'."
    }

    & docker info 1> $null 2> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker está instalado pero no responde. Abrí Docker Desktop y probá de nuevo."
    }
}

function Invoke-Compose {
    param(
        [hashtable]$Cli,
        [string[]]$BaseArgs,
        [string[]]$ActionArgs
    )

    & $Cli.Exe @($Cli.Prefix + $BaseArgs + $ActionArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose devolvió código $LASTEXITCODE."
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeDir = Join-Path $scriptDir "deployment/docker_compose"

if (-not (Test-Path $composeDir)) {
    throw "No se encontró la carpeta de compose: $composeDir"
}

$cli = Get-ComposeCli
if ($Accion -ne "config") {
    Test-DockerDaemon
}

$baseArgs = @("-f", "docker-compose.yml")
if (-not $SoloBase) {
    $baseArgs += @("-f", "docker-compose.dev.yml")
}

if ($ConS3) {
    $env:COMPOSE_PROFILES = "s3-filestore"
    $env:FILE_STORE_BACKEND = "s3"
    Write-Host "Modo de archivos: S3/MinIO (profile 's3-filestore')." -ForegroundColor Cyan
}
else {
    $env:COMPOSE_PROFILES = ""
    $env:FILE_STORE_BACKEND = "postgres"
    Write-Host "Modo de archivos: PostgreSQL (sin MinIO, más simple para arrancar)." -ForegroundColor Cyan
}

# Facilita login local sin configuración extra, salvo que el usuario lo sobreescriba manualmente.
if (-not $env:AUTH_TYPE) {
    $env:AUTH_TYPE = "disabled"
}

Push-Location $composeDir
try {
    switch ($Accion) {
        "up" {
            $args = @("up", "-d", "--remove-orphans")
            if (-not $SinBuild) {
                $args += "--build"
            }
            if (-not $SinWait -and $cli.SoportaWait) {
                $args += "--wait"
            }

            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs $args

            Write-Host "Servicios de Hop iniciados." -ForegroundColor Green
            Write-Host "URL principal: http://localhost:3000" -ForegroundColor Green
            Write-Host "API directa (si usás docker-compose.dev.yml): http://localhost:8080" -ForegroundColor Green
        }

        "down" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("down", "--remove-orphans")
            Write-Host "Servicios detenidos." -ForegroundColor Yellow
        }

        "restart" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("down", "--remove-orphans")

            $upArgs = @("up", "-d", "--remove-orphans")
            if (-not $SinBuild) {
                $upArgs += "--build"
            }
            if (-not $SinWait -and $cli.SoportaWait) {
                $upArgs += "--wait"
            }
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs $upArgs

            Write-Host "Servicios reiniciados." -ForegroundColor Green
        }

        "logs" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("logs", "-f", "--tail", "200")
        }

        "ps" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("ps")
        }

        "build" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("build", "--no-cache")
            Write-Host "Build completado." -ForegroundColor Green
        }

        "config" {
            Invoke-Compose -Cli $cli -BaseArgs $baseArgs -ActionArgs @("config")
        }
    }
}
finally {
    Pop-Location
}
