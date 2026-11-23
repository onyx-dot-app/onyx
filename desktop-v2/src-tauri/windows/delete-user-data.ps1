# Run by the MSI as LocalSystem on "msiexec /x ... DELETEAPPDATA=1". The MSI
# embeds this script with -EncodedCommand (installer-guards.wxs); the
# installer_files test fails when the two differ.
$ErrorActionPreference = 'SilentlyContinue'
$app = 'app.onyx.desktop.v2'
foreach ($user in Get-CimInstance -ClassName Win32_UserProfile) {
    if ($user.Special -or -not $user.LocalPath) { continue }
    foreach ($dir in 'AppData\Roaming', 'AppData\Local') {
        Remove-Item -LiteralPath (Join-Path $user.LocalPath "$dir\$app") -Recurse -Force
    }
}
