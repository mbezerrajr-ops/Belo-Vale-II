# Modelo de domínio e migração da baseline legada

## Objetivo

Permitir que o PostgreSQL receba a baseline legada completa — 401 animais e 152
medições — sem falsificar proveniência, sem perder campos do cadastro histórico e
sem violar a regra de que o brinco é a única chave de identidade operacional.

Hoje isso é impossível: o schema atual não tem onde guardar brinco, exige uma
cadeia de revisão de OCR que nunca existiu para as medições históricas, e não
representa lote como informação temporal.

## O problema, medido

Verificado contra `state_canonical.json` e `apps/api/app/db/models.py` em `503cc5c`.

### 1. `animals` não tem onde guardar a identidade real

O índice é `UNIQUE (farm_id, identifier)` com `identifier NOT NULL`. Isso força uma
escolha impossível:

- `identifier` = brinco → os **141 animais sem brinco não entram**, porque a coluna
  é obrigatória;
- `identifier` = número legado → colide em **3 casos** (`346` PONTA FINA / PONTA
  FINA DO ABREU, `570` CAMBRAIA / MIMOSA, `''` MALHADINHA / SERRANA) e contradiz a
  regra de que o número não é identidade.

Além disso, dos 14 campos do cadastro legado, o schema recebe 2 (`identifier` e
`name`). Ficam de fora brinco, situação, status, último parto, lote, DEL, média,
peso, nascimento e a referência ao registro de origem.

### 2. Medições históricas não têm proveniência possível

`ck_official_measurements_active_review_provenance` exige que toda medição ativa
tenha `review_decision_id` e `reviewed_by`. E `review_decisions.extracted_line_id`
é `NOT NULL`, o que exige `extracted_lines` → `extraction_runs` → `imports` →
`image_assets`.

Migrar as 152 medições históricas por esse caminho exigiria fabricar upload, OCR e
revisão humana que nunca aconteceram. Isso é auditoria falsa e está descartado.

### 3. Lote não tem representação temporal

A vaca muda de lote. O schema não tem onde registrar vigência, origem nem revisor
de uma mudança de lote, e a medição não preserva o lote observado no momento.

## Decisão central: três identificadores distintos, não um

O erro que trava o schema é tentar usar uma única coluna como identidade. São três
papéis diferentes, e separá-los resolve todos os casos de borda:

| Identificador | Papel | Obrigatório? |
| --- | --- | --- |
| `id` (UUID) | Identidade interna do registro. Nunca muda, nunca é reaproveitada. | Sempre |
| `brinco` | Chave de **matching automático** de arquivos novos. | Não — nulo é válido |
| `legacy_id` | Chave de **migração e reconciliação** com a baseline legada. | Só para registros migrados |

Consequências diretas:

- **Todos os 401 animais migram**, inclusive os 141 sem brinco. Eles entram com
  `brinco = NULL` e `legacy_id` preenchido, preservando cadastro e histórico.
- **Um animal sem brinco nunca recebe matching automático.** A ausência de brinco
  não impede a migração; impede a associação automática de linhas de arquivos novos.
  São coisas diferentes, e o schema passa a expressar isso.
- **As 152 medições migram**, inclusive as 6 de animais sem brinco. A medição
  pertence ao animal (resolvido por `legacy_id` durante a migração), não ao brinco.

### Casos de borda resolvidos por essa separação

- **`B2-XXX` (SERRANA, 2 medições ativas)** — não é um brinco, é um placeholder
  ilegível. Migra com `brinco = NULL`, `legacy_id = 'v-b2-xxx-serrana'` e uma
  observação registrando o valor ilegível encontrado. O animal e as medições são
  preservados; o animal simplesmente não é elegível a matching automático até
  alguém vincular um brinco real.
- **`346` PONTA FINA / PONTA FINA DO ABREU** — ambos têm `brinco = NULL`. Migram
  como dois registros distintos com `legacy_id` distintos. Sem colisão, porque o
  número não é mais índice único.
- **`570` CAMBRAIA / MIMOSA** — CAMBRAIA tem `brinco = NULL`, MIMOSA tem
  `brinco = '1009'`. Migram separados, sem colisão.
- **`MALHADINHA` (sem número, sem brinco)** — migra por `legacy_id =
  'v-malhadinha'`, que já é estável na baseline.
