<#
.SYNOPSIS
  One-command demo of prodpath on a fixture monorepo (or your own repo).

.EXAMPLE
  .\scripts\demo.ps1                       # mixed monorepo fixture, no LLM
  .\scripts\demo.ps1 -Summarize -Open      # with local-LLM summaries, open the results
  .\scripts\demo.ps1 -Repo C:\code\myrepo  # your own repo (outputs go to <repo>\.prodpath)
#>
param(
    [string]$Repo,
    [string]$Fixture = "mono_d",
    [string]$Region = "ap-south-1",
    [string]$Usage,
    [switch]$Summarize,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Prodpath {
    & uv run --project $root prodpath @args
    if ($LASTEXITCODE -ne 0) { throw "prodpath $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

if ($Repo) {
    $target = (Resolve-Path $Repo).Path
    Write-Host "Using your repo: $target (only .prodpath\ will be written)" -ForegroundColor Cyan
} else {
    $source = Join-Path $root "tests\fixtures\$Fixture"
    if (-not (Test-Path $source)) { throw "Fixture not found: $source" }
    $target = Join-Path $env:TEMP "prodpath-demo-$Fixture"
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item $source $target -Recurse
    Write-Host "Copied fixture $Fixture to $target (your working tree stays clean)" -ForegroundColor Cyan
}

Write-Host "`n== doctor ==" -ForegroundColor Yellow
& uv run --project $root prodpath doctor   # warnings are fine; a failed model check only matters for -Summarize

Write-Host "`n== scan: which services were found, and why ==" -ForegroundColor Yellow
Invoke-Prodpath scan --path $target

Write-Host "`n== run: plan + Terraform + forecast ==" -ForegroundColor Yellow
$runArgs = @("run", "--path", $target, "--region", $Region)
if ($Summarize) { $runArgs += "--summarize" }
if ($Usage) { $runArgs += @("--usage", $Usage) }
Invoke-Prodpath @runArgs

$out = Join-Path $target ".prodpath\out"
Write-Host "`nDone. Outputs:" -ForegroundColor Green
Get-ChildItem $out | ForEach-Object { Write-Host "  $($_.FullName)" }
Write-Host "Next: open PLAN.md and FORECAST.md, then see docs\DEMO.md for what to look at." -ForegroundColor Green

if ($Open) {
    Invoke-Item (Join-Path $out "PLAN.md")
    Invoke-Item (Join-Path $out "FORECAST.md")
}
