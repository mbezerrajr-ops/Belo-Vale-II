#!/usr/bin/env bash
# Backup diário do Belo Vale II no servidor Linux: banco, fotos e gravações.
#
# O mesmo pacote do backup do Windows (tools/backup/backup.ps1) — banco.dump,
# midia.tgz e manifesto.txt num .tar, cifrado com AES-256 pelo gpg —, para
# que qualquer cópia, antiga ou nova, abra do mesmo jeito.
#
# Saídas:
#
# - Backblaze B2, no nome do cliente: a cópia cifrada. Só conta como backup
#   feito quando ela chega lá e o tamanho confere. Com Object Lock no bucket,
#   nem quem invadir o servidor apaga as cópias dentro do prazo.
# - ~/.belo-vale/copias/: as últimas $MANTER_LOCAL cópias cifradas, para
#   restaurar rápido. Não contam como backup: estão no mesmo disco.
#
# A senha é gerada na primeira execução, em ~/.belo-vale/senha-backup.txt.
# ANOTE-A NO PAPEL e entregue uma cópia ao cliente: sem ela, nenhuma cópia
# abre.
#
# Uso: tools/servidor/backup.sh

. "$(dirname "$0")/comum.sh"

MANTER_LOCAL="${BV_MANTER_LOCAL:-7}"
LOG="$PASTA/backup.log"
NOME="belo-vale-$(date '+%Y-%m-%d_%H%M')"
TEMP="$(mktemp -d)"
COPIAS="$PASTA/copias"

# Nada de dado do rebanho sobra na pasta temporária, dê certo ou não.
limpar() {
  rm -rf "$TEMP"
  compose exec -T db rm -f /tmp/backup.dump >/dev/null 2>&1 || true
}
trap limpar EXIT

falhou() {
  registrar "$LOG" "FALHOU: $*"
  exit 1
}

senha_do_backup() {
  if [[ ! -f "$SENHA_ARQUIVO" ]]; then
    # 32 caracteres sem os que se confundem no papel, em grupos de 4.
    (umask 077 && tr -dc 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789' </dev/urandom |
      head -c 32 | fold -w 4 | paste -sd- | tr -d '\n' >"$SENHA_ARQUIVO")
    registrar "$LOG" "Senha do backup criada em $SENHA_ARQUIVO — anote-a no papel."
  fi
  chmod 600 "$SENHA_ARQUIVO"
}

registrar "$LOG" "Início do backup $NOME"
carregar_destino || falhou "destino do backup não configurado ($B2_ENV)"
senha_do_backup

# 1. Banco: pg_dump no formato do Postgres, consistente com o app em uso.
compose exec -T db pg_dump -U ingestion -d ingestion -Fc -f /tmp/backup.dump ||
  falhou "o pg_dump não rodou"
compose cp db:/tmp/backup.dump "$TEMP/banco.dump" >/dev/null || falhou "não consegui copiar o dump"

# 2. Fotos e gravações: o volume do armazenamento, só leitura.
docker run --rm --network none -v "${PROJETO}_minio_data:/data:ro" -v "$TEMP:/backup" \
  postgres:17-alpine tar czf /backup/midia.tgz -C /data . ||
  falhou "não consegui copiar fotos e gravações"

# 3. Manifesto: contagens e somas, para a verificação comparar. Um comando
#    por vez, cada um checado: num bloco `{ ...; } || falhou`, o bash ignora
#    o erro do meio e o backup de um banco quebrado passaria como bom.
CONTAGENS="$(compose exec -T db psql -U ingestion -d ingestion -tA -c "$CONSULTA_CONTAGENS")" ||
  falhou "não consegui contar os registros do banco"
SOMAS="$(cd "$TEMP" && sha256sum banco.dump midia.tgz)" || falhou "não consegui calcular as somas"
printf 'backup=%s\n%s\n%s\n' "$NOME" "$CONTAGENS" "$SOMAS" >"$TEMP/manifesto.txt"

# 4. Um arquivo só, cifrado.
tar -cf "$TEMP/$NOME.tar" -C "$TEMP" banco.dump midia.tgz manifesto.txt || falhou "não consegui empacotar"
gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$SENHA_ARQUIVO" \
  --symmetric --cipher-algo AES256 --output "$TEMP/$NOME.tar.gpg" "$TEMP/$NOME.tar" ||
  falhou "não consegui cifrar a cópia"
TAMANHO="$(du -h "$TEMP/$NOME.tar.gpg" | cut -f1)"

# 5. Cópia local (restauração rápida) — não conta como backup.
mkdir -p "$COPIAS"
cp "$TEMP/$NOME.tar.gpg" "$COPIAS/"
ls -1 "$COPIAS"/belo-vale-*.tar.gpg | sort -r | tail -n "+$((MANTER_LOCAL + 1))" | xargs -r rm -f

# 6. Fora do servidor. Só conta se chegou e o tamanho confere.
rclone copyto "$TEMP/$NOME.tar.gpg" "$DESTINO/$NOME.tar.gpg" --retries 3 ||
  falhou "a cópia não chegou ao destino ($DESTINO); ficou só neste servidor"
ENVIADO="$(rclone size --json "$DESTINO/$NOME.tar.gpg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bytes"])')"
LOCAL="$(stat -c %s "$TEMP/$NOME.tar.gpg")"
[[ "$ENVIADO" == "$LOCAL" ]] || falhou "a cópia no destino tem $ENVIADO bytes, a daqui $LOCAL"

echo "$NOME ($TAMANHO)" >"$PASTA/ultimo-backup.txt"
registrar "$LOG" "Backup concluído: $NOME ($TAMANHO), enviado para $DESTINO."
