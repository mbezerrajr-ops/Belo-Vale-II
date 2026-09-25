<#
.SYNOPSIS
  Regras do backup: o que conta como cópia fora deste PC, e como ler o
  registro. Sem efeito nenhum: só funções, carregadas com ". regras.ps1".

.DESCRIPTION
  Até 24/09/2026 o backup contava a pasta do OneDrive como "nuvem" só por
  ela existir. No PC da produção nenhuma conta estava conectada: a cópia
  criptografada ficava no mesmo disco, e o registro dizia "concluído".
  Testes: testar-regras.ps1.
#>

# Caminhos do Windows não diferenciam maiúsculas, e "/" vale como "\".
function PastaNormalizada([string]$pasta) {
  return ($pasta -replace "/", "\").TrimEnd("\").ToLowerInvariant()
}

# $null quando a pasta está dentro da pasta de uma conta do OneDrive
# conectada (a cópia sobe para a nuvem); senão, o motivo, para o registro.
function MotivoNuvemNoPc([string]$pasta, [string[]]$contas) {
  $alvo = PastaNormalizada $pasta
  foreach ($conta in $contas) {
    $raiz = PastaNormalizada $conta
    if ($raiz -and ($alvo -eq $raiz -or $alvo.StartsWith($raiz + "\"))) { return $null }
  }
  return "a pasta $pasta não está em nenhuma conta do OneDrive conectada: a cópia ficou só neste PC"
}

# $null quando o destino do HD fica fora do disco do sistema; senão, o motivo.
# Pasta de rede (\\servidor\...) sai do PC.
function MotivoHdNoPc([string]$pasta, [string]$discoDoSistema) {
  if ($pasta -match "^([A-Za-z]:)" -and $Matches[1] -eq $discoDoSistema) {
    return "a pasta $pasta fica no disco do sistema ($discoDoSistema), não num HD externo: a cópia ficou só neste PC"
  }
  return $null
}

# A linha da última tentativa de backup, se ela falhou; $null se deu certo ou
# se o registro não tem tentativa nenhuma.
function UltimaFalhaDoBackup([string[]]$linhas) {
  for ($i = $linhas.Count - 1; $i -ge 0; $i--) {
    if ($linhas[$i] -match "  FALHOU: ") { return $linhas[$i] }
    if ($linhas[$i] -match "  Backup conclu") { return $null }
  }
  return $null
}

# Pastas das contas do OneDrive conectadas neste Windows, pessoal e de
# trabalho. Conta desconectada fica no registro sem e-mail e sem pasta.
function PastasDoOneDriveConectadas {
  Get-ChildItem "HKCU:\Software\Microsoft\OneDrive\Accounts" -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ItemProperty $_.PSPath } |
    Where-Object { $_.UserEmail -and $_.UserFolder } |
    ForEach-Object { $_.UserFolder }
}
