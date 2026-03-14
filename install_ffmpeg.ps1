$dest = "$env:USERPROFILE\Downloads\ffmpeg.zip"
$extractPath = "$env:USERPROFILE\ffmpeg"

# Remove corrupt partial download
if (Test-Path $dest) { Remove-Item $dest -Force }
if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }

Write-Host "Downloading FFmpeg using curl..."
curl.exe -L -o $dest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" --retry 3 --retry-delay 5

$size = (Get-Item $dest).Length
Write-Host "Downloaded: $([math]::Round($size/1MB, 1)) MB"

if ($size -lt 10000000) {
    Write-Host "ERROR: Download too small, likely failed."
    exit 1
}

Write-Host "Extracting..."
Expand-Archive -Path $dest -DestinationPath $extractPath -Force

$ffmpegExe = Get-ChildItem $extractPath -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    Write-Host "ERROR: ffmpeg.exe not found after extraction"
    exit 1
}

$ffmpegDir = $ffmpegExe.DirectoryName
Write-Host "FFmpeg at: $ffmpegDir"

$currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
[System.Environment]::SetEnvironmentVariable("PATH", $currentPath + ";" + $ffmpegDir, "User")
$env:PATH += ";$ffmpegDir"

Write-Host "PATH updated permanently."
ffmpeg -version | Select-Object -First 1
Write-Host "SUCCESS: FFmpeg is ready."
