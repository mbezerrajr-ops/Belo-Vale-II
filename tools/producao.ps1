<#
.SYNOPSIS
  Operação do Belo Vale II em produção, neste PC.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\producao.ps1 estado
  powershell -ExecutionPolicy Bypass -File tools\producao.ps1 atualizar
  powershell -ExecutionPolicy Bypass -File tools\producao.ps1 registros api

.DESCRIPTION
  estado     O que está no ar: contêineres, leitores (Ollama e whisper),
             acesso pela internet (Funnel) e último backup.
  subir      Sobe o que estiver parado (sem reconstruir).
  atualizar  Depois de um merge: reconstrói com o código atual, aplica as
             migrações do banco e confere que voltou. Faça um backup antes
             (o comando pergunta).
  registros  Últimas linhas de registro de um serviço (api, worker, web, db).
  parar      Para tudo, sem apagar dados.
  backup     Roda o backup agora.
#>
param(
  [Parameter(Position = 0)][ValidateSet("estado", "subir", "atualizar", "registros", "parar", "backup")]
  [string]$Comando = "estado",
  [Parameter(Position = 1)][string]$Servico = "api"
)

$ErrorActionPreference = "Stop"
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Env = Join-Path $Repo "infra\.env.production"
$Base = @("compose", "-p", "belo-vale", "--env-file", $Env,
  "-f", (Join-Path $Repo "infra\docker-compose.yml"), "-f", (Join-Path $Repo "infra\docker-compose.prod.yml"))

function Compose([string[]]$argumentos) {
  & docker @($Base + $argumentos)
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($argumentos -join ' ') falhou" }
}

function Responde([string]$url) {
  try { return (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { return $false }
}

if (-not (Test-Path $Env)) { throw "Falta $Env. Gere com: python tools\gerar_env_producao.py" }

switch ($Comando) {
  "estado" {
    Compose @("ps", "--format", "table {{.Service}}\t{{.Status}}")
    "App local (127.0.0.1:8090): " + $(if (Responde "http://127.0.0.1:8090/healthz") { "no ar" } else { "FORA DO AR" })
    "Leitor de fotos (Ollama):   " + $(if (Responde "http://127.0.0.1:11434/api/tags") { "no ar" } else { "FORA DO AR" })
    "Transcritor (whisper):      " + $(if (Responde "http://127.0.0.1:8081/") { "no ar" } else { "FORA DO AR" })
    $ts = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $ts) { "Acesso pela internet (Funnel):"; & $ts funnel status } else { "Tailscale não instalado: o app não está na internet." }
    $ultimo = Join-Path $env:USERPROFILE ".belo-vale\ultimo-backup.txt"
    "Último backup: " + $(if (Test-Path $ultimo) { Get-Content $ultimo } else { "nenhum" })
  }
  "subir" { Compose @("up", "-d", "--wait") }
  "atualizar" {
    $r = Read-Host "Rodar o backup antes de atualizar? (S/n)"
    if ($r -ne "n") { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "tools\backup\backup.ps1") }
    Compose @("up", "-d", "--build", "--wait")
    Compose @("exec", "-T", "api", "uv", "run", "--no-sync", "alembic", "upgrade", "head")
    if (-not (Responde "http://127.0.0.1:8090/healthz")) { throw "O app não voltou. Veja: tools\producao.ps1 registros api" }
    "Atualizado e no ar."
  }
  "registros" { Compose @("logs", "--tail", "80", $Servico) }
  "parar" { Compose @("stop") }
  "backup" { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "tools\backup\backup.ps1") }
}
