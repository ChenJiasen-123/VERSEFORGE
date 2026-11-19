param([Parameter(Mandatory=$true)][string]$Folder)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskFolder = (Resolve-Path -LiteralPath $Folder).Path
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speaker.SelectVoice('Microsoft Huihui Desktop')
    $speaker.Rate = 0
    $speaker.Volume = 100
    foreach ($taskName in @('flow', 'line_pause')) {
        $taskXml = [System.IO.File]::ReadAllText((Join-Path $taskFolder ($taskName + '.ssml')))
        $speaker.SetOutputToWaveFile((Join-Path $taskFolder ($taskName + '.wav')))
        $speaker.SpeakSsml($taskXml)
        $speaker.SetOutputToNull()
    }
} finally { $speaker.Dispose() }
