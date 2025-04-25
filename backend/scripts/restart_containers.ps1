# Usage of the script with optional volume arguments
# .\restart_containers.ps1 -VespaVolume <vespa_volume> -PostgresVolume <postgres_volume> -RedisVolume <redis_volume>

param (
    [string]$VespaVolume = "",
    [string]$PostgresVolume = "",
    [string]$RedisVolume = ""
)

# Stop and remove the existing containers
Write-Host "Stopping and removing existing containers..."
docker stop onyx_postgres onyx_vespa onyx_redis | Out-Null
docker rm onyx_postgres onyx_vespa onyx_redis | Out-Null

# Start the PostgreSQL container with optional volume
Write-Host "Starting PostgreSQL container..."
if ($PostgresVolume -ne "") {
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d -v ${PostgresVolume}:/var/lib/postgresql/data postgres -c max_connections=250 | Out-Null
} else {
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d postgres -c max_connections=250 | Out-Null
}

# Start the Vespa container with optional volume
Write-Host "Starting Vespa container..."
if ($VespaVolume -ne "") {
    docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 -v ${VespaVolume}:/opt/vespa/var vespaengine/vespa:8 | Out-Null
} else {
    docker run --detach --name onyx_vespa --hostname vespa-container --publish 8081:8081 --publish 19071:19071 vespaengine/vespa:8 | Out-Null
}

# Start the Redis container with optional volume
Write-Host "Starting Redis container..."
if ($RedisVolume -ne "") {
    docker run --detach --name onyx_redis --publish 6379:6379 -v ${RedisVolume}:/data redis | Out-Null
} else {
    docker run --detach --name onyx_redis --publish 6379:6379 redis | Out-Null
}

# Ensure Alembic runs in the correct directory
$ScriptDir = Split-Path -Parent $PSScriptRoot
#$ParentDir = Split-Path -Parent $ScriptDir
Set-Location -Path $ScriptDir

# Give Postgres a second to start
Start-Sleep -Seconds 1

# Run Alembic upgrade
Write-Host "Running Alembic migration..."
try {
    alembic upgrade head
    # Uncomment the following line if using MT cloud
    # alembic -n schema_private upgrade head
} catch {
    Write-Host "Error running Alembic migration: $_"
}

Write-Host "Containers restarted and migration completed."