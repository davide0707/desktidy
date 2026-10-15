# The Windows build of DeskTidy: a zip with desktidy.exe and desktidyw.exe that needs no Python on the PC.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Output in dist\: DeskTidy-<version>-windows.zip, its .sha256, and the winget manifests filled in (dist\winget\).
# The user extracts the zip anywhere and runs desktidy.exe install: the program copies itself to
# %LOCALAPPDATA%\Programs\DeskTidy (no admin rights) and registers the command, the start at sign-in and the menu.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..")).Path
$venv = Join-Path $root "build\winvenv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) { python -m venv $venv }
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet "$root[ai]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
$version = (& $python -c "import desktidy; print(desktidy.__version__)").Trim()

$dist = Join-Path $root "dist"
$out = Join-Path $dist "windows"
& $python -m PyInstaller --noconfirm --clean --distpath $out --workpath (Join-Path $root "build\pyinstaller") `
    (Join-Path $here "desktidy.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# smoke test: the commands start without Python (an empty data folder, nothing of the real user is touched)
$env:DESKTIDY_HOME = Join-Path $root "build\smoke-home"
$printed = & (Join-Path $out "DeskTidy\desktidy.exe") --version
if ($LASTEXITCODE -ne 0 -or $printed -notmatch [regex]::Escape($version)) { throw "desktidy.exe --version: $printed" }
Remove-Item Env:DESKTIDY_HOME
# the version resource (file Properties, Task Manager, code signing): product name and version on both exes
foreach ($exe in "desktidy.exe", "desktidyw.exe") {
    $info = (Get-Item (Join-Path $out "DeskTidy\$exe")).VersionInfo
    if ($info.ProductName -ne "DeskTidy" -or $info.ProductVersion -ne $version) {
        throw "$exe version resource: '$($info.ProductName)' '$($info.ProductVersion)'"
    }
}

$zip = Join-Path $dist "DeskTidy-$version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $out "DeskTidy") -DestinationPath $zip
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash
Set-Content -Path "$zip.sha256" -Value "$sha  DeskTidy-$version-windows.zip" -Encoding ascii

# winget manifests with this version, address and hash (submitted by hand to microsoft/winget-pkgs)
$url = "https://github.com/davide0707/desktidy/releases/download/v$version/DeskTidy-$version-windows.zip"
$manifests = Join-Path $dist "winget\$version"
New-Item -ItemType Directory -Force -Path $manifests | Out-Null
Get-ChildItem (Join-Path $here "winget") -Filter *.yaml | ForEach-Object {
    $text = (Get-Content $_.FullName -Raw).Replace("{VERSION}", $version).Replace("{URL}", $url).Replace("{SHA256}", $sha)
    [System.IO.File]::WriteAllText((Join-Path $manifests $_.Name), $text, (New-Object System.Text.UTF8Encoding $false))
}
Write-Host "Built $zip"
Write-Host "SHA256 $sha"