- **`B2- 008` e `B1-016VD`** — normalizados na migração (ver abaixo), preservando
  o valor bruto original em `brinco_origem`.

## Normalização de brinco

Antes de qualquer índice único, o brinco passa por uma normalização canônica,
determinística e testável:

1. remover espaços nas pontas e colapsar espaços internos (`B2- 008` → `B2-008`);
2. caixa alta (`B2-abc` → `B2-ABC`);
3. string vazia após normalizar vira `NULL`.

A normalização **não** tenta corrigir o valor, inferir formato nem completar
dígitos. O valor bruto original é preservado em `brinco_origem` para auditoria, de
modo que nenhuma leitura se perde.

Além disso, marcadores de leitura ilegível (`XXX`, `???`, `---`, `B2-XXX`) viram
`NULL`: identificam a *ausência* de um brinco legível, não um brinco.

Verificado contra os 260 brincos reais da baseline:

| Resultado | Valor |
| --- | --- |
| Brincos válidos após normalizar | **259** |
| Único valor rejeitado | `B2-XXX` (SERRANA) → `NULL` |
| Único valor alterado | `B2- 008` → `B2-008` |
| **Colisões após normalizar** | **0** |

Zero colisões é o que torna `UNIQUE (farm_id, brinco)` seguro de aplicar.

## Schema proposto

Migrations **aditivas**. Nenhuma coluna existente é removida ou renomeada nesta
fase, e `identifier` permanece para não quebrar o pipeline de ingestão atual.

### `animals` — colunas novas

| Coluna | Tipo | Regra |
| --- | --- | --- |
| `brinco` | `varchar(64) NULL` | Normalizado. `UNIQUE (farm_id, brinco) WHERE brinco IS NOT NULL` |
| `brinco_origem` | `varchar(64) NULL` | Valor bruto como lido, sem normalizar |
| `legacy_id` | `varchar(64) NULL` | `UNIQUE (farm_id, legacy_id) WHERE legacy_id IS NOT NULL` |
| `numero_legado` | `varchar(64) NULL` | Informativo. **Sem índice único** — colide em 3 casos |
| `situacao` | `varchar(32) NULL` | Ex.: "Em lactação", "Seca" |
| `status` | `varchar(32) NULL` | Ex.: "Ativo" |
| `ultimo_parto` | `date NULL` | Base do cálculo de DEL |
| `nascimento` | `date NULL` | Vazio em toda a baseline; coluna existe para o futuro |
| `peso` | `numeric(6,2) NULL` | Vazio em toda a baseline |
| `observacoes` | `text NULL` | Onde fica o registro de brinco ilegível, por exemplo |

`DEL` **não é coluna**. É derivado de `ultimo_parto` e de uma data de referência,
conforme a regra já registrada. Persistir DEL congelaria um valor que muda todo dia.

### `animal_lot_assignments` — tabela nova

Histórico de lotação. Um lote novo não sobrescreve o anterior; encerra a vigência
do anterior e abre uma nova.

| Coluna | Tipo |
| --- | --- |
| `id` | `uuid PK` |
| `animal_id` | `uuid NOT NULL → animals.id` |
| `lote` | `varchar(64) NOT NULL` |
| `valid_from` | `date NOT NULL` |
| `valid_to` | `date NULL` (nulo = vigente) |
| `source` | `varchar(32) NOT NULL` — `legacy_baseline`, `import`, `manual` |
| `source_import_id` | `uuid NULL → imports.id` |
| `reviewed_by` | `varchar(255) NULL` |

Índice parcial `UNIQUE (animal_id) WHERE valid_to IS NULL`: no máximo uma lotação
vigente por animal. Lotes incompatíveis para a mesma data de referência viram
conflito manual, não sobrescrita.

O lote atual passa a ser **derivado** dessa tabela, não um campo solto.

### `official_measurements` — proveniência honesta

Duas colunas novas e um CHECK reescrito:

| Coluna | Tipo | Regra |
| --- | --- | --- |
| `provenance` | `varchar(32) NOT NULL DEFAULT 'ocr_review'` | `ocr_review` ou `legacy_baseline` |
| `baseline_import_id` | `uuid NULL → baseline_imports.id` | Obrigatório quando `provenance = 'legacy_baseline'` |
| `lote_observado` | `varchar(64) NULL` | Lote no momento da medição |

