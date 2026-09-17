# Belo Vale II — Projeto completo

Plataforma de gestão do rebanho leiteiro da fazenda Belo Vale II, construída a partir da
planilha "PLANILHA DO UMAR PESAGEM DO LEITE.xlsx" e das fichas de controle diário fotografadas.

Artefato publicado (link vivo, atualizado automaticamente pela plataforma):
https://claude.ai/code/artifact/2f0720ab-cd19-48da-8344-a6ecdc86c81c

Login de acesso: e-mail `mbezerrajr@gmail.com` (Administrador). A credencial legada foi rotacionada e **não é versionada** — o estado canônico traz apenas o marcador `LEGADO-SEM-SEGURANCA`. Para abrir um artefato real, defina `BV_LEGACY_PASSWORD` no ambiente.

**ATENÇÃO — segurança:** este repositório contém os **dados reais do rebanho**
(401 animais, produção, custos). Trate como confidencial e mantenha o repositório
**privado**.

As credenciais legadas que ficavam em texto puro no estado e na documentação foram
**redigidas do HEAD** e substituídas pelo marcador `LEGADO-SEM-SEGURANCA`; o gate
`tools/credential_scan.py` impede a reintrodução. Duas ressalvas permanecem, por
decisão registrada:

- **O histórico Git não foi reescrito.** O valor entra no commit raiz, e reescrever
  invalidaria todos os SHAs e os PRs já mergeados. A mitigação correta é a rotação
  da credencial, que torna o valor histórico inofensivo — não a remoção do registro.
- **O login legado nunca foi segurança.** É um gate client-side: quem tem o link do
  artefato lê o código-fonte. A proteção real é o link ser privado.

---

## Baseline legada atual

A baseline da branch mais recente contém **401 animais**, **152 medições de leite**
(107 em `2026-07-22` e 45 em `2026-08-25`), 4 insumos e 2 usuários. A fonte versionada
é `belo-vale-ii-projeto-completo/plataforma/state_canonical.json`.

`platform_ATUAL_publicado.html` e `state_dados_atuais.json` são artefatos derivados.
Valide e regenere sempre pela CLI; não edite o JSON embutido manualmente:

```powershell
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py validate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py generate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json --template belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_template.html --published belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_publicado.html --projection belo-vale-ii-projeto-completo/plataforma/state_dados_atuais.json
```

O PostgreSQL da aplicação nova ainda **não** recebeu essa baseline; a migração continua
como etapa futura e deve preservar os identificadores e históricos validados aqui.

---

## Estrutura das pastas

### `plataforma/`
O código-fonte da aplicação (HTML + CSS + JS em arquivo único, sem build step).

- **`state_canonical.json`** — **fonte de verdade versionada da baseline legada.** Contém
  todos os históricos e é validada antes de qualquer geração.
- **`platform_ATUAL_template.html`** — template de código da versão atual. Contém
  o placeholder `__STATE_JSON__` no lugar dos dados. Arquitetura: um objeto `state`
  (vacas/insumos/usuários/preço do leite) guardado num `<script id="state-data"
  type="application/json">`, renderizado inteiramente via JS, e salvo de volta via
  `claude.use("artifact").publish()` — busca o próprio HTML servido, substitui o bloco de
  estado e republica. Sem backend, sem banco de dados externo.
- **`platform_ATUAL_publicado.html`** — o HTML final já com os dados injetados (o que foi
  de fato publicado no artefato acima, num dado momento — os dados no artefato ao vivo podem
  ter mudado desde então pelas edições feitas por quem usa a plataforma).
- **`state_dados_atuais.json`** — projeção derivada sem `vacas[*].historico`, útil para
  inspeção. **Não é fonte de verdade.** `state_inicial.json` é histórico.
- **`build_platform_state.py`** — valida a baseline e gera atomicamente o HTML publicado
  e a projeção. Estados estruturalmente inválidos não substituem os artefatos.
- **`v1_*.html`, `vacas_rows.html`, `insumos_rows.html`, `insumos_hist_rows.html`** —
  primeira versão da plataforma (arquitetura antiga de sincronização direta no DOM, sem
  login com múltiplos perfis, sem impressão). Mantida como histórico/referência.
- **`dashboard*.html`, `full*.html`** — versões anteriores, só do painel (dashboard), antes
  de virar plataforma com login e cadastros.
- **`gen_dashboard.py`** — script Python usado para gerar as versões antigas do dashboard.

Os comandos oficiais de validação e geração estão na seção "Baseline legada atual".

### `dados/`
Os dados do rebanho em diferentes estágios de processamento.

- **`cows_full_DADOS_ATUAIS.json`** — fonte histórica de julho/2026 com 272 vacas, cada uma com
  `id, nome, sit (VL/VS), lote, parto, av (produção do dia 22/07/2026), fase (estágio DEL),
  media_historica, n_medicoes, ultima_medicao`.
