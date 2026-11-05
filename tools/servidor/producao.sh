#!/usr/bin/env bash
# Operação do Belo Vale II em produção, no servidor Linux.
#
#   tools/servidor/producao.sh estado      o que está no ar: contêineres, app,
#                                          acesso pela internet, último backup
#   tools/servidor/producao.sh subir       sobe o que estiver parado
#   tools/servidor/producao.sh atualizar   depois de um merge: backup, código
#                                          novo, migrações e conferência
#   tools/servidor/producao.sh registros [api|worker|web|db|minio]
#   tools/servidor/producao.sh parar       para tudo, sem apagar dados
#   tools/servidor/producao.sh backup      backup agora
#   tools/servidor/producao.sh verificar   prova que o último backup restaura

. "$(dirname "$0")/comum.sh"

COMANDO="${1:-estado}"
SERVICO="${2:-api}"
APP="http://127.0.0.1:8090"

responde() {
  curl -fs -o /dev/null --max-time 5 "$1"
}

case "$COMANDO" in
estado)
  compose ps --format 'table {{.Service}}\t{{.Status}}'
  if responde "$APP/healthz"; then echo "App local ($APP): no ar"; else echo "App local ($APP): FORA DO AR"; fi
  if command -v tailscale >/dev/null; then
    echo "Acesso pela internet (Funnel):"
    tailscale funnel status || true
  else
    echo "Tailscale não instalado: o app não está na internet."
  fi
  echo "Último backup: $(cat "$PASTA/ultimo-backup.txt" 2>/dev/null || echo nenhum)"
  # O "Último backup" só avança quando dá certo; sem isto, uma falha diária
  # ficaria escondida atrás da data do último que funcionou.
  if [[ -f "$PASTA/backup.log" ]]; then
    ULTIMA="$(grep -E 'Backup concluído|FALHOU' "$PASTA/backup.log" | tail -n 1 || true)"
    if [[ "$ULTIMA" == *FALHOU* ]]; then echo "A ÚLTIMA TENTATIVA DE BACKUP FALHOU: ${ULTIMA#*FALHOU: }"; fi
  fi
  if [[ -f "$PASTA/verificacao.log" ]]; then
    echo "Última verificação: $(grep -E 'OK: o backup restaura|FALHOU' "$PASTA/verificacao.log" | tail -n 1 || echo nenhuma)"
  fi
  df -h / | tail -n 1 | awk '{print "Disco: " $4 " livres de " $2}'
  ;;
subir)
  compose up -d --wait
  ;;
atualizar)
  "$REPO/tools/servidor/backup.sh"
  git -C "$REPO" pull --ff-only
  compose build api worker web
  # Migrações aditivas antes de trocar os serviços: uma recusa de migração
  # mantém a aplicação anterior, em vez de iniciar código sobre schema antigo.
  compose run --rm --no-deps api uv run --no-sync alembic upgrade head
  compose up -d --wait
  responde "$APP/healthz" || { echo "O app não voltou. Veja: $0 registros api" >&2; exit 1; }
  # As imagens antigas e o cache da compilação enchem o disco aos poucos.
  docker image prune -f >/dev/null
  echo "Atualizado e no ar."
  ;;
registros)
  compose logs --tail 80 "$SERVICO"
  ;;
parar)
  compose stop
  ;;
backup)
  "$REPO/tools/servidor/backup.sh"
  ;;
verificar)
  "$REPO/tools/servidor/verificar-backup.sh"
  ;;
*)
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
