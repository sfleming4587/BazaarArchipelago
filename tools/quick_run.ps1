# Solo test game: generates a seed, starts a local Archipelago server and opens The Bazaar Client.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File tools\quick_run.ps1
param(
    [string]$Name = "Sulldog",
    [string]$StartingHero = "any",   # any, vanessa, pygmalien, dooley, mak, stelle, jules, karnok, the_dragons
    [int]$Port = 38281
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$ap = Join-Path $root "Archipelago"
$python = Join-Path $root ".venv\Scripts\python.exe"
$work = Join-Path $root ".quickrun"
$players = Join-Path $work "players"
$output = Join-Path $work "output"

Remove-Item -Recurse -Force $output -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $players, $output | Out-Null

@"
name: $Name
game: The Bazaar
The Bazaar:
  owned_dlc_heroes: ["Mak", "Stelle", "Jules", "Karnok", "The Dragons"]
  starting_hero: $StartingHero
  heroes_required: 1
  max_day: 15
  legacy_card_packs: true
  death_link: false
"@ | Set-Content -Encoding utf8 (Join-Path $players "$Name.yaml")

Push-Location $ap
try {
    & $python Generate.py --player_files_path $players --outputpath $output --spoiler 2 | Out-Null
    $zip = Get-ChildItem $output -Filter "AP_*.zip" | Select-Object -First 1
    if (-not $zip) { throw "Generation failed - run Generate.py by hand to see the error." }
    Expand-Archive $zip.FullName -DestinationPath $output -Force
    $spoiler = Get-ChildItem $output -Filter "*_Spoiler.txt" | Select-Object -First 1
    $start = (Get-Content $spoiler.FullName | Select-String -Pattern "^Hero: " | Select-Object -First 1).Line
    Write-Host "Starting hero -> $start" -ForegroundColor Green

    Start-Process $python -ArgumentList "MultiServer.py", "`"$($zip.FullName)`"", "--port", $Port -WorkingDirectory $ap
    Start-Sleep -Seconds 5
    Start-Process $python -ArgumentList "Launcher.py", "`"The Bazaar Client`"", "--", "--connect", "localhost:$Port", "--name", $Name -WorkingDirectory $ap
    Write-Host "Server and client are starting. Spoiler log: $($spoiler.FullName)"
} finally {
    Pop-Location
}
