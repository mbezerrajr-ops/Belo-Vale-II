# Belo Vale II — Projeto completo

Plataforma de gestão do rebanho leiteiro da fazenda Belo Vale II, construída a partir da
planilha "PLANILHA DO UMAR PESAGEM DO LEITE.xlsx" e das fichas de controle diário fotografadas.

Artefato publicado (link vivo, atualizado automaticamente pela plataforma):
https://claude.ai/code/artifact/2f0720ab-cd19-48da-8344-a6ecdc86c81c

Login de acesso: e-mail `mbezerrajr@gmail.com`, senha `belovale2026` (Administrador).

**ATENÇÃO — segurança:** este ZIP contém, em texto puro, as credenciais de login da
plataforma (aba Usuários) e os dados reais do rebanho (401 animais, produção, custos).
Trate como confidencial. Se for subir para o GitHub, use um repositório **privado**.

---

## Estrutura das pastas

### `plataforma/`
O código-fonte da aplicação (HTML + CSS + JS em arquivo único, sem build step).

- **`platform_ATUAL_template.html`** — **fonte da versão atual em produção.** Template com
  o placeholder `__STATE_JSON__` no lugar dos dados. Arquitetura: um objeto `state`
  (vacas/insumos/usuários/preço do leite) guardado num `<script id="state-data"
  type="application/json">`, renderizado inteiramente via JS, e salvo de volta via
  `claude.use("artifact").publish()` — busca o próprio HTML servido, substitui o bloco de
  estado e republica. Sem backend, sem banco de dados externo.
- **`platform_ATUAL_publicado.html`** — o HTML final já com os dados injetados (o que foi
  de fato publicado no artefato acima, num dado momento — os dados no artefato ao vivo podem
  ter mudado desde então pelas edições feitas por quem usa a plataforma).
- **`state_dados_atuais.json`** / **`state_inicial.json`** — o objeto de estado
  (vacas/insumos/usuários) em JSON puro, para inspecionar ou reprocessar os dados sem abrir o HTML.
- **`v1_*.html`, `vacas_rows.html`, `insumos_rows.html`, `insumos_hist_rows.html`** —
  primeira versão da plataforma (arquitetura antiga de sincronização direta no DOM, sem
  login com múltiplos perfis, sem impressão). Mantida como histórico/referência.
- **`dashboard*.html`, `full*.html`** — versões anteriores, só do painel (dashboard), antes
  de virar plataforma com login e cadastros.
- **`gen_dashboard.py`** — script Python usado para gerar as versões antigas do dashboard.
- **`import_relatorio_animais.py`** — importa o PDF "RELATÓRIO DE TODOS ANIMAIS"
  (`docs/`) para dentro do estado: atualiza **Lote**, **Data do último parto** e **DEL** das
  vacas já cadastradas, cadastra as que faltam e preserva o histórico de medições de leite.
  Roda sem argumento extra para simular; com `--write` grava. Gera
  `import_relatorio_animais_ultimo_relatorio.txt` com tudo que mudou, o que não casou e o
  que ficou ambíguo. Rodar duas vezes seguidas não duplica nada.
- **`vendor/`** — pdf.js e SheetJS servidos junto com a plataforma (o Artifact bloqueia CDN
  externo). Ver `vendor/README.md`.

Para gerar um novo `platform_ATUAL_publicado.html` a partir do template com dados
atualizados: substituir a string `__STATE_JSON__` em `platform_ATUAL_template.html` pelo
JSON do estado desejado (ver os scripts de build usados nas pastas `testes/` como exemplo).

### `dados/`
Os dados do rebanho em diferentes estágios de processamento.

> Estes arquivos refletem o rebanho de julho/2026 (272 vacas). A base viva — 401 animais,
> com DEL e os lotes de manejo — está em `plataforma/state_dados_atuais.json` e no bloco
> `state-data` de `plataforma/platform_ATUAL_publicado.html`.

- **`cows_full_DADOS_ATUAIS.json`** — **fonte de dados definitiva.** 272 vacas, cada uma com
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

**Pendência conhecida:** as vacas "PONTA CURTA" (nº 497) e "GIGANTE" (nº 633) foram
resolvidas manualmente na aba REVISAR, mas o valor de produção do dia 22/07 delas nunca foi
propagado para a coluna AV — vale conferir com quem fez a medição original.

### `testes/`
Scripts Python (Playwright + Chromium headless) usados para testar a plataforma antes de
cada publicação — login, navegação entre abas, edição de campos, ciclo dos selos
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
- **Lote é o grupo de manejo, mas só 1/2/3 têm dieta.** Além de LOTE 1/2/3, o campo `lote`
  aceita os grupos do relatório da fazenda (PRÉ-PARTO, PIQUETES / REPASSE, ENGORDA,
  ENGENHO, INSERLEITE, BEZERREIRO, CAJARANAS, PALMA, COLÉGIO, ABREU). Custo/dia, dieta e os
  gráficos financeiros continuam calculados só sobre `LOTES_DIETA` (os lotes 1/2/3, os
  únicos com dieta cadastrada); produção por lote e a tabela por lote mostram todos os
  grupos que têm animais. Com 13 valores, o selo de ciclo do lote virou um `select`.
- **DEL é derivado, não digitado.** O campo `del` (dias em lactação) guarda o valor do
  relatório, mas é recalculado como `hoje − parto` a cada abertura da página e a cada
  mudança da data de parto — então não envelhece. Fica vazio para animal sem DEL no
  relatório (seco, pré-parto, piquete, recria).
- **Dados reais, não fictícios.** Os 3 lotes (LOTE 1/2/3), os 4 insumos (Concentrado,
  Caroço, Silagem, Casca de Mandioca) com preços e dietas reais, e o preço do leite
  (R$ 2,59/L) vêm da planilha e das conversas — nada foi inventado como placeholder.