CHECK novo, substituindo o atual:

```sql
status <> 'active' OR (
  (provenance = 'ocr_review'
     AND review_decision_id IS NOT NULL
     AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)
  OR
  (provenance = 'legacy_baseline'
     AND baseline_import_id IS NOT NULL
     AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)
)
```

O rigor é mantido: **toda medição ativa continua obrigada a ter proveniência
rastreável e um responsável**. O que muda é que o sistema para de mentir sobre
qual foi a origem. Uma medição da baseline declara que veio da baseline.

### `baseline_imports` — tabela nova

Registra a importação administrativa da baseline como um evento auditável de
primeira classe.

| Coluna | Tipo |
| --- | --- |
| `id` | `uuid PK` |
| `farm_id` | `uuid NOT NULL → farms.id` |
| `source_path` | `varchar(512) NOT NULL` — ex.: `plataforma/state_canonical.json` |
| `source_sha256` | `char(64) NOT NULL` — hash do arquivo migrado |
| `animal_count` | `integer NOT NULL` |
| `measurement_count` | `integer NOT NULL` |
| `approved_by` | `varchar(255) NOT NULL` — quem autorizou a importação |
| `approved_at` | `timestamptz NOT NULL` |
| `notes` | `text NULL` |

O `source_sha256` é o que torna a migração verificável: dá para provar depois
exatamente qual versão do arquivo originou cada medição.

## Monofazenda

Decidido pelo titular em 18/09/2026: existe uma única fazenda.

- `farm_id` permanece em todas as tabelas, para que multifazenda seja adicionável
  depois sem reescrever o schema;
- a API **não aceita `farm_id` arbitrário do cliente** — resolve a fazenda única no
  servidor;
- `user_farms`, escopo de papel por fazenda e RLS ficam **fora** desta fase;
- os índices únicos já são por `(farm_id, ...)`, então servem aos dois cenários.

## Critérios de aceite

A fase só está concluída quando, com evidência fresca:

1. A migration aplica e reverte (`upgrade` e `downgrade`) sem perda **em banco
   sem dados de baseline**. Com medições `legacy_baseline` presentes, o
   `downgrade` falha deliberadamente com mensagem acionável, em vez de destruir
   ou falsificar as linhas que o schema anterior não sabe representar.
2. A migration é aditiva: nenhuma coluna existente removida ou renomeada.
3. O pipeline de ingestão atual continua verde — a suíte de `apps/api/tests`.
4. A normalização de brinco é determinística e coberta por teste, incluindo
   `B2- 008`, `B1-016VD` e vazio → `NULL`.
5. `UNIQUE (farm_id, brinco) WHERE brinco IS NOT NULL` aceita múltiplos nulos e
   rejeita brinco repetido.
6. `UNIQUE (animal_id) WHERE valid_to IS NULL` rejeita duas lotações vigentes.
7. O CHECK de proveniência rejeita medição ativa `legacy_baseline` sem
   `baseline_import_id`, e rejeita `ocr_review` sem `review_decision_id`.

## Fora desta fase

- O importador da baseline em si (dry-run, idempotência, rollback, relatório de
  diferenças) — é o PR seguinte, e merece revisão isolada.
- Remover o fallback por nome de `animal_matching.py` e do importador legado —
  Fase 6.
- CRUD de cadastro mestre — Fase 5.
- OAuth, OCR real, CI — Fases 7 a 9.
- Limpeza do entulho do legado (HTMLs e JSONs órfãos) — tarefa própria, sem
  relação com o schema.

## Riscos

- **Migration aditiva num banco com dados de ingestão.** Mitigado por: nenhuma
  coluna removida, `provenance` com default `ocr_review` (preservando o
  comportamento atual de tudo que já existe), e `downgrade` testado.
- **O CHECK reescrito é mais permissivo que o anterior.** Mitigado por teste
  explícito de que `legacy_baseline` sem `baseline_import_id` continua rejeitado —
  a permissividade é apenas para a origem legítima da baseline.
- **`numero_legado` sem índice único** pode sugerir que número identifica animal.
  Mitigado por documentação na própria coluna e por não existir nenhum caminho de
  código que faça busca por ele.
