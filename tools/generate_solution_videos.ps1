param(
    [Parameter(Mandatory = $true)]
    [string]$Ffmpeg
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $projectRoot "static\videos"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

# Every source frame was generated specifically for VTIC. Reference/vendor
# footage is not used in these website videos.
$videoSpecs = @(
    @{ Name = "physical-security"; Image = "physical-security-ai.png"; PanX = 22; PanY = 8 },
    @{ Name = "information-security"; Image = "information-security-ai.png"; PanX = -18; PanY = 10 },
    @{ Name = "wireless-connectivity"; Image = "wireless-connectivity-ai.png"; PanX = 20; PanY = -8 },
    @{ Name = "communication"; Image = "communication-ai.png"; PanX = -20; PanY = 8 },
    @{ Name = "technology-backbone"; Image = "technology-backbone-ai.png"; PanX = 18; PanY = 6 },
    @{ Name = "cloud-computing"; Image = "cloud-computing-ai.png"; PanX = -16; PanY = -8 }
)

foreach ($spec in $videoSpecs) {
    $imagePath = Join-Path $projectRoot ("static\images\solutions\" + $spec.Image)
    $outputPath = Join-Path $outputDir ($spec.Name + ".mp4")
    if (-not (Test-Path -LiteralPath $imagePath)) { throw "Missing AI source image: $imagePath" }

    $filter = "scale=1540:866:force_original_aspect_ratio=increase,crop=1540:866,zoompan=z='1.025+0.045*(0.5-0.5*cos(2*PI*on/360))':x='iw/2-(iw/zoom/2)+$($spec.PanX)*sin(2*PI*on/360)':y='ih/2-(ih/zoom/2)+$($spec.PanY)*sin(2*PI*on/360)':d=360:s=1280x720:fps=30,eq=contrast=1.06:saturation=1.06:brightness=-0.025,format=yuv420p"
    & $Ffmpeg -y -loop 1 -i $imagePath -vf $filter -t 12 -an -c:v libx264 -preset medium -crf 24 -movflags +faststart $outputPath
    if ($LASTEXITCODE -ne 0) { throw "$($spec.Name) video generation failed." }
}

Get-ChildItem -LiteralPath $outputDir -Filter "*.mp4" | Select-Object Name, Length
