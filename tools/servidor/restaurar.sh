#!/usr/bin/env bash
# Restaura um backup num servidor novo: banco, fotos e gravações.
#
# Para depois de perder o servidor (ou o PC do Windows): com o .env.production
# novo (segredos novos) e o código clonado, devolve o banco e os arquivos do
# backup e aplica as migrações. As sessões abertas caem; cada pessoa entra de
# novo com a própria senha, que está no banco.
#
# Recusa restaurar por cima de um banco que já tem animais: restaurar é para
# servidor vazio. Conferido em 16/10/2026: os arquivos do MinIO de um backup
# abrem com as credenciais novas.
#
# Uso:
#   tools/servidor/restaurar.sh belo-vale-AAAA-MM-DD_HHMM.tar.gpg
#   tools/servidor/restaurar.sh --so-dados belo-vale-...tar.gpg   # sem subir o app

. "$(dirname "$0")/comum.sh"

SO_DADOS=0
if [[ "${1:-}" == "--so-dados" ]]; then
  SO_DADOS=1
  shift
fi
ARQUIVO="${1:?Uso: tools/servidor/restaurar.sh [--so-dados] <cópia .tar.gpg ou .tar>}"
[[ -f "$ARQUIVO" ]] || { echo "Cópia não encontrada: $ARQUIVO" >&2; exit 1; }
[[ -f "$SENHA_ARQUIVO" || "$ARQUIVO" != *.gpg ]] || {
  echo "Falta a senha do backup em $SENHA_ARQUIVO." >&2
  exit 1
}

TRABALHO="$(mktemp -d)"
trap 'rm -rf "$TRABALHO"' EXIT

echo "1/6 Abrindo a cópia..."
if [[ "$ARQUIVO" == *.gpg ]]; then
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$SENHA_ARQUIVO" \
    --decrypt --output "$TRABALHO/copia.tar" "$ARQUIVO"
else
  cp "$ARQUIVO" "$TRABALHO/copia.tar"
fi
mkdir "$TRABALHO/conteudo"
tar -xf "$TRABALHO/copia.tar" -C "$TRABALHO/conteudo"
sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' "$TRABALHO/conteudo/manifesto.txt" >"$TRABALHO/manifesto"
grep -E '^[0-9a-f]{64}  ' "$TRABALHO/manifesto" >"$TRABALHO/somas"
(cd "$TRABALHO/conteudo" && sha256sum --check --quiet "$TRABALHO/somas")
echo "    somas conferem: $(head -n 1 "$TRABALHO/manifesto")"

echo "2/6 Subindo só o armazenamento (banco, arquivos, fila)..."
compose up -d --wait db minio redis

# Duas consultas: o Postgres confere o nome da tabela antes de executar, e
# um CASE com a contagem falharia justamente no banco vazio.
ANIMAIS=0
TEM_TABELA="$(compose exec -T db psql -U ingestion -d ingestion -tAc "SELECT to_regclass('public.animals') IS NOT NULL")"
if [[ "$TEM_TABELA" == "t" ]]; then
  ANIMAIS="$(compose exec -T db psql -U ingestion -d ingestion -tAc 'SELECT count(*) FROM animals')"
fi
if [[ "$ANIMAIS" != "0" ]]; then
  echo "O banco já tem $ANIMAIS animais: restaurar é para servidor vazio. Nada foi alterado." >&2
  exit 1
fi

echo "3/6 Restaurando o banco..."
compose cp "$TRABALHO/conteudo/banco.dump" db:/tmp/banco.dump >/dev/null
compose exec -T db pg_restore -U ingestion -d ingestion --no-owner --exit-on-error /tmp/banco.dump
compose exec -T db rm -f /tmp/banco.dump

echo "4/6 Restaurando fotos e gravações..."
compose stop minio
docker run --rm --network none -v "${PROJETO}_minio_data:/data" -v "$TRABALHO/conteudo:/b:ro" \
  postgres:17-alpine sh -c 'rm -rf /data/* /data/.minio.sys && tar xzf /b/midia.tgz -C /data'
compose up -d --wait minio

if [[ "$SO_DADOS" == "1" ]]; then
  echo "5/6 (pulado: --so-dados) Suba o app e aplique as migrações com: tools/servidor/producao.sh atualizar"
else
  echo "5/6 Subindo o resto e aplicando as migrações..."
  compose up -d --build --wait
  compose exec -T api uv run --no-sync alembic upgrade head
fi

echo "6/6 Conferindo as contagens com o manifesto..."
RESTAURADO="$(compose exec -T db psql -U ingestion -d ingestion -tA -c "$CONSULTA_CONTAGENS")"
while read -r esperado; do
  if ! grep -qx "$esperado" <<<"$RESTAURADO"; then
    echo "Contagem diferente: esperado $esperado, restaurado $(tr '\n' ' ' <<<"$RESTAURADO")" >&2
    exit 1
  fi
done < <(grep -E '^[a-z]+=[0-9]+$' "$TRABALHO/manifesto")
echo "Restaurado e conferido: $(tr '\n' ' ' <<<"$RESTAURADO")"
