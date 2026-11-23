# Test harness for delete-user-data.ps1 (installer_files.rs). Builds app
# folders under $Root, replaces the account and folder lookups, and runs the
# script. The Rust test then checks what is left.
param(
    [Parameter(Mandatory)][string]$Script,
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$Sid,
    [switch]$NoLinks,
    [string]$LinkType = 'Junction'
)
$ErrorActionPreference = 'Stop'
$roaming = Join-Path $Root 'Roaming'
$local = Join-Path $Root 'Local'
$app = 'app.onyx.desktop.v2'
$roamingApp = Join-Path $roaming $app

New-Item -ItemType Directory -Force -Path (Join-Path $roamingApp 'sub\deep') | Out-Null
Set-Content -LiteralPath (Join-Path $roamingApp 'config.json') -Value '{}'
Set-Content -LiteralPath (Join-Path $roamingApp 'sub\deep\file.txt') -Value 'x'
New-Item -ItemType Directory -Force -Path $local | Out-Null
foreach ($target in 'target-inner', 'target-top') {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $target) | Out-Null
    Set-Content -LiteralPath (Join-Path $Root "$target\keep.txt") -Value 'keep'
}
if ($NoLinks) {
    New-Item -ItemType Directory -Force -Path (Join-Path $local "$app\EBWebView") | Out-Null
} else {
    New-Item -ItemType $LinkType -Path (Join-Path $roamingApp 'sub\link') -Target (Join-Path $Root 'target-inner') | Out-Null
    New-Item -ItemType $LinkType -Path (Join-Path $local $app) -Target (Join-Path $Root 'target-top') | Out-Null
}

$account = "`"test\user`",`"$Sid`""
function whoami.exe { $account }
function Get-ItemProperty { [pscustomobject]@{ AppData = $roaming; 'Local AppData' = $local } }

& ([scriptblock]::Create((Get-Content -LiteralPath $Script -Raw)))
