#!/usr/bin/env bash
# Instala o backup diário (3h30) e a verificação semanal (domingo, 4h30)
# como timers do systemd. Roda uma vez, com sudo, depois que o primeiro
# backup manual deu certo.
#
#   sudo tools/servidor/instalar-agendamentos.sh
#   systemctl list-timers 'belo-vale-*'

set -euo pipefail
PASTA="$(cd "$(dirname "$0")" && pwd)/systemd"
install -m 644 "$PASTA"/belo-vale-*.service "$PASTA"/belo-vale-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now belo-vale-backup.timer belo-vale-verifica.timer
systemctl list-timers 'belo-vale-*'
