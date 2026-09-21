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

### Resolvido: 30 animais com brinco, situação "Em lactação" e DEL vazio

Reavaliado em 2026-09-18: não é pendência no sistema novo. As 30 têm data de
último parto preenchida; vazio está só o campo DEL digitado à mão no legado. O
sistema novo calcula os dias em lactação a partir da data do parto, e as 132
vacas em lactação com brinco têm essa data no banco. O aviso continua saindo
na validação do estado canônico, porque ele confere o campo do legado — é
esperado.

### Coleta de 25/08/2026 será substituída

O titular vai enviar os dados de 25/08 normalizados. Decisão: nada foi apagado
nem anulado; os dados novos entram pela importação de arquivo, modo
"substituir", e as leituras antigas ficam como `superseded`, com motivo.

MULATA e SERRANA têm leitura em 25/08 e **não têm brinco**. Nenhum arquivo as
alcança, então a leitura delas de 25/08 permanece a da baseline mesmo depois
da substituição. Para trocá-la, é preciso vincular o brinco (ficha do animal)
antes de importar, ou corrigir a leitura à mão.

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

## Área "Fichas" escondida sem OCR real

O provedor de OCR padrão é falso: devolve sempre o mesmo animal e data.
Deixar a área "Fichas" visível faria uma leitura inventada chegar à revisão
parecendo verdadeira. A área só aparece com `VISION_PROVIDER=http` ou com
`PHOTO_SHEETS_DEMO=true` (demonstração e E2E), e a API se recusa a subir em
produção com o modo de demonstração ligado. O código do fluxo continua
inteiro e coberto pelo E2E.

## `HttpVisionProvider` sem integração externa real comprovada

Ver `docs/vision-provider-status.md` para a classificação completa.
Estruturalmente revisado e testado (construção de requisição, ausência de
credenciais no frontend, timeout, parsing do formato esperado); nunca
executado contra um provedor de visão/OCR real, por não haver credencial
disponível ou autorizada neste ambiente.

## CI — resolvido

`.github/workflows/ci.yml` roda em todo push e PR: varredura de credenciais,
contrato da baseline, suíte do backend contra PostgreSQL e Redis reais (com
ida e volta da migration mais recente), vitest, tipos e build do frontend, e
o Playwright E2E contra a pilha Docker inteira (API, worker, MinIO, nginx),
com segredos gerados no próprio runner.

O E2E entrou no CI porque, fora dele, apodreceu: de 27/08 a 18/09 ninguém o
rodou, e ele deixou de funcionar por quatro motivos diferentes (seed sem
brinco, senha fora da política, tela antiga, `.env.e2e` inexistente).

## Imagem da MinIO fora do Docker Hub

A MinIO deixou de publicar as imagens gratuitas no Docker Hub; o compose não
subia em máquina que ainda não tivesse a imagem em cache. A imagem passou a
vir do espelho oficial `quay.io/minio/minio`, mesma versão de antes, fixada
por digest. É um remendo: para produção, o armazenamento de arquivos deve ir
para um serviço gerenciado compatível com S3 (decisão da fase de deploy).

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

Decidido pelo titular em 2026-09-18: a conta criada pelo administrador
também troca a senha no primeiro acesso (a senha digitada por ele passou por
duas mãos). A senha inicial não expira sozinha — demorar a entrar não é
motivo para travar a conta.

## Importação de coleta por arquivo — decisões registradas

Decididas pelo titular em 2026-09-18:

- **A primeira coluna é o brinco.** O "Número" dos arquivos do sistema antigo
  é o brinco. A associação é só por ele; nome diferente do cadastro vira aviso
  na prévia. O legado removia tudo que não fosse dígito dessa coluna, o que
  transformava `B2-647` em `2647` — por isso as vacas `B*` nunca casavam.
- **Substituir não apaga ausências.** No modo "substituir", leitura com valor
  diferente é substituída; a vaca que já tinha leitura na data e não está no
  arquivo mantém a leitura antiga.
- **Quem importa.** "Só leituras novas" é de qualquer conta; "substituir" é de
  revisor ou administrador, com motivo.

Decisões de implementação:

- **Zero à esquerda não é adivinhado.** `026` e `26` continuam brincos
  diferentes (`app/services/brinco.py`). Quando uma planilha guarda o brinco
  como número e apaga o zero, a linha fica sem associação e a prévia avisa
  que existe o brinco com zero, pedindo a coluna formatada como texto.
- **Brinco repetido com valores diferentes** no mesmo arquivo não entra:
  escolher uma das linhas seria adivinhar qual está certa.
