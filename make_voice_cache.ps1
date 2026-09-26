param([Parameter(Mandatory=$true)][string]$OutputDir)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$nouns = [ordered]@{ person = 'Pedestrian'; bicycle = 'Bicycle'; car = 'Car'; vehicle = 'Vehicle'; obstacle = 'Obstacle' }
$locations = [ordered]@{ left = 'left'; right = 'right'; center = 'ahead' }
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SelectVoice('Microsoft Zira Desktop')
$speaker.Rate = 5
foreach ($noun in $nouns.Values) {
    foreach ($location in $locations.Values) {
        $message = "Stop. $noun $location."
        $slug = $message.ToLowerInvariant().Replace(' ', '_').Replace('.', '')
        $path = Join-Path $OutputDir "$slug.wav"
        if ((Test-Path $path) -and (Get-Item $path).Length -gt 1000) { continue }
        $speaker.SetOutputToWaveFile($path)
        $speaker.Speak($message)
        $speaker.SetOutputToNull()
    }
}
$speaker.Dispose()
