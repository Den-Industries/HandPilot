<#
  Builds the self-contained Windows bundle: embeddable Python + trimmed libraries + app + HandPilot.exe.
  The result needs no installation and no internet on the target PC.

    powershell -ExecutionPolicy Bypass -File tools\portable\build_portable.ps1 [-Out D:\Projects\HandPilot-portable]

  Needs (on the build machine only): Python 3.12 (same minor as the embeddable one), internet, .NET Framework csc.exe.
#>
param(
    [string]$Out = "D:\Projects\HandPilot-portable",
    [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    [string]$PyEmbedVersion = "3.12.10"
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Split-Path -Parent (Split-Path -Parent $Here)
$Bundle = "$Out\HandPilot"; $RT = "$Bundle\runtime"; $SP = "$RT\Lib\site-packages"
$Tmp = "$Out\build"

Remove-Item -Recurse -Force $Bundle -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $RT, $SP, $Tmp | Out-Null

Write-Host "1/7 embeddable Python $PyEmbedVersion"
$zip = "$Tmp\pyembed-$PyEmbedVersion.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PyEmbedVersion/python-$PyEmbedVersion-embed-amd64.zip" -OutFile $zip -UseBasicParsing
}
Expand-Archive $zip $RT -Force
# Explicit search path: this also makes the interpreter ignore any Python installed on the PC.
[IO.File]::WriteAllText("$RT\python312._pth", "python312.zip`r`n.`r`nLib\site-packages`r`n..\app`r`n")

Write-Host "2/7 libraries (no dependency resolution: MediaPipe would pull ~700 MB of unused jax/scipy/...)"
& $Python -m pip install --no-deps --target $SP --disable-pip-version-check --only-binary=:all: `
    numpy==1.26.4 opencv-python-headless==4.11.0.86 mediapipe==0.10.21 PySide6_Essentials==6.12.0 shiboken6==6.12.0 `
    absl-py attrs flatbuffers protobuf==4.25.9 sounddevice cffi pycparser
if ($LASTEXITCODE) { throw "pip failed" }

Write-Host "3/7 trimming"
& $Python "$Here\prune.py" $RT
# MediaPipe imports matplotlib only for a legacy 3D plot that HandPilot never calls.
New-Item -ItemType Directory -Force "$SP\matplotlib" | Out-Null
Set-Content "$SP\matplotlib\__init__.py" '"""Stub: only needed by MediaPipe legacy 3D plotting."""' -Encoding UTF8
Set-Content "$SP\matplotlib\pyplot.py" "def _na(*a, **k):`n    raise RuntimeError('matplotlib is not bundled')`n`nfigure = subplot = show = plot = _na" -Encoding UTF8
# Visual C++ runtime next to python.exe (a fresh Windows may not have it); taken from the PySide6 wheel.
foreach ($n in 'msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','concrt140.dll','vcruntime140.dll','vcruntime140_1.dll') {
    Copy-Item "$SP\PySide6\$n" "$RT\$n" -Force
}
Remove-Item "$SP\PySide6\msvcp140_codecvt_ids.dll","$SP\shiboken6\msvcp140_codecvt_ids.dll","$SP\shiboken6\vcomp140.dll" -ErrorAction SilentlyContinue

Write-Host "4/7 application"
New-Item -ItemType Directory "$Bundle\app" | Out-Null
Copy-Item "$Src\handpilot" "$Bundle\app\handpilot" -Recurse
Copy-Item "$Src\HandPilot.pyw" "$Bundle\app\HandPilot.pyw"
Get-ChildItem "$Bundle\app" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
foreach ($f in 'fingerspellbackup.py','dump_py.bat','py_dump.txt') { Get-ChildItem "$Bundle\app" -Recurse -Filter $f | Remove-Item -Force }

Write-Host "5/7 launcher"
& C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe /optimize+ /out:"$Bundle\HandPilot.exe" /r:System.Windows.Forms.dll "$Here\Launcher.cs"
if ($LASTEXITCODE) { throw "csc failed" }
[IO.File]::WriteAllText("$Bundle\HandPilot-debug.bat", "@echo off`r`nchcp 65001 >nul`r`nset PYTHONNOUSERSITE=1`r`ncd /d `"%~dp0app`"`r`n`"%~dp0runtime\python.exe`" HandPilot.pyw --debug %*`r`necho.`r`necho Exit code: %errorlevel%`r`npause`r`n", (New-Object Text.UTF8Encoding($false)))
Copy-Item "$Here\portable-readme.txt" "$Bundle\ПРОЧТИ-МЕНЯ.txt"
Copy-Item "$Src\README.md" "$Bundle\README.md"

Write-Host "6/7 smoke test (imports with the bundled interpreter only)"
Push-Location C:\
& "$RT\python.exe" -I -c "import numpy, cv2, mediapipe, PySide6.QtWidgets; from mediapipe.tasks.python import vision; print('imports ok')"
$rc = $LASTEXITCODE; Pop-Location
if ($rc) { throw "smoke test failed" }

Write-Host "7/7 zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$outZip = "$Out\HandPilot-Windows-portable.zip"; Remove-Item $outZip -ErrorAction SilentlyContinue
[IO.Compression.ZipFile]::CreateFromDirectory($Bundle, $outZip, [IO.Compression.CompressionLevel]::Optimal, $true)
"{0}: {1:N0} MB" -f $outZip, ((Get-Item $outZip).Length / 1MB)
