<#
.SYNOPSIS
  Backup diário do Belo Vale II: banco, fotos e gravações.

.DESCRIPTION
  Uma cópia por execução, com duas saídas:

  - HD externo (pasta em $HdDestino): a cópia como está, para restaurar rápido.
    Ficam as últimas $ManterHd.
  - Nuvem (pasta sincronizada do OneDrive): a mesma cópia criptografada com
    AES-256 (gpg). Só quem tem a senha abre. Ficam as últimas $ManterNuvem.
    Depois de subir, o arquivo deixa de ocupar o disco C: (Arquivos Sob
    Demanda do OneDrive).

  Só conta como backup feito quando ao menos uma cópia sai deste PC: a pasta
  do OneDrive precisa estar numa conta conectada, e a do HD fora do disco do
  sistema. Sem isso, a cópia fica gravada aqui mesmo (ainda serve contra um
  erro nos dados), mas o backup termina como FALHOU no registro, com o
  motivo, e o "Último backup" do producao.ps1 não avança.

  A senha da criptografia é gerada na primeira execução e fica em
  %USERPROFILE%\.belo-vale\senha-backup.txt, legível só pela conta do Windows
  que roda o backup. ANOTE-A NO PAPEL: se este PC se perder, é a única forma
  de abrir a cópia da nuvem.

  O banco sai pelo pg_dump (formato próprio do Postgres, consistente mesmo
  com o app em uso); fotos e gravações saem do volume do MinIO, somente
  leitura. Nada aqui altera a produção.

.PARAMETER HdDestino
  Pasta no HD externo, por exemplo E:\BeloVale-backup. Sem HD conectado, o
  backup segue só para a nuvem e registra o aviso.
#>
param(
  [string]$HdDestino = $env:BV_BACKUP_HD,
  [string]$NuvemDestino = $(if ($env:OneDrive) { Join-Path $env:OneDrive "BeloVale-backup" } else { "" }),
  [int]$ManterHd = 30,
  [int]$ManterNuvem = 14
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "regras.ps1")
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Pasta = Join-Path $env:USERPROFILE ".belo-vale"
$Log = Join-Path $Pasta "backup.log"
$SenhaArquivo = Join-Path $Pasta "senha-backup.txt"
$ConfigHd = Join-Path $Pasta "hd-destino.txt"
$Gpg = "C:\Program Files\Git\usr\bin\gpg.exe"
$Projeto = "belo-vale"
$Carimbo = Get-Date -Format "yyyy-MM-dd_HHmm"
$Nome = "belo-vale-$Carimbo"

New-Item -ItemType Directory -Force $Pasta | Out-Null

function Registrar([string]$texto) {
  $linha = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $texto
  Add-Content -Path $Log -Value $linha -Encoding UTF8
  # Write-Host, não Write-Output: uma função que registra no meio do caminho
  # (SenhaDoBackup) devolveria a mensagem junto com o valor.
  Write-Host $linha
}

function Compose([string[]]$argumentos) {
  $base = @("compose", "-p", $Projeto, "--env-file", (Join-Path $Repo "infra\.env.production"),
    "-f", (Join-Path $Repo "infra\docker-compose.yml"), "-f", (Join-Path $Repo "infra\docker-compose.prod.yml"))
  & docker @($base + $argumentos)
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($argumentos -join ' ') falhou ($LASTEXITCODE)" }
}

# Só a conta que roda o backup lê a senha.
function Proteger([string]$arquivo) {
  & icacls $arquivo /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
}

function SenhaDoBackup {
  if (-not (Test-Path $SenhaArquivo)) {
    $letras = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $chars = $bytes | ForEach-Object { $letras[$_ % $letras.Length] }
    # Em grupos de 4, para anotar no papel sem errar.
    $senha = (0..7 | ForEach-Object { -join $chars[($_ * 4)..($_ * 4 + 3)] }) -join "-"
    Set-Content -Path $SenhaArquivo -Value $senha -NoNewline -Encoding ASCII
    Proteger $SenhaArquivo
    Registrar "Senha do backup criada em $SenhaArquivo — anote-a no papel."
  }
  return $SenhaArquivo
}

function Limpar([string]$pasta, [string]$padrao, [int]$manter) {
  Get-ChildItem -Path $pasta -Filter $padrao -File | Sort-Object Name -Descending |
    Select-Object -Skip $manter | ForEach-Object { Remove-Item $_.FullName -Force }
}

