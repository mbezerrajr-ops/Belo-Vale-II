# Estabilização da branch mais recente

## Objetivo

Transformar `feature/importa-relatorio-animais` na baseline confiável do produto
legado, preservando suas funcionalidades e seus dados mais recentes antes de
integrá-la à `main` e usá-la como origem da futura migração para PostgreSQL.

O resultado desta fase deve manter 401 animais e 152 medições históricas, eliminar
identificadores técnicos duplicados, tornar a geração do HTML reproduzível e
registrar separadamente conflitos que dependem de decisão do negócio.

## Escopo

Esta fase inclui:

- preservar o estado completo embutido em `platform_ATUAL_publicado.html`;
- criar uma representação canônica completa e legível por ferramentas;
- validar contagens, medições e unicidade antes de publicar ou migrar dados;
- corrigir IDs técnicos duplicados de forma determinística e idempotente;
- manter `state_dados_atuais.json` como projeção sem histórico, deixando essa
  limitação explícita;
- separar leitura/escrita de estado, validação de integridade e importação do PDF;
- atualizar a documentação para refletir 401 animais e a fonte de verdade real;
- criar testes automatizados reproduzíveis para os contratos acima.

Não faz parte desta fase:

- migrar dados para PostgreSQL;
- alterar autenticação ou substituir o Artifact;
- escolher ou integrar um provedor de visão/OCR;
- fundir automaticamente animais com brincos antigos e novos;
- decidir automaticamente se um animal sem DEL está seco;
- reescrever o frontend legado em React.

## Baseline protegida

A baseline é o commit `c3854c26b8697050a118d10123103b4b7d31d763` da branch
`origin/feature/importa-relatorio-animais`.

Os seguintes invariantes são obrigatórios durante a estabilização:

- exatamente 401 animais;
- exatamente 152 medições históricas;
- 107 medições em `2026-07-22`;
- 45 medições em `2026-08-25`;
- quatro insumos e dois usuários preservados;
- nenhum histórico existente pode mudar de animal, data ou produção;
- todo animal deve ter ID técnico não vazio e único;
- gerar novamente o estado deve produzir o mesmo resultado lógico;
- nenhuma correção automática pode fundir ou excluir animais.

## Fonte canônica e artefatos derivados

Durante a estabilização, `plataforma/state_canonical.json` passa a representar o
estado completo versionado, incluindo históricos. Ele será extraído uma vez do
bloco `state-data` do HTML da baseline e depois usado para gerar os derivados.

Os artefatos terão responsabilidades distintas:

- `state_canonical.json`: estado completo e origem para validação/migração;
- `platform_ATUAL_template.html`: aplicação sem dados embutidos;
- `platform_ATUAL_publicado.html`: aplicação gerada com o estado canônico;
- `state_dados_atuais.json`: projeção operacional sem `historico`, mantida por
  compatibilidade e nunca descrita como backup completo;
- `import_relatorio_animais_ultimo_relatorio.txt`: relatório humano da última
  reconciliação com o PDF.

Uma rotina de I/O de estado será responsável por extrair o JSON do HTML, carregar
o canônico, gerar o HTML publicado e gerar a projeção. O importador de PDF consumirá
essa interface em vez de manipular HTML e arquivos diretamente em seu corpo global.

## Identidade dos animais

`numero` e `brinco` são atributos de negócio e podem mudar ou pertencer a séries
diferentes. `id` é uma chave técnica usada pela interface e precisa ser única.

A estabilização não regenerará os 401 IDs. Somente grupos já duplicados serão
reparados. Para cada membro de um grupo em conflito, o novo ID será derivado de:

1. ID antigo;
2. brinco, quando presente, senão número;
3. nome normalizado.

O formato será ASCII, minúsculo e determinístico. Colisões residuais receberão um
sufixo ordinal estável calculado após ordenação pela identidade de negócio. Rodar a
rotina novamente não deverá alterar IDs já únicos.

