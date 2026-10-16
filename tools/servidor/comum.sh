# Partes comuns dos scripts do servidor Linux. Carregado com
# `. "$(dirname "$0")/comum.sh"`; não roda sozinho.
#
# Tudo o que é da produção e não é código fica em ~/.belo-vale/, legível só
# pelo usuário do servidor:
#
#   senha-backup.txt   senha da criptografia do backup (anote no papel)
#   b2.env             B2_KEY_ID, B2_APP_KEY e B2_BUCKET do Backblaze
#   backup.log         registro dos backups
#   verificacao.log    registro das verificações
#   ultimo-backup.txt  nome e tamanho do último backup que deu certo
#   copias/            as últimas cópias cifradas, para restaurar rápido

# As variáveis daqui são usadas pelos scripts que carregam este arquivo.
# shellcheck disable=SC2034
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASTA="${BV_PASTA:-$HOME/.belo-vale}"
PROJETO="belo-vale"
ENV_PRODUCAO="${BV_ENV:-$REPO/infra/.env.production}"
SENHA_ARQUIVO="$PASTA/senha-backup.txt"
B2_ENV="$PASTA/b2.env"
# Destino das cópias cifradas: um remoto do rclone. O padrão é o bucket do
# Backblaze; nos testes, uma pasta local.
DESTINO="${BV_DESTINO:-}"

mkdir -p "$PASTA"
chmod 700 "$PASTA"

# O rclone é configurado só por variáveis de ambiente: sem isto, ele avisa a
# cada chamada que não achou o arquivo de configuração.
export RCLONE_CONFIG=/dev/null

# A mesma linha no terminal e no registro: o agendamento roda sem ninguém olhando.
registrar() {
  local log="$1"
  shift
  local linha
  linha="$(date '+%Y-%m-%d %H:%M:%S')  $*"
  echo "$linha" | tee -a "$log"
}

compose() {
  if [[ ! -f "$ENV_PRODUCAO" ]]; then
    echo "Falta $ENV_PRODUCAO. Gere com: python3 tools/gerar_env_producao.py" >&2
    return 1
  fi
  docker compose -p "$PROJETO" --env-file "$ENV_PRODUCAO" \
    -f "$REPO/infra/docker-compose.yml" -f "$REPO/infra/docker-compose.prod.yml" "$@"
}

# As credenciais do Backblaze viram a configuração do rclone por variável de
# ambiente: nada de arquivo de configuração com a chave fora de ~/.belo-vale.
carregar_destino() {
  if [[ -n "$DESTINO" ]]; then
    return 0
  fi
  if [[ ! -f "$B2_ENV" ]]; then
    echo "Falta $B2_ENV com B2_KEY_ID, B2_APP_KEY e B2_BUCKET (ver docs/runbook-producao.md)." >&2
    return 1
  fi
  # shellcheck disable=SC1090
  . "$B2_ENV"
  export RCLONE_CONFIG_B2_TYPE=b2
  export RCLONE_CONFIG_B2_ACCOUNT="$B2_KEY_ID"
  export RCLONE_CONFIG_B2_KEY="$B2_APP_KEY"
  # Com Object Lock, o B2 não deixa apagar a cópia antes do prazo; o rclone
  # não precisa tentar.
  export RCLONE_CONFIG_B2_HARD_DELETE=false
  DESTINO="b2:$B2_BUCKET"
}

# As mesmas contagens do manifesto do backup e da verificação.
CONSULTA_CONTAGENS="SELECT 'animais='||count(*) FROM animals UNION ALL SELECT 'medicoes='||count(*) FROM official_measurements UNION ALL SELECT 'propostas='||count(*) FROM event_proposals UNION ALL SELECT 'usuarios='||count(*) FROM users UNION ALL SELECT 'arquivos='||count(*) FROM media_assets"
