#!/usr/bin/env bash
# Prova que um backup restaura, sem tocar na produção.
#
# Baixa a cópia (a mais recente do destino, ou o arquivo dado), decifra,
# confere as somas SHA-256 do manifesto, abre o arquivo de fotos e
# gravações, restaura o banco num Postgres descartável, sem rede, e compara
# as contagens com o manifesto. No fim, apaga tudo o que criou.
#
# Abre também as cópias feitas no Windows (tools/backup/backup.ps1): o
# pacote é o mesmo.
#
# Uso:
#   tools/servidor/verificar-backup.sh                 # a mais recente do destino
#   tools/servidor/verificar-backup.sh arquivo.tar.gpg # uma cópia local

. "$(dirname "$0")/comum.sh"

LOG="$PASTA/verificacao.log"
TRABALHO="$(mktemp -d)"
CONTAINER="belo-vale-verifica-$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"

limpar() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$TRABALHO"
}
trap limpar EXIT

falhou() {
  registrar "$LOG" "FALHOU: $*"
  exit 1
}

ARQUIVO="${1:-}"
if [[ -z "$ARQUIVO" ]]; then
  carregar_destino || falhou "destino do backup não configurado ($B2_ENV)"
  ULTIMO="$(rclone lsf "$DESTINO" --include 'belo-vale-*.tar.gpg' | sort | tail -n 1)"
  [[ -n "$ULTIMO" ]] || falhou "nenhuma cópia em $DESTINO"
  registrar "$LOG" "Verificando $DESTINO/$ULTIMO"
  rclone copyto "$DESTINO/$ULTIMO" "$TRABALHO/copia.tar.gpg" || falhou "não consegui baixar $ULTIMO"
else
  [[ -f "$ARQUIVO" ]] || falhou "cópia não encontrada: $ARQUIVO"
  registrar "$LOG" "Verificando $ARQUIVO"
  cp "$ARQUIVO" "$TRABALHO/copia.tar.gpg"
fi

gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$SENHA_ARQUIVO" \
  --decrypt --output "$TRABALHO/copia.tar" "$TRABALHO/copia.tar.gpg" ||
  falhou "não abriu: senha errada ou arquivo danificado"
mkdir "$TRABALHO/conteudo"
tar -xf "$TRABALHO/copia.tar" -C "$TRABALHO/conteudo" || falhou "o pacote não abriu (tar)"
CONTEUDO="$TRABALHO/conteudo"

# O manifesto do Windows vem com BOM e fim de linha \r\n.
sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' "$CONTEUDO/manifesto.txt" >"$TRABALHO/manifesto"

# 1. Somas: cada arquivo é o que foi gravado no dia.
grep -E '^[0-9a-f]{64}  ' "$TRABALHO/manifesto" >"$TRABALHO/somas" || falhou "o manifesto não traz as somas"
(cd "$CONTEUDO" && sha256sum --check --quiet "$TRABALHO/somas") ||
  falhou "soma diferente: algum arquivo foi alterado ou corrompido"
registrar "$LOG" "Somas SHA-256 conferem."

# 2. Fotos e gravações: o arquivo abre inteiro.
ENTRADAS="$(tar tzf "$CONTEUDO/midia.tgz" | wc -l)" || falhou "o arquivo de fotos e gravações está danificado"
registrar "$LOG" "Fotos e gravações: arquivo íntegro ($ENTRADAS entradas)."

# 3. Banco: num Postgres descartável, sem rede e sem porta.
docker run -d --name "$CONTAINER" --network none -e POSTGRES_PASSWORD=verifica -e POSTGRES_DB=verifica \
  -v "$CONTEUDO:/b:ro" postgres:17-alpine >/dev/null || falhou "não consegui subir o banco descartável"
# O Postgres reinicia uma vez ao terminar a primeira inicialização: espera
# ele responder a uma consulta, não só ao pg_isready.
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" psql -U postgres -d verifica -tAc 'select 1' >/dev/null 2>&1 && break
  sleep 1
done
# O banco de produção pertence ao papel "ingestion": cria o mesmo papel.
docker exec "$CONTAINER" psql -U postgres -d verifica -qc 'CREATE ROLE ingestion' >/dev/null
docker exec "$CONTAINER" pg_restore -U postgres -d verifica --no-owner --exit-on-error /b/banco.dump ||
  falhou "o banco não restaurou"

RESTAURADO="$(docker exec "$CONTAINER" psql -U postgres -d verifica -tA -c "$CONSULTA_CONTAGENS")" ||
  falhou "o banco restaurado não tem as tabelas do sistema"
while read -r esperado; do
  grep -qx "$esperado" <<<"$RESTAURADO" ||
    falhou "contagem diferente: esperado $esperado, restaurado $(tr '\n' ' ' <<<"$RESTAURADO")"
done < <(grep -E '^[a-z]+=[0-9]+$' "$TRABALHO/manifesto")

registrar "$LOG" "Banco restaurado e conferido: $(tr '\n' ' ' <<<"$RESTAURADO")"
registrar "$LOG" "OK: o backup restaura."