Antes da correção, os testes devem reproduzir os grupos `v570`, `v346` e `v`. Depois
da correção, os seis registros continuam existindo e podem ser editados
individualmente pela interface.

## Regras de DEL e situação

DEL continua sendo derivado da data do último parto quando estiver preenchido. A
assimetria atual — 30 animais importados com DEL vazio e situação “Em lactação” —
será registrada como aviso de reconciliação, não corrigida automaticamente.

Essa decisão evita transformar uma hipótese técnica em regra zootécnica. Uma fase
posterior deverá receber uma regra aprovada pelo responsável pelos dados para
definir como lote, DEL e situação se relacionam.

Avisos não bloqueiam a geração do Artifact. Violações estruturais, como ID vazio ou
duplicado, contagem divergente e perda de medições, bloqueiam a geração.

## Componentes

### `state_contract.py`

Módulo sem dependências externas com funções puras para:

- carregar e serializar estado;
- extrair/injetar `state-data` no HTML;
- calcular o resumo da baseline;
- detectar IDs inválidos;
- reparar apenas IDs duplicados/vazios;
- produzir a projeção sem históricos;
- retornar erros estruturais e avisos de negócio separadamente.

### `build_platform_state.py`

CLI fina que usa `state_contract.py`. Terá comandos explícitos para validar,
extrair a baseline e gerar os dois artefatos derivados. A execução que grava
arquivos será atômica sempre que possível e falhará antes da escrita se houver
erro estrutural.

### `import_relatorio_animais.py`

Continuará responsável pela interpretação e conciliação do relatório de animais,
mas passará a expor funções e um `main()` protegido. Leitura de PDF, casamento e
aplicação serão unidades distintas. O modo padrão continuará sendo simulação; o
modo `--write` atualizará o estado canônico por meio da interface compartilhada.

## Estratégia de testes

Os primeiros testes usarão `unittest` e apenas a biblioteca padrão do Python 3.13,
para que o contrato de dados seja executável sem instalar `pdfplumber` ou
Playwright.

O ciclo será TDD:

1. teste falha ao encontrar IDs duplicados na baseline;
2. reparo mínimo torna os IDs únicos sem alterar contagens ou históricos;
3. testes de idempotência protegem execuções futuras;
4. testes de round-trip garantem paridade entre JSON canônico e HTML gerado;
5. testes de projeção garantem que somente `historico` é removido;
6. teste do PDF real será adicionado quando a dependência for declarada e instalada;
7. E2E da interface será modernizado para usar caminhos relativos e Chromium
   gerenciado pelo Playwright.

Os testes de integridade devem trabalhar sobre dados reais versionados, sem mocks.
Fixtures sintéticas pequenas serão usadas apenas para erros de borda e colisões.

## Documentação e rastreabilidade

O README raiz e o README interno deverão concordar sobre:

- 401 animais como baseline mais recente;
- `state_canonical.json` como estado completo versionado;
- `state_dados_atuais.json` como projeção sem histórico;
- 152 medições preservadas;
- PONTA CURTA e GIGANTE já possuírem leitura de `2026-07-22` na baseline;
- conflitos de nome, animais ausentes e possíveis pares antigos/novos continuarem
  pendentes de conciliação humana.

Cada etapa deve produzir uma mudança pequena, testável e revisável. Nenhuma etapa
de estabilização deve misturar a futura migração para PostgreSQL.

## Critérios de aceite

- A validação da baseline passa sem erros estruturais.
- Os 401 animais permanecem presentes.
- As 152 medições permanecem byte a byte equivalentes em conteúdo lógico.
- Não existem IDs vazios ou duplicados.
- Reparar IDs duas vezes produz o mesmo resultado.
- O HTML publicado e o JSON canônico contêm o mesmo estado.
- A projeção contém os mesmos animais e campos, exceto `historico`.
- As 30 inconsistências DEL/situação aparecem como avisos, sem alteração silenciosa.
- Os READMEs não apresentam fontes de verdade ou contagens contraditórias.
- Os testes relevantes executam por comandos documentados a partir do worktree.
