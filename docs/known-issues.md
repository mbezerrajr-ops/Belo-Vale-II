# Dívida técnica e lacunas conhecidas

Registradas explicitamente para não ficarem escondidas. As pendências do legado não
bloqueiam sua validação ou geração, mas devem ser resolvidas antes de declarar a migração
para PostgreSQL como reconciliada.

## Contenção de credenciais legadas (Fase 1)

A credencial de login legada estava em texto puro em 23 arquivos versionados
(25 ocorrências) e foi **redigida do HEAD**, substituída pelo marcador
`LEGADO-SEM-SEGURANCA`. O gate `tools/credential_scan.py` impede a reintrodução
(`python -m unittest test_credential_scan` dentro de `tools/`).

O campo `senha` foi preservado em vez de removido porque
`apps/web/e2e/legacy-platform.spec.ts` lê a credencial do próprio estado canônico
para fazer login, e o HTML publicado compara contra o mesmo estado embutido.
Os scripts Playwright históricos passam a ler `BV_LEGACY_PASSWORD` do ambiente.

### Pendente fora do repositório — só o titular pode executar

Redigir o HEAD **não reduz o risco por si só**. O valor continua conhecido por
quem já clonou, permanece no histórico Git e foi documentado publicamente no
README anterior. As ações que efetivamente contêm o incidente:

1. **Rotacionar a senha em todo serviço onde tenha sido reutilizada.** A
   reutilização é o vetor mais grave, porque o valor era legível e curto.
2. **Rotacionar a credencial do segundo usuário legado**, de domínio externo —
   os dois usuários compartilhavam o mesmo valor, então a rotação envolve um
   terceiro e uma comunicação, não apenas uma alteração de dado.
3. **Restringir ou desativar o Artifact antigo.** O link privado do artefato é a
   exposição primária: quem o abre lê o código-fonte e o estado embutido.
4. **Revisar quem tem acesso** ao repositório, a clones locais e a backups.

### Histórico Git — decisão registrada, não reescrito

A string entra no **commit raiz** (`c980db2`), num repositório de 44 commits.
Reescrever invalidaria todos os SHAs e os dois PRs já mergeados, exigindo reclone
de todos os colaboradores — e **não removeria o conhecimento** do valor, apenas o
registro. Como os colaboradores já o conheciam, a rotação é a mitigação que
realmente resolve.

Reavaliar a reescrita apenas se o repositório for tornar-se público ou se a
rotação não for viável. Nesse caso, exige plano próprio com backup, janela de
reclone e comunicação aos colaboradores — nunca `filter-repo` ou force-push sem
autorização explícita.

## Reconciliação da baseline legada

A baseline canônica validada possui 401 animais e 152 medições. O relatório operacional
completo está em
`belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais_ultimo_relatorio.txt`.
O relatório de reconciliação (`docs/reports/conflitos-reconciliacao-manual.pdf`, versão
1.2) formaliza o brinco como única chave de identidade operacional: nome é descrição,
não identificador, e não é usado para localizar, casar ou fundir animais. Sob essa regra,
das quatro categorias encontradas, apenas uma exige decisão humana antes da migração.

### Pendência real: 30 animais com brinco, situação "Em lactação" e DEL vazio

São avisos de qualidade de dado genuínos — o DEL não pôde ser calculado por falta de
data de último parto compatível. Resolver exige confirmar o último parto ou corrigir a
situação com evidência; nunca inventar ou zerar o DEL apenas para eliminar o alerta.

### Não são pendências — apenas preservados ou registrados como observação

- **141 animais legados** não aparecem no PDF mais recente. O brinco já resolveu a
  correspondência: a ausência significa apenas que esse arquivo não trouxe uma leitura
  nova para esses animais, nunca remoção, venda, óbito, descarte ou produção zero. Todos
  foram preservados, sem alteração ou exclusão automática, e não exigem classificação.
- **13 divergências de nome** entre PDF e base — o brinco já confirmou a identidade;
  o nome do PDF apenas difere do nome cadastrado: 432 Carolina/KAROLINA; 434 FAISCA DO
  ABREU/FAÍSCA; 448 MEIAS BRANCAS/MEIAS BRANCA; 701 Pequena/PIQUENA; 733 Crauna/Pauna;
  779 GESSICA/GÉSSIKA; 967 MALHADA/Machada; 981 CONDESA/Condessa; 1008
  DENGOSA/CABELO DE FOGO; 1013 CODORNA/Boemia; B1-263 ESPERANÇA II ABREU/ESPERANÇA;
  B2-512 Asa Negra/AZA NEGRA; B2-523 BARONESA/BARONEZA. O nome da base foi mantido; uma
  eventual atualização de nome é uma ação cadastral separada e auditada, nunca
  automática, e não bloqueia a migração.
- **27 pares candidatos por nome normalizado** entre registros legados e registros com
  brinco do relatório. Nome igual ou parecido não é evidência de duplicidade: os
  registros têm brincos diferentes (ou nenhum brinco) e por isso permanecem separados.
  Não são equivalências confirmadas e não foram fundidos:

