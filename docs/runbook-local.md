# Runbook local — ambiente de homologação (Docker)

Todos os comandos abaixo foram executados de verdade durante o desenvolvimento
da Task 8, contra o `docker-compose.yml` deste repositório. Rode-os a partir
da raiz do repositório, salvo indicação contrária.

## Limite de integração com o legado

A `main` histórica ainda é a POC baseada em HTML/JSON. Esta arquitetura nova
fornece API, banco e frontend operacionais, mas **não migra os 401 animais nem
suas 152 medições da baseline canônica**. Portanto, integrar o código não é um cutover: os
JSONs, planilhas e HTMLs legados permanecem necessários para uma futura
migração e validação. PostgreSQL ainda não é a fonte definitiva dos dados
históricos.

## Validação da baseline legada

Rode a partir da raiz do repositório. A fonte de verdade é
`belo-vale-ii-projeto-completo/plataforma/state_canonical.json`; o HTML publicado e a
projeção sem histórico são derivados.

```powershell
python -m unittest belo-vale-ii-projeto-completo/testes/test_state_contract.py -v
python -m unittest belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py -v
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py validate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json
```

O resultado esperado da validação é 401 animais, 152 medições (107 em `2026-07-22` e 45
em `2026-08-25`), zero erro estrutural e 30 avisos de negócio. Avisos não bloqueiam a
geração e não alteram situação ou DEL automaticamente.

Para regenerar os derivados depois de uma alteração canônica validada:

```powershell
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py generate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json --template belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_template.html --published belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_publicado.html --projection belo-vale-ii-projeto-completo/plataforma/state_dados_atuais.json
```

Para ler novamente o PDF, instale primeiro
`belo-vale-ii-projeto-completo/plataforma/requirements-import.txt`. Execute o importador
sem `--write` para simular e atualizar somente o relatório; use `--write` apenas após
revisar a reconciliação. Em PowerShell, se o nome acentuado do PDF for corrompido pelo
terminal, descubra o caminho com `Path.glob("REL*ANIMAIS.pdf")`, como faz o teste real.

O PostgreSQL **ainda não recebeu esta baseline**. Não trate a execução dos comandos acima
como migração ou cutover.

## 1. Configurar variáveis de ambiente

Copie `infra/.env.example` para um arquivo de ambiente (por exemplo
`infra/.env.local`) e preencha os valores. Nunca commite o arquivo
preenchido — `.gitignore` já exclui `.env` e `.env.*` (exceto o próprio
`.env.example`).

```bash
cp infra/.env.example infra/.env.local
# edite infra/.env.local com valores reais
```

Em todos os comandos `docker compose` abaixo, use `--env-file infra/.env.local`
(ou o nome que você escolher) para que o compose resolva as variáveis.

