<#
.SYNOPSIS
  Prova que um backup restaura, sem tocar na produção.

.DESCRIPTION
  Abre a cópia (decifra se for .gpg), restaura o banco num Postgres
  descartável, sem rede e sem porta publicada, e compara as contagens com o
  manifesto gravado no dia do backup. Confere também as somas SHA-256 e o
  arquivo de fotos e gravações. No fim, apaga tudo o que criou.

  Sem -Arquivo, usa a cópia mais recente da nuvem.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\backup\verificar-backup.ps1
  powershell -ExecutionPolicy Bypass -File tools\backup\verificar-backup.ps1 -Arquivo E:\BeloVale-backup\belo-vale-2026-09-22_0330.tar
#>
param([string]$Arquivo)

$ErrorActionPreference = "Stop"
$Gpg = "C:\Program Files\Git\usr\bin\gpg.exe"
$Senha = Join-Path $env:USERPROFILE ".belo-vale\senha-backup.txt"
$Trabalho = Join-Path $env:TEMP ("verifica-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$Container = "belo-vale-verifica-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$Codigo = 1
$Log = Join-Path $env:USERPROFILE ".belo-vale\verificacao.log"
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null

# Na tela e no registro: agendada, a verificação roda sem ninguém olhando.
function Write-Host([string]$texto) {
  $linha = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $texto
  Add-Content -Path $Log -Value $linha -Encoding UTF8
  Microsoft.PowerShell.Utility\Write-Host $linha
}

try {
  if (-not $Arquivo) {
    $Arquivo = (Get-ChildItem (Join-Path $env:OneDrive "BeloVale-backup") -Filter "belo-vale-*.tar.gpg" |
      Sort-Object Name -Descending | Select-Object -First 1).FullName
  }
  if (-not $Arquivo -or -not (Test-Path $Arquivo)) { throw "cópia não encontrada: $Arquivo" }
  Write-Host "Verificando $Arquivo"
  New-Item -ItemType Directory -Force $Trabalho | Out-Null

  $tar = Join-Path $Trabalho "backup.tar"
  if ($Arquivo.EndsWith(".gpg")) {
    & $Gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file $Senha --decrypt --output $tar $Arquivo
    if ($LASTEXITCODE -ne 0) { throw "não abriu: senha errada ou arquivo danificado" }
  } else {
    Copy-Item $Arquivo $tar
  }
  $pasta = Join-Path $Trabalho "conteudo"
  New-Item -ItemType Directory -Force $pasta | Out-Null
  & tar -xf $tar -C $pasta
  if ($LASTEXITCODE -ne 0) { throw "o pacote não abriu (tar)" }

  # 1. Somas: cada arquivo é o que foi gravado no dia.
  $manifesto = Get-Content (Join-Path $pasta "manifesto.txt") -Encoding UTF8
  foreach ($linha in $manifesto | Where-Object { $_ -match "^[0-9a-f]{64}  " }) {
    $soma, $nome = $linha -split "  ", 2
    $atual = (Get-FileHash (Join-Path $pasta $nome) -Algorithm SHA256).Hash.ToLower()
    if ($atual -ne $soma) { throw "soma diferente em ${nome}: o arquivo foi alterado ou corrompido" }
  }
  Write-Host "Somas SHA-256 conferem."

  # 2. Fotos e gravações: o arquivo abre inteiro.
  $objetos = & docker run --rm --network none -v "${pasta}:/b:ro" postgres:17-alpine sh -c "tar tzf /b/midia.tgz | wc -l"
  if ($LASTEXITCODE -ne 0) { throw "o arquivo de fotos e gravações está danificado" }
  Write-Host "Fotos e gravações: arquivo íntegro ($($objetos.Trim()) entradas)."

  # 3. Banco: restaura num Postgres descartável, sem rede.
  & docker run -d --name $Container --network none -e POSTGRES_PASSWORD=verifica -e POSTGRES_DB=verifica `
    -v "${pasta}:/b:ro" postgres:17-alpine | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "não consegui subir o banco descartável" }
  for ($i = 0; $i -lt 30; $i++) {
    & docker exec $Container pg_isready -U postgres -d verifica 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
  }
  # O banco de produção pertence ao papel "ingestion": cria o mesmo papel.
  & docker exec $Container psql -U postgres -d verifica -qc "CREATE ROLE ingestion" | Out-Null
  & docker exec $Container pg_restore -U postgres -d verifica --no-owner --exit-on-error /b/banco.dump
  if ($LASTEXITCODE -ne 0) { throw "o banco não restaurou" }

  $consulta = "SELECT 'animais='||count(*) FROM animals UNION ALL SELECT 'medicoes='||count(*) FROM official_measurements UNION ALL SELECT 'propostas='||count(*) FROM event_proposals UNION ALL SELECT 'usuarios='||count(*) FROM users UNION ALL SELECT 'arquivos='||count(*) FROM media_assets"
  $restaurado = & docker exec $Container psql -U postgres -d verifica -tA -c $consulta
  $esperado = $manifesto | Where-Object { $_ -match "^[a-z]+=\d+$" }
  foreach ($linha in $esperado) {
    if ($restaurado -notcontains $linha) { throw "contagem diferente: esperado $linha, restaurado $($restaurado -join ', ')" }
  }
  Write-Host ("Banco restaurado e conferido: " + ($restaurado -join ", "))
  Write-Host "OK: o backup restaura."
  $Codigo = 0
} catch {
  Write-Host "FALHOU: $($_.Exception.Message)"
} finally {
  # O gpg deixa um agente rodando, que guarda a senha em memória por alguns
  # minutos e prende o terminal que chamou o script. Encerra ao sair.
  & "C:\Program Files\Git\usr\bin\gpgconf.exe" --kill gpg-agent 2>$null | Out-Null
  & docker rm -f $Container 2>$null | Out-Null
  if (Test-Path $Trabalho) { Remove-Item $Trabalho -Recurse -Force }
}
exit $Codigo