$Temp = Join-Path $env:TEMP $Nome
$Pacote = $null
$Codigo = 1
try {
  if (-not $HdDestino -and (Test-Path $ConfigHd)) { $HdDestino = (Get-Content $ConfigHd -Raw).Trim() }
  New-Item -ItemType Directory -Force $Temp | Out-Null
  Registrar "Início do backup $Nome"

  # 1. Banco: pg_dump dentro do contêiner, copiado para fora (sem passar
  #    binário por pipe do PowerShell, que o corromperia).
  Compose @("exec", "-T", "db", "pg_dump", "-U", "ingestion", "-d", "ingestion", "-Fc", "-f", "/tmp/backup.dump")
  $db = (& docker compose -p $Projeto --env-file (Join-Path $Repo "infra\.env.production") -f (Join-Path $Repo "infra\docker-compose.yml") -f (Join-Path $Repo "infra\docker-compose.prod.yml") ps -q db).Trim()
  & docker cp "${db}:/tmp/backup.dump" (Join-Path $Temp "banco.dump") | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "não consegui copiar o dump do banco" }
  Compose @("exec", "-T", "db", "rm", "-f", "/tmp/backup.dump")

  # 2. Fotos e gravações: o volume do MinIO, montado só para leitura. Usa a
  #    imagem do Postgres, que já está no PC (tem tar e gzip).
  & docker run --rm -v "${Projeto}_minio_data:/data:ro" -v "${Temp}:/backup" postgres:17-alpine `
    tar czf /backup/midia.tgz -C /data .
  if ($LASTEXITCODE -ne 0) { throw "não consegui copiar fotos e gravações" }

  # 3. Manifesto: o que a cópia deve conter, para a verificação comparar.
  $contagens = Compose @("exec", "-T", "db", "psql", "-U", "ingestion", "-d", "ingestion", "-tA", "-c",
    "SELECT 'animais='||count(*) FROM animals UNION ALL SELECT 'medicoes='||count(*) FROM official_measurements UNION ALL SELECT 'propostas='||count(*) FROM event_proposals UNION ALL SELECT 'usuarios='||count(*) FROM users UNION ALL SELECT 'arquivos='||count(*) FROM media_assets")
  $hashes = Get-ChildItem $Temp -File | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
  Set-Content -Path (Join-Path $Temp "manifesto.txt") -Encoding UTF8 -Value (@("backup=$Nome") + $contagens + $hashes)

  # 4. Um arquivo só, com o tar do próprio Windows.
  $Pacote = Join-Path $env:TEMP "$Nome.tar"
  & tar -cf $Pacote -C $Temp .
  if ($LASTEXITCODE -ne 0) { throw "não consegui empacotar o backup" }
  $tamanho = "{0:N1} MB" -f ((Get-Item $Pacote).Length / 1MB)

  # Uma cópia no mesmo disco não sobrevive a ele: só conta o que sai do PC.
  $saidas = 0
  $foraDoPc = 0
  if ($HdDestino -and (Test-Path ([IO.Path]::GetPathRoot($HdDestino)))) {
    New-Item -ItemType Directory -Force $HdDestino | Out-Null
    Copy-Item $Pacote (Join-Path $HdDestino "$Nome.tar") -Force
    Limpar $HdDestino "belo-vale-*.tar" $ManterHd
    Registrar "HD externo: $HdDestino\$Nome.tar ($tamanho)"
    $saidas++
    $motivo = MotivoHdNoPc $HdDestino $env:SystemDrive
    if ($motivo) { Registrar "AVISO: $motivo" } else { $foraDoPc++ }
  } else {
    Registrar "AVISO: HD externo não encontrado ($HdDestino). Conecte o HD para a cópia local."
  }

  if ($NuvemDestino) {
    New-Item -ItemType Directory -Force $NuvemDestino | Out-Null
    $cifrado = Join-Path $NuvemDestino "$Nome.tar.gpg"
    & $Gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file (SenhaDoBackup) `
      --symmetric --cipher-algo AES256 --output $cifrado $Pacote
    if ($LASTEXITCODE -ne 0) { throw "não consegui criptografar a cópia da nuvem" }
    Limpar $NuvemDestino "belo-vale-*.tar.gpg" $ManterNuvem
    Registrar "Nuvem (criptografada): $cifrado"
    $saidas++
    $motivo = MotivoNuvemNoPc $NuvemDestino @(PastasDoOneDriveConectadas)
    if ($motivo) {
      Registrar "AVISO: $motivo"
    } else {
      # Sobe para a nuvem e deixa de ocupar o C: (fica só o atalho do OneDrive).
      & attrib +U -P $cifrado | Out-Null
      $foraDoPc++
    }
  }

  if ($saidas -eq 0) { throw "nenhum destino disponível: nem HD externo nem pasta da nuvem" }
  if ($foraDoPc -eq 0) {
    throw "nenhuma cópia saiu deste PC. Conecte o OneDrive ou o HD externo; a de hoje ficou só neste disco."
  }
  Set-Content -Path (Join-Path $Pasta "ultimo-backup.txt") -Value "$Nome ($tamanho)" -Encoding UTF8
  Registrar "Backup concluído: $Nome ($tamanho), $saidas destino(s)."
  $Codigo = 0
} catch {
  Registrar "FALHOU: $($_.Exception.Message)"
} finally {
  # O gpg deixa um agente rodando, que guarda a senha em memória por alguns
  # minutos e prende o terminal que chamou o script. Encerra ao sair.
  & "C:\Program Files\Git\usr\bin\gpgconf.exe" --kill gpg-agent 2>$null | Out-Null
  # Nada de dado do rebanho sobra na pasta temporária do C:.
  if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force }
  if ($Pacote -and (Test-Path $Pacote)) { Remove-Item $Pacote -Force }
}
exit $Codigo
