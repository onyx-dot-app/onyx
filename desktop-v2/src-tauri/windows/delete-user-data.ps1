# Run by the MSI on "msiexec /x ... DELETEAPPDATA=1", as the user who runs
# msiexec. The MSI embeds this script with -EncodedCommand
# (installer-guards.wxs); the installer_files test fails when the two differ.
# Windows PowerShell 5.1 "Remove-Item -Recurse" follows junctions, so this
# script never uses it and never goes into a junction or symbolic link.
$ErrorActionPreference = 'SilentlyContinue'

# Only a real user account: not LocalSystem (SCCM, Intune) or a service.
$sid = whoami.exe /user /fo csv /nh
if ($sid -notmatch '"S-1-(5-21|12-1)-[0-9-]+"\s*$') { exit 0 }

$app = 'app.onyx.desktop.v2'
$reparsePoint = 1024

function Remove-OnyxTree([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($null -eq $item) { return }
    if ($item.Attributes -band $reparsePoint) { return }
    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $Path -Force) {
            # A link inside the folder stays, and so does its target.
            if (-not ($child.Attributes -band $reparsePoint)) {
                Remove-OnyxTree $child.FullName
            }
        }
        # Without -Recurse, and only when empty.
        if ($null -eq (Get-ChildItem -LiteralPath $Path -Force)) {
            Remove-Item -LiteralPath $Path -Force
        }
    } else {
        Remove-Item -LiteralPath $Path -Force
    }
}

# This user's folders. The process environment can be the installer
# service's, so read them from the user's own registry.
$folders = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
foreach ($root in $folders.AppData, $folders.'Local AppData') {
    if (-not $root) { continue }
    $path = Join-Path $root $app
    $item = Get-Item -LiteralPath $path -Force
    if ($null -eq $item) { continue }
    if ($item.Attributes -band $reparsePoint) {
        # Removes the link only. rmdir without /s never deletes contents.
        cmd.exe /d /s /c "rmdir `"$path`""
    } else {
        Remove-OnyxTree $path
    }
}