- **`cows_final.json`, `cows_with_avg.json`, `cows_compact.json`** — estágios intermediários
  do processamento (histórico do trabalho, não necessários para reconstruir a plataforma).
- **`agg_final.json`, `agg_lotes.json`** — agregações por lote usadas na construção dos
  primeiros dashboards.
- **`update_log.json`, `_inject.json`** — logs/artefatos intermediários da atualização da
  planilha a partir das fotos.

### `planilha/`
A planilha Excel original e suas versões corrigidas, mais a transcrição das fichas
fotografadas de controle de produção.

- **`pesagem_leite_USER_FINAL (arquivo real enviado pelo usuario).xlsx`** — **a versão mais
  correta e mais recente**, enviada diretamente pelo usuário no chat, com a aba LOTES
  reestruturada (coluna "Nº da Vaca" separada do nome, coluna **AV** = leitura consolidada
  de 22/07/2026).
- **`pesagem_leite_FINAL.xlsx`** — versão corrigida por mim a partir das fotos, com aba
  REVISAR (trilha de auditoria dos lançamentos ambíguos) e fórmulas de dependência
  (COUNTIF/SUMIF) estendidas para as linhas novas.
- **`pesagem_leite_ATUALIZADA.xlsx`, `pesagem_leite.xlsx`** — estágios intermediários da
  correção (atualização de insumos, fórmula D37).
- **`from_drive.xlsx`, `current_from_drive*.xlsx`** — cópias baixadas do Google Drive em
  diferentes momentos da conversa (mantidas para rastreabilidade — em alguns momentos o
  arquivo do Drive não refletia as edições que o usuário pensava ter feito).
- **`transcricao.py` / `transcricao.json`** — transcrição estruturada das 5 fotos de fichas
  de controle manuscritas (113 registros), com nível de confiança e notas de referência
  cruzada por registro.
- **`apply_update.py`** — script que aplica a transcrição à aba LOTES (80 linhas
  atualizadas, 23 inseridas, 10 mantidas para revisão manual) e estende as fórmulas
  dependentes.
- **`fotos_medicoes/`** — as 5 fotos originais das fichas de controle diário (lotes 1, 2 e 3)
  usadas na transcrição acima.

As vacas **PONTA CURTA** (nº 497) e **GIGANTE** (nº 633) já possuem leituras de
`2026-07-22` na baseline canônica. A ausência desses valores em planilhas históricas não
deve mais ser interpretada como ausência na plataforma atual.

### `testes/`
Testes Python de contrato/importação e regressões Playwright usados antes de cada
publicação — invariantes da baseline, idempotência do PDF, login, navegação, edição de campos, ciclo dos selos
(Lote/Situação/Status), seleção em massa, geração da área de impressão, modo escuro, etc.
Não fazem parte do produto final; documentam como cada mudança foi validada.

### `screenshots/`
Capturas de tela (headless) de várias etapas do desenvolvimento — dashboard, cadastro de
vacas, insumos, usuários, modo escuro, modal de impressão. Documentação visual do histórico,
não o estado atual necessariamente.

---

## Decisões técnicas relevantes

- **Sem backend.** A "persistência" é o próprio Artifact do Claude: o JS da página busca seu
  próprio HTML servido (`fetch(location.href)`), troca o bloco `<script id="state-data">`
  pelo novo JSON e republica via `claude.use("artifact").publish()`. Se o Claude não
  conceder essa capacidade (ex.: fora do ambiente Claude), a página cai para "somente
  neste navegador" — os dados ficam só na sessão local.
- **Login é uma cortina visual, não segurança real.** É um gate client-side (a lista de
  usuários/senhas fica no próprio HTML/JSON). A proteção de verdade é o link do artefato
  ser privado — quem tem o link vê o código-fonte e as senhas.
- **Impressão/PDF sem backend.** O ambiente do Artifact roda dentro de um iframe
  restrito que bloqueia silenciosamente `window.open()` e chamadas de script a
  `window.print()`. A solução: o conteúdo a imprimir é preparado numa área oculta da
  própria página, com CSS `@media print` isolando só essa área, e o usuário aciona a
  impressão manualmente via **Ctrl+P / Cmd+P** (atalho de teclado do navegador, que não
  passa pelo mesmo bloqueio de sandbox).
- **Dados reais, não fictícios.** Os 3 lotes (LOTE 1/2/3), os 4 insumos (Concentrado,
  Caroço, Silagem, Casca de Mandioca) com preços e dietas reais, e o preço do leite
  (R$ 2,59/L) vêm da planilha e das conversas — nada foi inventado como placeholder.
