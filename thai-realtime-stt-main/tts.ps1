param([string]$Text, [string]$Out)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($task, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($task))
    $t.Wait(-1) | Out-Null
    $t.Result
}

[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage, ContentType=WindowsRuntime] | Out-Null

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
         Where-Object { $_.Language -eq 'th-TH' } | Select-Object -First 1
if (-not $voice) { throw "no th-TH voice" }
$synth.Voice = $voice

$stream = Await ($synth.SynthesizeTextToStreamAsync($Text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$size = $stream.Size
$reader = New-Object Windows.Storage.Streams.DataReader($stream)
Await ($reader.LoadAsync($size)) ([uint32]) | Out-Null
$bytes = New-Object byte[] $size
$reader.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($Out, $bytes)
"wrote $Out ($size bytes) voice=$($voice.DisplayName)"