| Legado | Registro do relatório |
| --- | --- |
| 125 MARINGÁ | B2-687 Maringa |
| 205 REVISTA | 827 Revista |
| 604 CARINHOSA | 832 Carinhosa |
| 157 CIGANA | 821 Cigana |
| 474 SURUBIM | 846 Surubim |
| 440 ARIZONA | 1001 Arizona |
| 19 BOLINHA | 956 Bolinha |
| 626 BOLINHA | 956 Bolinha |
| 143 BURGUESA | B2-662 BURGUESA |
| 155 CARINA | B2-658 CARINA |
| 147 CARRAPETA | B2-664 CARRAPETA |
| 46 ESMERALDA | 812 Esmeralda |
| 78 ESPERANÇA | B1-263 ESPERANÇA |
| 009 VERMELHO FAÍSCA | 434 FAÍSCA |
| 220 JARDINEIRA | 1015 Jardineira |
| 702 MAÇA | B2-663 MAÇA |
| 686 MEDALHA | 879 Medalha |
| 635 NEBLINA | 767 NEBLINA |
| 96 PALOMA | B2-584 PALOMA |
| 10 TIETA | 964 Tieta |
| 498 Meias Branca | 448 MEIAS BRANCA |
| 682 Rainha | B2-680 RAINHA |
| 141 Fumaca | 441 FUMAÇA |
| 519 Branquinha | B2-549 BRANQUINHA |
| 133 Bruna | 433 BRUNA |
| 862 Saia Branca | 861 SAIA BRANCA |
| 508 Princesa | B2-548 PRINCESA |

O caso BOLINHA ilustra por que nome não identifica: dois registros legados apontam pelo
nome para o mesmo registro 956. Os três permanecem separados; uma eventual fusão exigiria
brinco e outra evidência independente, nunca similaridade de nome — e essa investigação
não bloqueia a migração. PONTA CURTA (497) e GIGANTE (633) não fazem mais parte das
pendências de produção: ambas têm leitura em `2026-07-22` no estado canônico.

## Achados de integridade da baseline (verificados em 2026-09-17)

Verificados programaticamente contra `state_canonical.json` no HEAD. Condicionam o
modelo de identidade (Fase 3) e a migração (Fase 4); nenhum deles autoriza alteração
automática de dado.

- **Os 141 sem correspondência no relatório são exatamente os 141 sem brinco.** Os
  dois conjuntos foram comparados registro a registro e são idênticos. Ausência no
  relatório significa **apenas** ausência de brinco — não remoção, venda, morte,
  descarte nem produção zero.
- **`B2-XXX` não é um brinco.** É um placeholder ilegível usado como identidade de
  SERRANA, que tem **2 medições ativas** (2026-07-22 e 2026-08-25). Sob a regra do
  brinco como única identidade, esse registro não tem identidade operacional válida e
  precisa de decisão humana antes da migração.
- **Brincos exigem normalização canônica antes de qualquer índice único:** `B2- 008`
  tem espaço interno e `B1-016VD` mistura formatos.
- **6 animais sem brinco possuem 6 das 152 medições** (BAIANA, MULATA, SEREIA, Meias
  Branca, Branquinha, Saia Branca). A migração precisa de regra explícita: são
  medições legítimas cujo animal não tem identidade operacional.
- **Os 141 brincos ausentes são `null`, não string vazia.** O contrato e o schema
  precisam distinguir os dois casos.
- **Dos 260 brincos, 81 vêm do PDF** (formato `B*`) e **179 são numéricos**, dos quais
  174 idênticos ao `numero` legado. Confirmado pelo titular em 2026-09-17 que **são
  brincos físicos reais**, e portanto identidade operacional válida.
- **Números legados duplicados:** `346` (PONTA FINA / PONTA FINA DO ABREU), `570`
  (CAMBRAIA / MIMOSA) e `''` (MALHADINHA / SERRANA). Em todos, ao menos um lado tem
  brinco nulo — o conflito é do `identifier` numérico do schema atual, não do brinco.
- **O matching por nome existe em dois lugares, não um.** Além do fallback em
  `apps/api/app/services/animal_matching.py`, o importador legado faz matching
  **primário** por nome em `import_relatorio_animais.py` (`by_name` antes de
  `by_number`). A Fase 6 precisa tratar os dois.

## Scripts Playwright históricos não são uma suíte `unittest`

Nove arquivos antigos em `belo-vale-ii-projeto-completo/testes/` usam prefixo `test_`,
executam `asyncio.run(main())` durante o import e fixam o navegador em
`/opt/pw-browsers/chromium`. Por isso, uma descoberta ampla com
`python -m unittest discover -p "test_*.py"` tenta executar esses scripts e falha fora do
antigo ambiente Linux. Eles foram preservados como histórico; não são o gate desta
baseline. Use os dois comandos de módulos explícitos documentados no runbook e o teste
Playwright TypeScript `apps/web/e2e/legacy-platform.spec.ts`.

## npm audit — esbuild (dependência de desenvolvimento)