- **PDF só com texto.** PDF digitalizado (foto) é recusado com mensagem; não
  há OCR real.
- **O arquivo fica guardado** em `production_imports`, imutável, com hash,
  modo, motivo e quem enviou. Reenviar o mesmo arquivo na mesma data e modo
  não duplica nada.
- **Limites:** 5 MB, 50 MB descompactado para XLSX, 50 páginas de PDF, 5000
  linhas. XML de planilha só é lido com `defusedxml`; fórmulas nunca são
  executadas.

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

## Leitor do formulário impresso — decisões registradas (20/09/2026)

- **"→ DOENTE" vira observação** na ficha, por enquanto (decisão do titular).
- **"→ 2º LOT"** (abreviado) é troca de lote; **"→ SECA"** é ordem de secagem,
  como "SECAR" na folha manuscrita.
- **Tiques ao lado do total** ("1", "/", "✓") não são anotação.
- **Sem dica de data na instrução.** "Hoje é ..." fez o modelo escrever a
  data de hoje no formulário de 22/07/26. A data vem só da folha; errada, o
  revisor troca a do arquivo inteiro.
- **Nome divergente oferece a vaca do nome lido.** Quando o brinco lido é de
  uma vaca e o nome de outra (brinco da margem deslocado uma linha), a
  associação continua pelo brinco, com alerta, e a vaca do nome aparece em
  "Ou é esta", a um toque. Nada é trocado sozinho.

## Nomes repetidos no cadastro: o que é duplicata e o que não é

26 nomes aparecem em duas (ou mais) fichas, uma com brinco e outra sem. A
planilha conferida de 25/08/2026 desempatou (ver `docs/Treinamento-VC/`, fora
do Git):

- **Na maioria são vacas diferentes com o mesmo nome.** Em 15 casos o número
  da planilha é o brinco da ficha que tem brinco, e a outra ficha está seca ou
  sem nenhuma medição (NEBLINA 767 × nº antigo 635, SURUBIM 846 × 474,
  TIETA 964 × 10, MAÇA 663 × 702...). Nada a fazer.
- **Duplicata de verdade** quando as duas fichas têm o mesmo nome e números
  parecidos, e a medição caiu na ficha sem brinco porque o número escrito na
  folha bateu com o "número antigo" da outra ficha:
  - SAIA BRANCA (861 × 862) e MEIAS BRANCA (448 × 498): **resolvido** em
    20/09/2026 — a produção de 22/07 foi anulada com motivo na ficha errada e
    lançada na vaca certa (`measurement_voided` + `manual_entry` em
    `audit_events`). A ficha duplicada continua no cadastro, vazia.
  - **BRANQUINHA: resolvido** em 20/09/2026, por decisão do titular. A folha
    de 25/08 traz "649 BRANQUINHA" no 2º lote **e** "649 REDONDA" no 3º — o
    mesmo número para duas vacas, no mesmo dia (a planilha copiou a folha
    fielmente; o conflito é da anotação). O titular confirmou que o 649 é da
    BRANQUINHA. Aplicado, nesta ordem: o 649 foi **tirado** da REDONDA (que
    fica sem brinco até ser conferida no curral, com a produção dela
    preservada), passou para a BRANQUINHA (antes B2-549), e os 21,5 L de
    22/07 saíram da ficha duplicada sem brinco (nº antigo 519) para ela.
    **Pendente:** ler no curral o brinco da REDONDA.
- **Dígito ambíguo, não ficha duplicada:** o número escrito difere do brinco
  por um dígito (ARIZONA 1901 × 1001, BRUNA 473 × 433, FUMAÇA 491 × 441,
  PRINCESA 518 × 548). É a letra de quem anota.

Isto responde, com evidência independente, parte dos "27 pares candidatos por
nome normalizado" registrados acima na reconciliação da baseline: lá eles
ficaram separados por falta de prova; a planilha conferida de 25/08 é essa
prova para SAIA BRANCA e MEIAS BRANCA.

Números repetidos na própria folha não são raros: só em 25/08 apareceram
cinco (016 em BORBOLETA e BELMONTE, 544 em XENA e PITUDA, 649 em BRANQUINHA e
REDONDA, 652 em ASA BRANCA duas vezes, 732 em PRAUNA e PACIÊNCIA). Por isso o
brinco lido nunca associa sozinho quando o nome desmente.

Ainda falta um jeito de juntar duas fichas no sistema (histórico e auditoria);
hoje a correção é anular e relançar, uma medição por vez.

