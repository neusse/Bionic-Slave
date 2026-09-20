<#
.SYNOPSIS
Registers `codex mcp-server` as an MCP server inside Bionic, so a Bionic session
can call Codex as a tool and get results back inline (the Bionic -> Codex direction).

.DESCRIPTION
Bionic keeps its MCP servers in:

    <AppDataRoot>\apps\bionic\.internal\ng-mcp.json

This script appends a single stdio entry:

    {
      "id": "<guid>",
      "name": "codex",
      "enabled": true,
      "connection": {
        "type": "stdio",
        "command": "<absolute path to codex.exe>",
        "args": ["mcp-server"],
        "env": {},
        "cwd": "<project root>"
      }
    }

It is idempotent: if a server named "codex" already exists it reports and exits.

Because Bionic owns ng-mcp.json while it runs, the script refuses to write while
Bionic is open. Close Bionic first, or pass -KeepAppRunning to write anyway
(Bionic may overwrite the change).

.PARAMETER AppDataRoot
Bionic app data folder containing apps\bionic. Defaults to $env:BIONIC_APP_DATA,
then $env:LMSTUDIO_HOME, then %USERPROFILE%\.lmstudio.

.PARAMETER ConfigPath
Full path to ng-mcp.json. Overrides -AppDataRoot.

.PARAMETER KeepAppRunning
Write even though Bionic is running.

.PARAMETER Disabled
Add the entry disabled instead of enabled.

.EXAMPLE
pwsh -File bridge\install_codex_mcp_bionic.ps1 -WhatIf
#>
#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AppDataRoot,
    [string]$ConfigPath,
    [switch]$KeepAppRunning,
    [switch]$Disabled
)

$ErrorActionPreference = 'Stop'

function Write-Section { param([string]$T) Write-Host ""; Write-Host "== $T" -ForegroundColor Cyan }
function Write-Ok { param([string]$T) Write-Host "   [ok] $T" -ForegroundColor Green }
function Write-Note { param([string]$T) Write-Host "   [!!] $T" -ForegroundColor Yellow }
function Write-Fail { param([string]$T) Write-Host "   [xx] $T" -ForegroundColor Red }

if (-not $ConfigPath) {
    if (-not $AppDataRoot) {
        $AppDataRoot = $env:BIONIC_APP_DATA
        if (-not $AppDataRoot) { $AppDataRoot = $env:LMSTUDIO_HOME }
        if (-not $AppDataRoot) { $AppDataRoot = Join-Path $env:USERPROFILE '.lmstudio' }
    }
    $ConfigPath = Join-Path $AppDataRoot 'apps\bionic\.internal\ng-mcp.json'
}

Write-Section "Bionic MCP config"
Write-Host "   $ConfigPath"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Fail "ng-mcp.json not found. Is Bionic installed?"
    exit 1
}

$raw = Get-Content -LiteralPath $ConfigPath -Raw
$config = $raw | ConvertFrom-Json
$servers = @($config.servers)

$existing = $servers | Where-Object { $_.name -eq 'codex' }
if ($existing) {
    Write-Ok "A server named 'codex' already exists (id $($existing[0].id)). Nothing to do."
    exit 0
}

$codex = (Get-Command codex -ErrorAction SilentlyContinue).Source
if (-not $codex) {
    $codex = Join-Path $env:USERPROFILE 'AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
}
if (-not (Test-Path -LiteralPath $codex)) {
    Write-Fail "codex.exe not found. Install Codex CLI first."
    exit 1
}
Write-Ok "codex.exe -> $codex"

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$entry = [ordered]@{
    id      = [guid]::NewGuid().ToString()
    name    = 'codex'
    enabled = -not $Disabled
    connection = [ordered]@{
        type    = 'stdio'
        command = $codex
        args    = @('mcp-server')
        env     = [ordered]@{}
        cwd     = $projectRoot
    }
}

$isRunning = $false
$proc = Get-Process -Name 'Bionic' -ErrorAction SilentlyContinue
if ($proc) { $isRunning = $true }

if ($isRunning -and -not $KeepAppRunning) {
    Write-Note "Bionic appears to be running. It owns ng-mcp.json and may overwrite this change."
    Write-Note "Close Bionic and re-run, or pass -KeepAppRunning to write anyway."
    exit 2
}

$newServers = @($servers) + $entry
$newConfig = [ordered]@{ servers = $newServers }

$backup = "$ConfigPath.bak"
Copy-Item -LiteralPath $ConfigPath -Destination $backup -Force
Write-Ok "Backed up to $backup"

$json = $newConfig | ConvertTo-Json -Depth 12
if ($PSCmdlet.ShouldProcess($ConfigPath, "write codex MCP server entry")) {
    Set-Content -LiteralPath $ConfigPath -Value $json -Encoding UTF8
}
Write-Ok "Registered 'codex' MCP server in Bionic."
Write-Host ""
Write-Host "Restart Bionic, then in any session you can ask it to use the Codex MCP tools." -ForegroundColor Yellow