- **Dependência:** `esbuild` (via `vite`/`vitest`/`vite-node`/`@vitest/mocker`,
  todas dependências de desenvolvimento do frontend).
- **Advisory:** [GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99)
  — o servidor de desenvolvimento do esbuild aceita requisições de qualquer
  origem e devolve a resposta.
- **Escopo:** exclusivamente o servidor de desenvolvimento local (`vite dev`
  / `npm run dev`). Não afeta o bundle de produção gerado por `npm run
  build` nem a imagem Docker do serviço `web` (que só serve arquivos
  estáticos via nginx, sem o servidor de dev do Vite).
- **Impacto:** um site malicioso aberto no mesmo navegador enquanto alguém
  roda `npm run dev` localmente poderia, em teoria, ler respostas do
  servidor de dev. Não há exposição em produção nem em CI (que roda `npm
  run build`, não `npm run dev`).
- **Mitigação atual:** nenhuma ação além de não expor o servidor de dev em
  rede não confiável (comportamento padrão — ele só escuta em localhost).
- **Upgrade necessário para resolver:** `vite@8` (major, breaking change),
  que arrasta `vitest`/`@vitest/mocker`/`vite-node` juntos.
- **Prioridade:** baixa. Deliberadamente não aplicado nesta task para não
  trocar a stack de build/teste no meio de uma integração — ver instrução
  explícita da Task 8 de não fazer upgrade major só para zerar o audit.

## Duas seções "Fazenda" na tela principal — resolvido

O upload e o dashboard pediam, cada um, o UUID da fazenda digitado à mão.
A fazenda agora vem de `GET /api/farms/current`, resolvida no servidor, e
nenhuma tela pede isso ao usuário.

## `HttpVisionProvider` sem integração externa real comprovada

Ver `docs/vision-provider-status.md` para a classificação completa.
Estruturalmente revisado e testado (construção de requisição, ausência de
credenciais no frontend, timeout, parsing do formato esperado); nunca
executado contra um provedor de visão/OCR real, por não haver credencial
disponível ou autorizada neste ambiente.

## CI — resolvido, com um limite

`.github/workflows/ci.yml` roda em todo push e PR: varredura de credenciais,
contrato da baseline, suíte do backend contra PostgreSQL e Redis reais (com
ida e volta da migration mais recente), vitest, tipos e build do frontend.

Fica de fora o Playwright E2E, que precisa do Docker Compose inteiro (API,
worker, MinIO, nginx). Continua sendo rodado à mão, conforme o runbook.

## Segurança para exposição pública: o que falta

A aplicação será acessada pelo celular via internet pública, por dono e
funcionários. Já estão atendidos: política de senha, limite de tentativas de
login, gestão de contas com RBAC, sessão renovável em cookie `HttpOnly` e os
cabeçalhos de segurança do navegador. Continuam em aberto, e **todos importam
antes de expor a aplicação**:

- **HTTPS não é obrigatório em lugar nenhum.** Sem TLS, senha e token viajam
  em texto puro. Precisa de certificado, redirecionamento e HSTS. Fica para a
  fase de deploy, que só será planejada com a estruturação completa.

Resolvidos nesta etapa:

- **Limite de login no Redis.** Compartilhado entre réplicas e preservado
  quando a API reinicia. Com o Redis fora do ar, o limite continua valendo na
  memória do processo (nem tranca a fazenda, nem libera força bruta).
- **Redefinição de senha pelo administrador**, com senha provisória que
  expira em 72 h e só serve para escolher outra. Não há recuperação por
  e-mail: exigiria um provedor de envio, e a fazenda tem sempre um
  administrador por perto.

Decisão pendente, registrada para não passar despercebida: a conta criada
pelo administrador já nasce com a senha que ele digitou, sem troca
obrigatória no primeiro acesso. É o mesmo risco que a redefinição trata (uma
senha que passou por mais de uma mão). Aplicar a troca obrigatória também na
criação é uma linha no endpoint, mas muda o fluxo do dono e ficou para ele
decidir.

## Uso diário — decisões registradas

- **Lançamento manual de produção** usa a proveniência `manual_entry`. O
  trigger do banco exige que o responsável gravado seja uma conta existente,
  com o mesmo rigor da revisão de OCR e da baseline.
- **Teto de 80 L por vaca por dia** no lançamento. Acima disso é quase certo
  erro de digitação (a maior produção da baseline é 37,5 L). Zero é aceito:
  leite descartado em tratamento.
- **"Hoje" é o dia da fazenda** (UTC−3 fixo, `app/core/farm_clock.py`), não o
  do servidor. Datas futuras são recusadas no lançamento e na baixa.
- **Desfazer baixa não reabre lote.** Reabrir sozinho afirmaria uma lotação
  que ninguém confirmou; o animal volta sem lote e quem desfaz decide onde
  ele está.
- **Painel e folha de coleta ignoram animais com baixa.** A produção que eles
  deram antes da saída continua no banco e na série histórica.

## Cadastro mestre — resolvido

API e telas existem: buscar animal, ver ficha, vincular brinco, mudar de lote,
cadastrar animal e gerenciar contas. Ver a seção 5 do runbook.