## Revisão por arquivo — decisões registradas

- **Filtro por arquivo** na caixa de Revisão, pedido do titular (19/09/2026).
- **Data do arquivo inteiro de uma vez.** A fonte lida continua imutável; a
  migração `0011` acrescenta só `corrected_reference_date`, quem corrigiu e
  quando, e o trigger aceita mudança apenas nessas colunas (a correção não
  pode ser apagada). As pendentes são normalizadas de novo a partir do que
  foi lido (`raw_fields`) com a nova data; os alertas sobre o animal (brinco,
  nome) ficam como estavam. Cada proposta muda de versão: quem estava com o
  cartão aberto recarrega antes de aprovar. Fica em `audit_events`
  (`source_date_corrected`).

## Resolvido: "hoje" saía do fuso do aparelho, não do da fazenda

O servidor recusa coleta e baixa com data no futuro comparando com o dia da
fazenda (UTC−3 fixo, `app/core/farm_clock.py`). As telas, porém, montavam o
"hoje" com os campos locais do navegador (`localToday`). Em UTC−3 os dois
coincidem; fora disso, não: **das 21h à meia-noite de Brasília, um aparelho
em UTC calcula "amanhã"**, e o lançamento é recusado sem o funcionário
entender por quê — a linha some do "salvo" e nada explica.

Achado pelo CI, que roda em UTC: o E2E do curral falhou às 00:30 UTC e
passava na máquina de quem desenvolve, em UTC−3. Reproduzido localmente às
01:09 UTC com a mesma mensagem.

Corrigido: `farmToday()` calcula o dia da fazenda pelo deslocamento fixo,
igual ao servidor, e não depende do fuso do aparelho. O Playwright agora
roda com `timezoneId: "UTC"`, para que a suíte local cubra essa classe de
bug em vez de escondê-la.

Continua dependendo de o **relógio** do aparelho estar mais ou menos certo —
só o fuso deixou de importar. Se isso virar problema (celular com data
errada), o passo seguinte é a API devolver o dia da fazenda e a tela usar
esse valor.

## Resolvido: sair e recarregar reabria a sessão

O botão Sair mostrava o login na hora e revogava a sessão no servidor sem
esperar resposta. Se a página recarregasse logo em seguida (ou a aba fosse
fechada), o pedido era cortado, e o cookie de sessão, ainda válido, reabria o
app logado como quem tinha acabado de sair — num celular compartilhado, uma
sessão viva sem ninguém saber. Achado pelo E2E, que falhava de forma
intermitente ("Contas" e "senha provisória"). Agora o Sair apaga o token
local, espera a revogação (até 5 s, para quem está sem rede) e só então mostra
o login.

