$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$studyFolder = Join-Path (Get-Location) 'research/audio-study-01'
$studyVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $studyVoice.SelectVoice('Microsoft Huihui Desktop')
    $studyVoice.Rate = 0
    $studyVoice.Volume = 100
    foreach ($studyName in @('continuous','suspended','phrased')) {
        $studyInput = Join-Path $studyFolder ($studyName + '.ssml')
        $studyOutput = Join-Path $studyFolder ($studyName + '.wav')
        $studySsml = [System.IO.File]::ReadAllText($studyInput,[System.Text.Encoding]::UTF8)
        $studyVoice.SetOutputToWaveFile($studyOutput)
        $studyVoice.SpeakSsml($studySsml)
        $studyVoice.SetOutputToNull()
        [PSCustomObject]@{File=($studyName+'.wav');Bytes=(Get-Item -LiteralPath $studyOutput).Length;Voice=$studyVoice.Voice.Name}
    }
} finally {
    $studyVoice.Dispose()
}