## 2. Subir o ambiente

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml up --build -d
```

Sobe `db` (PostgreSQL 17), `redis`, `minio`, `api` (porta `8000`), `worker`
(sem porta publicada) e `web` (porta `8080`, nginx servindo o React
compilado e fazendo proxy reverso de `/api/*` e `/healthz` para `api`).

Verifique a saúde dos serviços:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml ps
```

Todos devem aparecer como `Up (healthy)` (exceto `worker`, que não tem
healthcheck — veja a seção de diagnóstico).

## 3. Migrações

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml exec api uv run --no-sync alembic upgrade head
```

## 4. Criar o primeiro administrador

O comando é interativo (pede a senha duas vezes via stdin, nunca aceita a
senha como argumento). Para rodar de forma não interativa (ex.: em scripts
de CI/seed), envie a senha por stdin:

```bash
printf "SUA_SENHA_AQUI\nSUA_SENHA_AQUI\n" | docker compose --env-file infra/.env.local -f infra/docker-compose.yml exec -T api uv run --no-sync python -m app.core.bootstrap_admin --email admin@example.com
```

O bootstrap se recusa a rodar se já existir qualquer usuário no banco.

## 5. Cadastrar fazenda e animal (cadastro mestre)

Pela API. A fazenda é resolvida no servidor: nenhum endpoint aceita `farm_id`
do cliente.

Crie a fazenda (exige **admin**) e confira qual está em uso:

```bash
curl -X POST http://localhost:8000/api/farms \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Belo Vale II"}'

curl http://localhost:8000/api/farms/current -H "Authorization: Bearer $TOKEN"
```

Cadastre um animal (exige **reviewer**). O brinco é opcional — um animal pode
entrar no cadastro antes de ter brinco:

```bash
curl -X POST http://localhost:8000/api/animals \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"brinco": "B2-008", "name": "Cabelo de Fogo", "lote": "LOTE 1"}'
```

Endpoints disponíveis:

| Método | Rota | Papel mínimo | Para quê |
| --- | --- | --- | --- |
| `POST` | `/api/farms` | admin | Cria a fazenda |
| `GET` | `/api/farms/current` | operator | A fazenda em uso |
| `POST` | `/api/animals` | reviewer | Cadastra animal |
| `GET` | `/api/animals` | operator | Lista, com `brinco`, `name`, `sem_brinco`, `limit`, `offset` |
| `GET` | `/api/animals/{id}` | operator | Detalhe com histórico de lotação |
| `PATCH` | `/api/animals/{id}` | reviewer | Campos descritivos (nome, situação, status…) |
| `POST` | `/api/animals/{id}/brinco` | reviewer | Vincula ou troca o brinco |
| `POST` | `/api/animals/{id}/lote` | reviewer | Registra mudança de lote |

### Vincular brinco a um animal que não tem

É por aqui que os 142 registros migrados sem brinco passam a receber matching
automático. Como muda a identidade operacional do animal, a evidência é
obrigatória e fica na auditoria junto com o valor anterior:

```bash
curl -X POST http://localhost:8000/api/animals/<ID>/brinco \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"brinco": "B2-731", "evidence": "Brinco aplicado no curral em 18/09/2026"}'
```

Para encontrar os animais nessa situação: `GET /api/animals?sem_brinco=true`.

O brinco **não** pode ser alterado pelo `PATCH` genérico — a requisição falha
explicitamente em vez de ser ignorada. Trocar de lote também tem rota própria,
porque acrescenta uma linha ao histórico em vez de sobrescrever a anterior.

## 6. Acessar a aplicação

Abra `http://localhost:8080` no navegador. Faça login com o e-mail/senha
criados no passo 4.

Para chamadas diretas à API (sem passar pelo proxy do nginx):
`http://localhost:8000`.

## 7. Rodar os testes de backend

O alvo oficial usa PostgreSQL real, aplica migrations e roda pytest em uma
imagem `test` separada. A imagem runtime continua sem pytest, dependências de
desenvolvimento ou arquivos de teste.

Use um nome de projeto distinto para manter banco e volumes descartáveis,
independentes do ambiente de desenvolvimento:

```bash
docker compose -p belo-vale-test --env-file infra/.env.local -f infra/docker-compose.yml \
  --profile test run --build --rm api-tests
```

O comando executa as validações contra PostgreSQL real, incluindo as
verificações declarativas de isolamento de `AUTH_SECRET` entre API e worker e
das regras de `.gitignore`. Nenhuma etapa copia arquivos ou instala
dependências manualmente dentro de um container runtime.

## 7.1. Importar a baseline legada

Move os 401 animais e as 152 medições do estado canônico legado para o
PostgreSQL. **Simula por padrão**: só grava com `--apply`.

O comando precisa de uma fazenda já existente. Para criar a primeira:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml   exec db psql -U ingestion -d ingestion   -tAc "INSERT INTO farms (name) VALUES ('Belo Vale II') RETURNING id"
```

Simulação — mostra exatamente o que aconteceria, sem escrever nada:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml   exec api uv run --no-sync python -m app.core.import_baseline   --state /app/state_canonical.json   --farm-id <uuid-da-fazenda>   --approved-by "seu.nome@fazenda"   --reference-date 2026-08-25
```

Conferido o relatório, repita com `--apply` para gravar.

Sobre `--reference-date`: é a data a partir da qual a lotação observada passa
a valer. A baseline não registra desde quando cada animal está em seu lote,
então essa data é **declarada pelo operador**, nunca inferida.

Garantias do importador, todas cobertas por teste:

- **valida antes de escrever** — se as contagens não baterem com 401/152, nada
  é gravado;
- **idempotente** — rodar de novo não duplica nada e reusa o mesmo registro de
  auditoria;
- **transacional** — falha no meio não deixa estado parcial;
- **auditável** — cada medição aponta para o `baseline_imports` que a originou,
  e esse registro guarda o SHA-256 do arquivo de origem;
- **não migra credenciais** — usuários legados não são sequer lidos.

Verificação após aplicar:

```sql
SELECT count(*) FROM animals WHERE farm_id = '<uuid>';                 -- 401
SELECT count(*) FROM animals WHERE farm_id = '<uuid>' AND brinco IS NOT NULL;  -- 259
SELECT measured_on, count(*) FROM official_measurements m
  JOIN animals a ON a.id = m.animal_id
 WHERE a.farm_id = '<uuid>' GROUP BY measured_on;  -- 2026-07-22: 107, 2026-08-25: 45
```

### Rollback

A importação não tem um comando de desfazer, por decisão: remover medições
oficiais é um ato deliberado. Para reverter uma importação inteira, apague na
ordem — dentro de uma transação — as medições, as lotações e os animais
daquele `baseline_imports`, e por fim o próprio registro:

```sql
BEGIN;
DELETE FROM official_measurements WHERE baseline_import_id = '<import-uuid>';
DELETE FROM animal_lot_assignments WHERE animal_id IN (
  SELECT id FROM animals WHERE farm_id = '<uuid>' AND legacy_id IS NOT NULL);
DELETE FROM animals WHERE farm_id = '<uuid>' AND legacy_id IS NOT NULL;
DELETE FROM baseline_imports WHERE id = '<import-uuid>';
COMMIT;
```

Confira os totais antes do `COMMIT`. Se o banco já tiver recebido medições de
OCR para esses animais, elas **não** têm `baseline_import_id` e por isso não
são atingidas pelo primeiro `DELETE` — mas o `DELETE FROM animals` falharia,
porque `official_measurements.animal_id` é `ON DELETE RESTRICT`. Isso é
proposital: um rollback só é automático enquanto a baseline for a única origem
daqueles animais.

## 8. Rodar os testes de frontend

```bash
cd apps/web
npm test              # Vitest — testes de unidade/componente
npx tsc --noEmit       # typecheck
npm run build          # build de produção real
```

## 9. Rodar o Playwright (E2E real)

Pré-requisito: ambiente Docker no ar (passos 1–5 já feitos, incluindo
usuário admin, fazenda e animal — o próprio teste garante isso de forma
idempotente via `docker compose exec`, então rodar mais de uma vez é seguro).

```bash
cd apps/web
npx playwright install chromium               # só na primeira vez
E2E_BASE_URL=http://localhost:8080 npx playwright test
```

O Playwright usa o compose real (`infra/docker-compose.yml` +
`infra/.env.e2e`, hardcoded em `e2e/seed.ts`) para popular usuário/fazenda/
animal via `docker compose exec`. Se você usa um arquivo de env diferente de
`infra/.env.e2e`, ajuste `ENV_FILE` em `apps/web/e2e/seed.ts`.

## 10. Derrubar o ambiente

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.yml down
```

Adicione `-v` para também apagar os volumes (`postgres_data`, `minio_data`)
— use com cautela, isso apaga todos os dados.

## Diagnóstico básico

| O que checar | Comando |
| --- | --- |
| API está de pé | `curl http://localhost:8000/healthz` (ou `http://localhost:8080/healthz` via proxy) |
| Web está servindo o SPA | `curl -I http://localhost:8080/` (deve retornar `200`) |
| Banco está aceitando conexões | `docker compose ... exec db pg_isready -U ingestion -d ingestion` |
| Fila/worker está processando | `docker compose ... logs worker --tail=50` — procure `Task ingestion.process_extraction_run[...] succeeded` |
| Логs da API | `docker compose ... logs api --tail=100` |
| Estado de uma importação específica | `GET /api/imports/{id}/review` com um token válido — o campo `status` reflete o `ExtractionRun` mais recente (pending/processing/extracted/failed), não fica travado em "queued" |

## Notas de rede (Docker)

`ingestion_private` é uma rede Docker `internal: true` — containers nela
(`db`, `redis`, `minio`, `worker`) não têm rota de saída para a internet nem
podem ser alcançados via porta publicada do host. `api` e `web` também
participam de uma segunda rede, `ingestion_edge` (não interna), que é o que
permite `8000:8000` e `8080:80` funcionarem a partir do host. Isso foi
confirmado empiricamente durante a Task 8 — antes dessa segunda rede
existir, a porta publicada da API nunca era alcançável de fora de um
container, apesar do `ports:` já estar declarado desde a Task 1.