A suíte E2E também falha se rodada várias vezes seguidas contra o mesmo
Redis: os logins errados propositais acionam o limitador por origem ("Muitas
tentativas de login"). É a proteção funcionando; recrie a pilha (`down -v`)
entre rodadas locais, como o CI faz.

## Leitor local de folhas (fase 2, passo 1) — decisões registradas

Decisões do titular em 19/09/2026, a partir da primeira folha real:

- **Brinco com prefixo:** o caderno traz "694", o cadastro tem "B2-694" (68
  animais têm B1-/B2-). O sistema **sugere, nunca associa sozinho**
  (alerta `brinco_variant`). Vale também para zero à esquerda ("011" ↔
  "B2-11"). O cadastro não foi alterado.
- **"→ SECAR" é uma ordem para secar**, não o registro de que secou: vira
  proposta de secagem com a data da folha e o alerta `dry_off_order` para
  confirmar a data real.
- **"4 + 3 = 7" é manhã + tarde = total diário.** Grava-se o total; as
  ordenhas só conferem a leitura (alerta `sum_mismatch`).
- **Nome parecido é sugestão, não divergência.** "PAETENHA" no brinco da
  PRETINHA não gera `name_mismatch` (semelhança ≥ 0,6); um nome diferente
  gera, porque o brinco pode ter sido mal lido e cair noutra vaca.
- **Data com mais de 6 meses** gera `old_date`: o modelo leu o ano do
  cabeçalho errado na primeira folha.
- **Ainda não feito:** envio da foto pelo app (hoje a leitura entra por
  comando), corrigir a data de uma folha inteira de uma vez na revisão, e
  mostrar a imagem ao lado das propostas.

## Caixa de revisão (fase 1, sem leitura automática) — decisões registradas

- **Toda leitura vira proposta, nunca dado direto.** Foto, áudio e texto
  geram `event_proposals` pendentes; só a aprovação de um revisor aplica o
  evento, pelos mesmos serviços do cadastro (`update_animal`, baixa, lote).
  A produção aprovada usa a proveniência `proposal_review`, e o trigger do
  banco exige uma proposta aprovada do mesmo animal decidida pela mesma conta.
- **O que foi lido não muda.** `raw_fields`, a fonte e a saída bruta do
  leitor são imutáveis (triggers); a correção do revisor vai em
  `applied_payload`. Proposta decidida não volta a pendente.
- **Só o brinco associa.** Nome lido gera sugestões; sem brinco, aprovar exige
  escolher o animal. Nome divergente do cadastro gera alerta.
- **DEL não é gravado.** "DEL 120" vira data de parto calculada, com o alerta
  `derived_from_del` para o revisor confirmar.
- **Produção diferente da já lançada pede motivo**, como na importação por
  arquivo; igual é registrada como "já lançada", sem duplicar.
- **Leitura local, sem provedor externo.** As fases de visão e áudio vão rodar
  modelos na própria infraestrutura; nenhuma imagem ou gravação sai dela.
- **Resolvido junto: 500 ao editar parto ou peso na ficha do animal.** A
  auditoria do cadastro tentava gravar `date`/`Decimal` direto em JSON;
  agora converte (`_jsonable` em `animal_registry.py`).
- **Navegação com nove áreas** quebra em duas linhas em telas de computador
  estreitas, em vez de cortar a última.

## Cadastro mestre — resolvido

API e telas existem: buscar animal, ver ficha, vincular brinco, mudar de lote,
cadastrar animal e gerenciar contas. Ver a seção 5 do runbook.

## Foto do celular vira proposta (fase 2c) — decisões registradas (20/09/2026)

### O `worker` ganhou saída para fora da rede interna

Até aqui o `worker` vivia só em `ingestion_private`, uma rede `internal`: sem
rota para fora. Para falar com o leitor (que no Windows roda **fora** do
Docker, porque a GPU AMD não passa para o contêiner) ele precisou de uma
segunda rede, `reader_link`, não interna, mais
`extra_hosts: host.docker.internal:host-gateway`.

**É uma troca de isolamento por capacidade, e está registrada como tal.** O
que limita o estrago:

- o padrão continua `READER_PROVIDER=fake`, que não fala com ninguém;
- `ensure_local_url` recusa endereço público: só loopback, IP privado, nome
  sem ponto, `localhost` e `host.docker.internal` passam. Mandar a foto para
  um provedor externo exigiria afrouxar a guarda de propósito;
- o `worker` não tem `AUTH_SECRET`: mesmo comprometido, não emite sessão;
- a `api` e o banco continuam sem essa rota.

Quando o leitor virar serviço do compose (`ollama:11434`) ou um servidor
próprio na VPN, a `reader_link` pode voltar a ser `internal` — a mudança é de
infraestrutura, não de código.

### O leitor falso é recusado em produção

`RUNTIME_ROLE=worker` com `READER_PROVIDER=fake` não sobe em produção: o
leitor falso devolve sempre a mesma vaca e o mesmo volume, e isso viraria
medição de mentira na caixa de Revisão. `ollama` sem `READER_URL` também é
recusado, na subida, não na primeira foto.

### A foto fica ligada à proposta, e a fonte continua imutável

`event_proposal_sources.image_asset_id` (migração 0012) é gravado **no
INSERT**. A fonte é imutável por gatilho: ligar a foto depois, por UPDATE,
seria recusado pelo banco. O inbox devolve `photo_url` assinada por 15
minutos, para quem revisa conferir a folha sem trocar de tela.

### A área "Fichas" saiu do menu, o código antigo ficou

O caminho antigo (`POST /api/imports` → `run_extraction` →
`provenance=ocr_review`) continua no banco e no código, servindo as fichas já
importadas. O envio de foto novo mora dentro da Revisão. Apagar as telas, as
rotas e o `approval.py` é assunto de outro PR — nada foi removido agora.

### A caixa não se atualiza sozinha

A leitura termina em segundo plano, e a tela não escuta o servidor. Enquanto
não há notificação, a Revisão traz um botão **Atualizar**: clicar na aba já
escolhida não recarregaria nada. Empurrar a atualização (SSE, WebSocket ou
sondagem) fica para quando houver mais de um revisor ao mesmo tempo.

## A anotação da margem contaminava a folha inteira (20/09/2026)

Achado na **primeira prova com o leitor de verdade** ligado ao app: uma foto
de 22/07 (14 vacas, lote 1) entrou pela Revisão e produziu 14 produções e
**13 ordens de secagem que não existem na folha**. A folha tem duas setas na
margem, ambas "→ 2º LOTE"; nenhuma diz "SECA".

Não era regressão da fase 2c: a leitura saiu idêntica à que o CLI já
produzia. A fiação nova apenas expôs, em uso real, um defeito de leitura que
a medição por campo não pegava — ela conferia brinco, nome e litros, não
quantas anotações foram inventadas.

Medido nas cinco fotos de 22/07, antes:

| foto | linhas | anotações na folha | eventos de anotação lidos |
|---|---|---|---|
| lote1-2 | 14 | 2 | 14 (13 "secar" falsas) |
| lote1 | 28 | ? | 28 (27 "secar" falsas) |
| lote2-2 | 28 | ? | 28 (todas "3º lote") |
| lote2 | 23 | 4 | 23 (todas "3º lote") |
| lote3 | 21 | 0 | 0 |

A assinatura é clara: onde não há anotação nenhuma, sai limpo; onde há uma,
ela é copiada para a folha inteira. A anotação fica solta na margem direita,
longe da linha a que pertence — é o campo mais fácil de o modelo generalizar.

### O que foi feito

1. **Guarda no código** (`_drop_repeated_annotation`): a mesma anotação em
   seis linhas ou mais, cobrindo 60% da página, é repetição do modelo, não
   leitura — e é apagada. Seis linhas porque um lote pequeno pode mudar de
   lote junto de verdade; 60% porque margem anotada de ponta a ponta não
   acontece na folha.
2. **Prompt do formulário impresso** (`folha-v8`): diz que anotação é rara e
   que só se escreve onde há tinta na margem naquela altura.

Depois, nas mesmas cinco fotos: **91 eventos de anotação viraram 3**. As
ordens de secagem falsas sumiram inteiras.

### O que se perde, e por que vale a pena

**A guarda é que resolve; o prompt quase não.** As transcrições cruas do v8
ainda trazem "→ SECA" em 13 e 27 linhas e "→ 3º LOT" em 28 — quem limpa é o
código. Por isso a guarda ficou no código e não na instrução: prompt deriva,
código não.

E o leitor agora **lê anotação de menos**: no lote 2, das 4 anotações reais
("→ 3º LOTE" em três linhas e "DOENTE" numa), sai 1. A troca é deliberada —
uma troca de lote que não aparece é uma correção pequena na caixa; vinte e
três ordens de secagem falsas afogam quem revisa e, aprovadas sem conferir,
secam um lote inteiro.

A leitura crua fica guardada em `extraction_runs.raw_response`: nada é
perdido em silêncio, e a foto está ao lado das propostas.

**Próximo passo natural** (não feito): perguntar a margem em **chamada
própria**, como já se faz com o cabeçalho — "quais linhas têm escrita na
margem direita, e o quê" —, que foi o que resolveu o cabeçalho.

## O cabeçalho lido à parte pode falhar em silêncio

A data e o lote são perguntados numa chamada só deles, com prazo de 90 s,
porque no meio de 48 linhas saíam errados. Se essa chamada estoura o prazo —
com a GPU carregada, acontece: uma folha do 1º lote levou 216 s —, o leitor
volta para a data que veio no meio da transcrição, que é a fonte pior, **sem
dizer nada**. Nas cinco fotos de 22/07, três leram a data como 25/08.

Agora fica registrado no log (`cabeçalho não pôde ser lido à parte`). O
revisor corrige a data do arquivo inteiro de uma vez, então o estrago é
pequeno — mas era invisível.

## O lote do cabeçalho não vira dado nenhum

Registrado porque a lacuna "corrigir o lote do arquivo inteiro, como já se
corrige a data" estava na lista de próximos passos com prioridade alta, e a
conferência do código mostrou que ela vale pouco: `sheet_to_events` usa só a
`data` do cabeçalho. O lote lido serve para conferir a leitura contra o
gabarito; não entra em proposta nenhuma. Troca de lote só existe quando está
escrita na margem, linha a linha, e essa o revisor corrige no próprio cartão.

## O recorte do cabeçalho cortava o cabeçalho (20/09/2026)

A data saía errada em três das cinco fotos de 22/07 — e data errada erra a
**página inteira**, não uma linha. A primeira hipótese foi prazo: o cabeçalho
é perguntado numa chamada própria de 90 s, e a folha do 1º lote levava 216 s.
Medida a chamada sozinha, ela leva **24 a 52 s**: nunca estourou.

A causa era geométrica. O recorte pegava 18% do alto da folha, o que bastava
no PDF escaneado, em que a folha começa no pixel zero. Na foto de celular a
mesa entra no enquadramento, e esses 18% terminam **acima** da linha
"LOTE: __ DATA: __": o modelo recebia um retângulo de papel em branco e
inventava uma data — a mesma nas três, "25/08/26".

Medido nas cinco fotos, com o recorte em 32%:

| foto | 18% (antes) | 32% (agora) | folha |
|---|---|---|---|
| lote1-2 | 25/08/26 · 1º LOTE | **22/07/26 · 1º** | 22/07/26 · 1º |
| lote1 | 25/08/26 · 2º LOTE | **22/07/26 · 1º** | 22/07/26 · 1º |
| lote2-2 | 22/07/26 · 2º | 22/07/26 · 2º LOTE | 22/07/26 · 2º |
| lote2 | 22/07/26 · 2º | 22/07/26 · 2º | 22/07/26 · 2º |
| lote3 | 25/08/26 · 1º LOTE | **22/07/26 · 3º** | 22/07/26 · 3º |

Cinco de cinco, data e lote. 45% não melhora nada e custa o mesmo. Na folha
manuscrita de 25/08 (PDF escaneado) as três páginas dão leitura **idêntica**
com 18% e com 32%: o recorte maior não tira nada de quem já acertava.

**A lição** é sobre o método, não sobre o modelo: a hipótese ("estourou o
prazo") era plausível e estava errada, e cronometrar a chamada custou dois
minutos. O log de aviso que tinha sido acrescentado para esse caso continua
no lugar — só não era esse o problema.

## Margem e brincos ganharam pergunta própria (formulário impresso)

A guarda contra anotação repetida apaga o estrago, mas com ele some também a
anotação verdadeira: das 4 anotações reais do 2º lote saía 1. Então a margem
passou a ser perguntada sozinha — "quais linhas têm escrita na margem
direita, e o quê" —, e a resposta dela manda: a linha que ela não cita fica
sem anotação. É o mesmo desenho que resolveu o cabeçalho.

O brinco do formulário impresso segue o mesmo caminho, do outro lado: a faixa
esquerda leva a coluna escrita à mão e os números impressos que a ancoram,
com mais pixels por dígito. Aqui, porém, a regra é outra — a linha que a faixa
não cita **fica com o que a transcrição leu**. O problema do brinco é dígito
trocado, não brinco inventado, e apagar o que já se tinha seria perder leitura
boa.

**Só no formulário impresso.** Na folha manuscrita não há margem: brinco e
anotação estão dentro da própria linha ("3 - 389 ÁGATA → 4 + 5 = 9 → SECAR").
Perguntar "o que há na margem" ali devolveria lista vazia — e a lista vazia
apaga anotação. Seriam as 10 ordens de secagem e as 7 trocas de lote de 25/08
apagadas de uma vez.

## Exemplo dentro do prompt vira resposta (20/09/2026)

A instrução da margem dizia o que procurar: *"geralmente depois de uma seta:
'→ 2º LOTE', '→ SECA', 'DOENTE'"*. Na primeira foto lida com a margem em
chamada própria, o modelo devolveu exatamente **as três** — numa folha que
tem só duas setas, ambas "→ 2º LOTE". As anotações falsas caíram de 13 para
2, mas as 2 que sobraram saíram do nosso próprio texto.

Agora a instrução descreve a **forma** ("em geral uma seta seguida de duas ou
três palavras") e manda copiar o que estiver escrito, dizendo explicitamente
para deixar a linha de fora quando não der para ler, em vez de trocar por
uma anotação parecida ou provável. Um teste trava isso: "SECA" e "DOENTE"
não podem aparecer nas instruções do formulário impresso nem da margem.

**A folha manuscrita ficou como estava**, de propósito: ali "SECAR" aparece
no exemplo que ensina o formato da linha ("8 - 633 GIGANTE → 2 + 2 = 4 →
SECAR"), e é a folha em que a leitura de anotação ia razoável (10 secagens e
7 trocas de lote em 113 linhas). Tirar sem medir contra o gabarito seria
trocar um erro conhecido por um desconhecido. Está na fila, com gabarito.

## A palavra "null" escrita por extenso virava leitura

Na mesma foto, o modelo escreveu a **string** `"null"` nos campos das 14
linhas em branco do formulário — em vez de deixar o campo vazio, como o
esquema permite. Para o nosso código "null" era texto, logo a linha tinha
conteúdo: as 14 linhas vazias viraram **14 produções fantasma**, com litros
"null", que chegariam à caixa de Revisão.

Duas correções:

1. `_clean` passa a tratar como vazio o que é vazio escrito por extenso:
   `null`, `none`, `nulo`, `n/a`, `-`, `--`. Vale para todos os campos.
2. As instruções não pedem mais "use null" nem "o brinco é null" — pedem
   "deixe vazio", e dizem para nunca escrever a palavra "null" como
   conteúdo. Era provavelmente o que ensinava o modelo a escrevê-la.

A guarda no código é o que garante: prompt deriva, código não.

## A pergunta dos brincos ajuda — medida com e sem (20/09/2026)

A chamada da faixa esquerda foi acrescentada por raciocínio, não por
medição. Medida depois, nas mesmas cinco fotos de 22/07, com o mesmo código
e a mesma comparação com o banco, mudando só se a pergunta acontece:

| | sem a pergunta | com a pergunta |
|---|---|---|
| **chega à revisão com a vaca certa associada ou em 1º** | 83% (7 toques em "Ou é esta") | **91%** (5 toques) |
| vacas do dia achadas pelo brinco | 87% | 82% |
| linhas que apontam vaca já apontada | 8 | 7 |

O contraste diz algo útil sobre o que cada número significa. Sem a pergunta,
o leitor **encontra** mais vacas do dia — mas associa pior. Com ela, encontra
um pouco menos e põe o brinco certo **na linha certa**, que é o que faz a
vaca certa aparecer no cartão de quem revisa.

Como o produto é a caixa de Revisão, a métrica que manda é a segunda, e a
pergunta fica. Custo medido: 22 s por folha.

## A leitura é determinística, e isso é uma ferramenta

A mesma folha, lida duas vezes com o mesmo código, deu **exatamente** os
mesmos 113 campos — inclusive os errados. Isso não é detalhe: sem
determinismo, comparar duas versões do leitor não significaria nada, porque
a diferença poderia ser sorte.

Foi assim que uma regressão na folha manuscrita foi atribuída a uma mudança
nossa em vez de "variação do modelo": repetida, a leitura não mudou nada.
Vale o registro para quem for medir de novo — se dois resultados diferem, a
causa está no código ou na instrução, não no acaso.

## Uma frase de instrução custou 10 pontos na folha manuscrita (20/09/2026)

Ao consertar a palavra "null" escrita por extenso, a instrução passou de
*"Campo ilegível: null"* para *"Campo ilegível: deixe vazio"* — nos **dois**
formatos de folha. A medição do formulário impresso melhorou; a da folha
manuscrita, que não foi medida na hora, piorou:

| campo | v7 | com o texto novo | com o texto revertido |
|---|---|---|---|
| brinco | 63% | 58% | **63%** |
| nome | 30% | 23% | **30%** |
| manhã | 78% | 66% | 76% |
| tarde | 78% | 72% | 74% |
| total | 73% | 63% | 68% |
| anotação | 75% | 77% | 75% |
| perdidas / inventadas | 7 / 1 | 6 / 0 | **7 / 1** |

O texto voltou a ser o da v7 nas regras comuns e na folha manuscrita; o
aviso sobre a palavra "null" ficou só no formulário impresso, onde foi
medido. Custo no impresso: 1 ponto (91% → 90% de chegada à revisão). Ganho na
manuscrita: 5 a 10 pontos.

**A lição é de método:** mudança em instrução compartilhada tem de ser medida
nos dois formatos antes de entrar. A guarda que realmente resolve o "null" é
a do código (`_clean`), que não depende de o modelo obedecer.

### O que sobrou sem explicação

Os litros ficaram ~5 pontos abaixo da v7 (total 68% contra 73%), com
identidade e contagem de linhas idênticas. Três candidatos foram
**eliminados por medição**, e ficam registrados para quem continuar:

- **não é variação entre rodadas**: a mesma folha, lida duas vezes com o
  mesmo código, deu os mesmos 113 campos, inclusive os errados;
- **não é a limpeza de campos vazios**: os 29 totais errados são todos
  números mal lidos ("37,5" lido "33,5"), nenhum vazio;
- **não são as guardas de anotação**: com elas desligadas, a folha dá
  exatamente os mesmos números.

## Fase 3: a gravação da ordenha vira proposta — decisões e limites (21/09/2026)

### Medido com as gravações do titular

Três gravações de teste (40 a 49 s cada, fora do Git), com 11 vacas ditas em
frase natural. Pelo caminho real inteiro — envio pela API, fila, worker com
ffmpeg, whisper na GPU, tradutor, propostas no banco:

- **as 11 vacas** com brinco, nome e total certos;
- as **4 ordens de secar** e a **troca para o 1º lote**;
- "secar ela daqui a 7 meses" como ordem de secagem **e** observação com o
  prazo;
- nenhuma proposta de conversa ("bora lá, meu amigo", "certo? obrigado");
- leitura de 7 a 20 s por gravação.

É um número bom e **otimista**: as gravações são de teste, ditas com calma. O
número de verdade sai de gravações no curral, com a ordenhadeira ligada.

### O jeito real de falar mudou o tradutor

O primeiro desenho separava vaca por ponto final. As gravações mostraram que
o whisper põe ponto no MEIO de uma vaca, que o nome vem junto, que o brinco às
vezes vem em outra frase ("o número dela é 462") e que há conversa no meio.
Agora uma vaca começa numa âncora — "vaca", um número com cara de brinco, ou
um nome no começo da frase seguido de "produziu" — e vai até a próxima.

**Limites que decorrem disso, conhecidos:**

- **Brinco de menos de três dígitos só é reconhecido depois de "vaca".** A
  regra que separa brinco de litro é "três dígitos ou mais, ou zero à
  esquerda" (litro nunca passa de 100 por dia). "A 16 deu 5" não acha o
  brinco 16; "vaca 16 deu 5" acha. O cadastro desta fazenda guarda brincos com
  zero à esquerda ("016"), e o whisper preserva o zero quando ele é dito.
- **A lista de conversa descarta palavras soltas** ("assim", "bem", "certo",
  "depois"...). Uma observação feita só dessas palavras some. Isso evita
  proposta de lixo, e o custo é perder uma observação que só dissesse, por
  exemplo, "bem".
- **Parto, baixa e DEL falados não têm análise estruturada**: viram
  observação com o texto dito. Escrever gramática para eles sem gravação real
  para medir seria adivinhação, e adivinhação errada em "baixa" é o erro mais
  caro que pode chegar à caixa.
- **"meia" sozinha não é lida** (é 0,5 ou é 6).
- **"Secar daqui a 7 meses" gera a ordem de secagem com a data da
  gravação**, mais a observação com o prazo. É o mesmo comportamento da folha
  ("SECAR 7 MES."): quem revisa lê o prazo e ajusta.

### A data da gravação

A fala não tem cabeçalho. A data de referência é o dia da fazenda em que a
gravação foi **enviada** — não o da leitura, que pode ser um reprocessamento
dias depois. Quem revisa corrige o arquivo inteiro de uma vez se precisar.

### iPhone

O Safari não oferece gravação num campo de arquivo de áudio: no iPhone a
pessoa grava no app Gravador e escolhe o arquivo. A tela avisa. Gravar dentro
do próprio app (MediaRecorder) ficou para uma fase seguinte, por decisão do
titular.

### Três defeitos que já existiam e que o áudio expôs

- **O teto de upload era 1 MB, não 15 MB.** O nginx não declarava
  `client_max_body_size`. Uma gravação de um minuto passa disso sempre, e a
  foto passava às vezes — e o que morria no proxy voltava como HTML, que o app
  lia como erro de conexão. Agora o limite é 20 MB no proxy, e cada motivo de
  falha tem o seu texto na tela.
- **O link da foto na Revisão nunca abriu na pilha real** (fase 2c): era uma
  URL do armazenamento interno (`http://minio:9000`), que nenhum navegador
  resolve. Agora o arquivo abre pela própria API, com o login.
- **A hora no nome do arquivo saía em UTC** ("Foto de ... 20:16" para um envio
  das 17:16). Agora é a hora da fazenda.

### A tarefa do whisper apareceu desativada

Durante o trabalho de 21/09 a tarefa `BeloVale-Whisper` foi encontrada
**desativada**, com o servidor encerrado por um Ctrl+C (o log termina em
`^C`). O registro operacional do Agendador está desligado (padrão do
Windows), então não dá para saber quem desativou: pode ter sido o titular, o
antivírus ou o próprio Windows. Não foi reativada automaticamente — é
configuração da máquina, e a decisão é do titular. Se foi acidental:

```powershell
Enable-ScheduledTask -TaskName "BeloVale-Whisper"
Start-ScheduledTask  -TaskName "BeloVale-Whisper"
```

Se voltar a acontecer, ligar o registro do Agendador ajuda a achar a causa:
`wevtutil set-log Microsoft-Windows-TaskScheduler/Operational /enabled:true`
(terminal de administrador).
