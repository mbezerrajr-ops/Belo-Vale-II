<#
.SYNOPSIS
  Testes das regras do backup (regras.ps1): sem Docker e sem tocar em nada.

.DESCRIPTION
  O backup de 24/09/2026 dizia "concluído" com a cópia da "nuvem" gravada
  numa pasta do OneDrive que nenhuma conta sincronizava: nada saía do PC.
  Estes casos travam as regras que impedem isso de novo.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\backup\testar-regras.ps1
  pwsh -NoProfile -File tools/backup/testar-regras.ps1
#>
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "regras.ps1")

$falhas = 0

function Caso([string]$nome, [scriptblock]$corpo) {
  try {
    & $corpo
    Write-Host "ok      $nome"
  } catch {
    $script:falhas++
    Write-Host "FALHOU  $nome`n        $($_.Exception.Message)"
  }
}

function Igual($obtido, $esperado) {
  if (-not ($obtido -ceq $esperado)) { throw "esperado [$esperado], obtido [$obtido]" }
}

# O motivo vai para o registro: precisa dizer qual pasta ficou no PC.
function Motivo($obtido, [string]$pasta) {
  if (-not ($obtido -is [string] -and $obtido.Contains($pasta))) {
    throw "esperado um motivo citando [$pasta], obtido [$obtido]"
  }
}

$conta = "C:\Users\caiol\OneDrive"

# --- Nuvem: só sai do PC o que está dentro da pasta de uma conta conectada.

Caso "nuvem: pasta dentro de uma conta conectada sai do PC" {
  Igual (MotivoNuvemNoPc "C:\Users\caiol\OneDrive\BeloVale-backup" @($conta)) $null
}

Caso "nuvem: sem conta conectada, a cópia fica no PC" {
  Motivo (MotivoNuvemNoPc "C:\Users\caiol\OneDrive\BeloVale-backup" @()) "C:\Users\caiol\OneDrive\BeloVale-backup"
}

Caso "nuvem: pasta de nome parecido não é a pasta da conta" {
  Motivo (MotivoNuvemNoPc "C:\Users\caiol\OneDrive2\BeloVale-backup" @($conta)) "C:\Users\caiol\OneDrive2\BeloVale-backup"
}

Caso "nuvem: maiúsculas, barra final e barra normal não importam" {
  Igual (MotivoNuvemNoPc "c:/users/CAIOL/onedrive/BeloVale-backup" @("C:\Users\caiol\OneDrive\")) $null
}

Caso "nuvem: vale qualquer conta conectada, não só a primeira" {
  Igual (MotivoNuvemNoPc "D:\OneDrive - Fazenda\BeloVale-backup" @($conta, "D:\OneDrive - Fazenda")) $null
}

# --- HD: pasta no disco do sistema não é HD externo.

Caso "hd: outro disco sai do PC" {
  Igual (MotivoHdNoPc "E:\BeloVale-backup" "C:") $null
}

Caso "hd: pasta no disco do sistema fica no PC" {
  Motivo (MotivoHdNoPc "c:\BeloVale-backup" "C:") "c:\BeloVale-backup"
}

Caso "hd: pasta de rede sai do PC" {
  Igual (MotivoHdNoPc "\\nas\BeloVale-backup" "C:") $null
}

# --- Registro: a última tentativa falhou?

$inicio23 = "2026-09-23 03:30:01  Início do backup belo-vale-2026-09-23_0330"
$ok23 = "2026-09-23 03:31:10  Backup concluído: belo-vale-2026-09-23_0330 (80,1 MB), 1 destino(s)."
$inicio24 = "2026-09-24 03:30:01  Início do backup belo-vale-2026-09-24_0330"
$aviso24 = "2026-09-24 03:31:11  AVISO: HD externo não encontrado (). Conecte o HD para a cópia local."
$falha24 = "2026-09-24 03:31:12  FALHOU: nenhuma cópia saiu deste PC"

Caso "registro: a última tentativa falhou" {
  Igual (UltimaFalhaDoBackup @($inicio23, $ok23, $inicio24, $aviso24, $falha24)) $falha24
}

Caso "registro: falha antiga seguida de sucesso não é falha" {
  Igual (UltimaFalhaDoBackup @($inicio24, $falha24, $inicio23, $ok23)) $null
}

Caso "registro: aviso depois do sucesso não é falha" {
  Igual (UltimaFalhaDoBackup @($inicio23, $ok23, $aviso24)) $null
}

Caso "registro: vazio" {
  Igual (UltimaFalhaDoBackup @()) $null
}

if ($falhas) {
  Write-Host "`n$falhas caso(s) falharam."
  exit 1
}
Write-Host "`nTodos os casos passaram."
exit 0
