# Status do provedor de visão/OCR

Esta é uma classificação explícita, para não confundir "implementação
estruturalmente pronta" com "integração externa validada".

> **Removido em 24/09/2026:** as três primeiras seções (`FakeVisionProvider`,
> `HttpVisionProvider` e provedor externo) descrevem o leitor do caminho
> antigo das Fichas, que saiu do código. O leitor em uso começa em "Leitor
> local de folhas (Ollama)", abaixo. Ver `known-issues.md`, "Caminho antigo
> das Fichas removido".

## FakeVisionProvider

**Comprovado em uso real.** É o provedor padrão (`VISION_PROVIDER=fake`,
valor default em `Settings`), exercitado pelos testes de backend contra
Postgres real e pelo fluxo E2E completo via Playwright contra o Docker
Compose real (upload → worker → extração → revisão → aprovação → dashboard).
Deliberadamente determinístico — sempre retorna o mesmo animal, lote e data
— o que é adequado para testes, mas significa que ele não testa nada sobre
qualidade de reconhecimento de imagem real.

## HttpVisionProvider

**Validado apenas estruturalmente.** Revisado nesta task quanto a:

- Construção da requisição: `POST` do conteúdo pré-processado da imagem
  como corpo bruto (`application/octet-stream`), com `Authorization: Bearer
  <chave>` lida exclusivamente de `Settings` (nunca aceita do chamador nem
  exposta ao frontend).
- Autenticação/configuração: `get_vision_provider()` recusa-se a construir
  o adaptador HTTP sem `VISION_API_URL` e `VISION_API_KEY` configurados —
  levanta `RuntimeError` explícito (coberto por teste).
- Parsing: mapeia a resposta JSON esperada (`header_text`, `lot`,
  `measured_on`, `header_confidence`, `lines[]`) para `VisionExtraction`/
  `VisionLine`, incluindo conversão de `bounding_boxes` de listas para
  tuplas.
- Timeout: usa timeout fixo de 60s na chamada (`urllib.request.urlopen`).

**Não comprovado nesta task:**

- Tratamento de erro de rede/indisponibilidade do provedor externo (a
  chamada pode levantar `URLError`/`HTTPError` sem tratamento específico no
  adaptador — hoje isso propaga como exceção genérica até `run_extraction`,
  que já trata qualquer exceção nesse ponto marcando o run como `failed`
  preservando o estado; ou seja, o comportamento agregado é seguro, mas o
  adaptador em si não tem tratamento fino por tipo de erro HTTP).
- Parsing de uma resposta malformada/inesperada de um provedor real (só foi
  testado com um dicionário Python já no formato esperado, não com JSON
  malformado ou com campos ausentes além dos opcionais já tratados via
  `.get(...)`).

## Provedor externo real

**NÃO COMPROVADO.**

Motivo: não existe, neste ambiente, nenhuma credencial de um provedor de
visão/OCR real configurada nem autorizada para uso. Nenhuma chamada de rede
foi feita a um serviço de visão computacional de terceiros durante esta
task — nem haveria como fazê-lo com segurança sem uma URL e chave
legítimas fornecidas pelo usuário. Nenhum documento real ou sensível foi
enviado a qualquer serviço externo.

Se/quando uma integração real for autorizada, o ponto de entrada já existe
e está isolado (`app/vision/provider.py::HttpVisionProvider`) — trocar de
provedor não deveria exigir mudanças em `run_extraction`, `extraction_processing.py`
ou em qualquer camada acima do adaptador, já que todos consomem apenas o
contrato `VisionExtraction`/`VisionLine`.

## Leitor local de folhas (Ollama) — fase 2, passo 1

**Comprovado em uma folha real; ainda não ligado ao app.** Roda só na
máquina da fazenda (decisão do titular: nenhuma foto sai para provedor
externo). `ensure_local_url` recusa qualquer endereço que não seja loopback,
rede privada ou nome de serviço interno.

- Código: `app/vision/pages.py` (PDF/foto → páginas) e
  `app/vision/sheet_reader.py` (transcrição pelo modelo + tradução em eventos
  sem IA). A saída entra na caixa de Revisão pelo mesmo contrato da fase 1.
- Modelo: `qwen2.5vl:7b` no Ollama 0.34, AMD RX 7600 (100% GPU, ~5,5 GB),
  instrução `folha-v2`, página reduzida a 1200 px.
- Nota: `python -m app.core.evaluate_reader --samples <pasta>` compara com os
  gabaritos (`<nome>.gabarito.json`). Amostras em `docs/Treinamento-VC/`,
  fora do Git.

### Primeira folha real (19/09/2026)

"PESAGEM DO LEITE 25/08/2026 3º LOTE", 18 linhas manuscritas. Gabarito
ainda em rascunho (a confirmar pelo titular).

| | v1 (1600 px) | v2 (1200 px) |
|---|---|---|
| tempo | 121 s | 43 s |
| linhas perdidas / inventadas | 0 / 0 | 0 / 0 |
| brinco | 11/18 | 13/18 |
| nome | 5/18 | 8/18 |
| manhã / tarde / total | 16 / 18 / 17 | 17 / 17 / 17 |
| anotação | 15/18 | 16/18 |
| data do cabeçalho | errada (2024) | errada |

O que chega à revisão (leitura v2 + cruzamento com o cadastro): as 18
produções têm a vaca certa associada ou entre as sugestões — 17 associadas ou
em primeiro lugar —, e **nenhuma foi associada à vaca errada**. Os brincos mal
lidos (4↔1, 4↔9) não existem no cadastro; o nome, mesmo torto, e o brinco a
um dígito de distância recuperam a vaca como sugestão.

**Limites conhecidos:**

- A data do cabeçalho não é confiável (25/08/2026 lida como 2024 ou como
  26/08). Data com mais de 6 meses gera alerta `old_date`; um dia trocado
  não é detectável — o revisor confere a data da folha.
- Leituras erradas mas coerentes (3 + 5 = 8 no lugar de 3 + 2 = 5) passam
  pela conferência de soma; só o revisor vê.
- Resultado de uma folha só: não serve para comparar modelos. Precisa de
  mais amostras com gabarito.

### Formulário impresso "CONTROLE LEITEIRO" (20/09/2026)

Cinco fotos de celular dos lotes 1 a 3 de 22/07/2026 (114 linhas). Os dados
já estavam lançados, então a nota é contra o banco (`--records-date`): 101
vacas com brinco e medição no dia.

O formato é outro: brinco escrito na **margem esquerda**, fora da tabela;
anotações na margem direita ("→ 2º LOT", "→ SECA", "DOENTE"); tiques de
conferência ao lado do total. O leitor agora pergunta primeiro qual é o
formato e usa instrução e ordem de chaves próprias para cada um.

| versão | brinco (vacas do dia achadas) | total certo | na revisão (vaca certa associada ou 1ª) | erro certo* |
|---|---|---|---|---|
| v2 (só folha manuscrita) | — | — | — | data lida como a de hoje |
| v3 (dois formatos, uma instrução) | 71% | 51% | — | — |
| v4 (brinco antes do nº da linha) | 90% / 68%** | 74% / 48%** | 89% / 86%** | 8 / 11** |
| v6 (formato detectado, semente fixa, releitura) | 87% | 53% | 82%, 10 com um toque em "Ou é esta" | 12 |

\* linhas que apontam uma vaca já apontada por outra linha.
\*\* duas rodadas da mesma instrução: sem semente fixa a leitura variava
muito entre rodadas (numa delas o modelo entrou em repetição na foto do
lote 1). A v6 fixa a semente e relê em outra resolução quando a leitura sai
incoerente (brincos repetidos, somas que não fecham).

Folha manuscrita de 25/08 com a v6: brinco 12/18, total 16/18, anotação 16/18
(a v4, com a ordem de chaves do formulário, tinha caído para 0/18 de brinco).

**O que ainda erra:** o brinco da margem desce ou sobe uma linha em blocos
da folha. Nome e litros continuam alinhados entre si, então a caixa de
Revisão avisa do nome divergente e oferece a vaca do nome lido ("Ou é esta")
a um toque. Com 6 folhas, diferenças de poucos pontos entre versões são
ruído; mais amostras dirão se vale trocar de modelo.

**Achado no cadastro:** há vacas duplicadas — uma ficha com brinco e outra
sem, com a medição de 22/07 na ficha sem brinco (SAIA BRANCA, TIETA,
BRANQUINHA, FAÍSCA...). Por isso parte das linhas "sem vaca do dia" está
certa; a nota as conta à parte, "a conferir".

### Folhas manuscritas de 25/08, em escala (113 linhas, 20/09/2026)

A planilha conferida pelo titular virou gabarito das 3 páginas do PDF
completo (`build_gabarito`) — o primeiro teste do leitor num volume real, não
numa folha só.

**Achado e corrigido: colisão de página por cabeçalho mal lido.** O PDF traz
as páginas fora da ordem dos lotes (3º, 1º, 2º), e o alinhamento passou a
usar o lote escrito em cada página, não a posição. Mas a página física do
2º lote foi lida com o cabeçalho **"3º LOTE"** — igual à página do 3º lote de
verdade — em duas leituras independentes. Sem defesa, as duas viravam a
mesma chave, e a nota cotejava vacas de páginas diferentes entre si,
inflando erros que não existiam (a primeira medição saiu com brinco 29%,
nome 5%). Corrigido: cada página ganha um rótulo único dentro da mesma
leitura; se dois cabeçalhos colidem, a segunda cai para um rótulo que nunca
se confunde com um número de lote. A página ambígua fica sem casar — nunca
casada com a errada.

**Números depois da correção, duas leituras limpas independentes:**

| | leitura 1 | leitura 2 |
|---|---|---|
| tempo | 684 s | 424 s |
| linhas perdidas / inventadas | 50 / 44 | 51 / 45 |
| brinco | 37% | 38% |
| nome | 13% | 19% |
| manhã / tarde | 42% / 47% | 46% / 47% |
| total | 39% | 43% |
| anotação | 45% | 44% |

Consistentes entre si — não é ruído de uma rodada. **Bem abaixo** da folha
manuscrita única de 25/08 medida antes (brinco 12/18 ≈ 67%): em volume, com
páginas de até 51 linhas lidas em faixas, o leitor erra mais do que numa
folha de 18 linhas lida de uma vez.

**A causa do cabeçalho errado** era disputa de atenção: data e lote eram
pedidos **dentro** da transcrição de 48 linhas. A escrita em si é legível —
"2º LOTE" claro, sem rasura relevante.

### v7: cabeçalho à parte e faixas na resolução original (20/09/2026)

Duas mudanças, medidas juntas no mesmo PDF de 113 linhas:

1. **O topo da folha (18% da altura) vai numa chamada própria**, com esquema
   de duas chaves e instrução curta — inclusive o aviso de que "2 e 3 se
   parecem nesta letra". A resposta tem dez palavras em vez de quatro mil
   tokens, e o valor lido ali prevalece sobre o que vier no meio das linhas
   (se o recorte não for legível, o antigo vale como reserva).
2. **Os recortes saem da página original.** Antes a página era reduzida para
   1200 px e **depois** cortada em faixas — cada faixa chegava com 1200×600
   de uma imagem já encolhida. Agora a página fica em resolução cheia, os
   recortes saem dela, e só então cada um é reduzido: o dobro de pixels por
   letra em cada faixa.

| | v6 | v7 |
|---|---|---|
| linhas perdidas / inventadas | 51 / 45 | **7 / 1** |
| manhã / tarde | 46% / 47% | **78% / 78%** |
| total | 43% | **73%** |
| anotação | 44% | **75%** |
| brinco | 38% | **63%** |
| nome | 19% | **30%** |
| tempo (3 páginas) | 424 s | 535 s |

O cabeçalho saiu certo nas três páginas, inclusive o "2º LOTE" que errara
nas duas leituras anteriores — era ele que derrubava o agregado, porque uma
página inteira deixava de casar.

Por lote, com a v7:

| lote | linhas | brinco | manhã/tarde | total | anotação |
|---|---|---|---|---|---|
| 1º (48 linhas, em faixas) | 45 lidas | 66% | 72% / 72% | 66% | 89% |
| 2º (47 linhas, em faixas) | 45 lidas | 59% | 76% / 74% | 72% | 74% |
| 3º (18 linhas, 1 chamada) | 18 lidas | 61% | 94% / 100% | 94% | 38% |

**O que ainda erra:** o ano da data (25/08/**2024** em vez de 2026) — o
revisor corrige o arquivo inteiro de uma vez. O brinco continua na casa dos
60%: é o campo mais difícil, porque um dígito trocado não tem contexto que o
denuncie. Nome baixo (30%) importa menos: ele serve de sugestão, e a caixa
de Revisão já casa por semelhança.

**Não é uma regressão de código:** a comparação honesta expôs um problema
de leitura que já existia, mas a comparação anterior (por posição, cega ao
lote) o escondia misturando ele com outro. A caixa de Revisão já corrige a
*data* de um arquivo inteiro de uma vez (`redate_source`); ainda não existe
o equivalente para o *lote* — quem revisa hoje corrigiria linha a linha se
o lote saísse errado. Registrado como próximo passo, não implementado agora.

## Qual caminho é o oficial (20/09/2026)

Existem dois caminhos de leitura no repositório. **O oficial é o novo.**

| | Fichas (legado) | Revisão (oficial) |
|---|---|---|
| Entrada | área "Fichas", fora do menu | **Revisão → Enviar foto** |
| Leitor | `VisionProvider` (`app/vision/provider.py`) | `EventExtractor` (`app/vision/reader.py`) |
| Modelo | nunca houve provedor real ligado | Ollama local, `qwen2.5vl:7b` |
| Resultado | linhas, `provenance=ocr_review` | eventos tipados, `proposal_review` |
| Situação | congelado, serve o que já foi importado | em uso |

O legado continua no lugar porque as fichas já importadas dependem dele.
Nada novo deve ser construído sobre ele. *(Em 24/09/2026 o código do legado
saiu; as medições que ele gerou continuam no banco, com a origem
`ocr_review`.)*

### O que o app sabe sobre o modelo

Só o endereço (`READER_URL`) e o nome do modelo. Não há SDK de provedor, não
há chave de API, e `ensure_local_url` recusa endereço público — a regra de
"nada sai para provedor externo" vale por construção, não por disciplina.
É isso que permite mudar de máquina (Windows do titular → servidor com GPU →
servidor próprio na VPN) sem tocar no código.

### O que ainda é conhecido como fraco

O brinco continua na casa dos 60% na folha manuscrita (ver a medição acima).
Ele é sugestão, não decisão: nada entra no rebanho sem alguém aprovar na
caixa de Revisão. Subir esse número (segmentar linha a linha, outros modelos)
é trabalho separado.

## v9 — os cantos da folha em perguntas próprias (20/09/2026)

As cinco fotos de celular de 22/07, contra as medições já lançadas no banco:

| versão | cabeçalho (5 folhas) | brinco | total | na revisão (vaca certa ou 1ª) | erro certo* |
|---|---|---|---|---|---|
| v6 | 2 de 5 | 87% | 53% | 82%, 10 toques em "Ou é esta" | 12 |
| **v9** | **5 de 5** | 82% | **81%** | **91%**, 5 toques | **7** |

\* linhas que apontam uma vaca já apontada por outra linha.

O salto do total (53% → 81%) e o da revisão (82% → 91%) vêm de três coisas
medidas uma a uma:

1. **O recorte do cabeçalho pegava 18% do alto** — o bastante no PDF
   escaneado, nada numa foto de celular, em que a mesa entra no
   enquadramento. Com 32%, data e lote saem certos nas cinco folhas.
2. **A palavra "null"**, escrita por extenso pelo modelo nas linhas em branco
   do formulário, virava leitura: 14 produções fantasma numa foto de 14 vacas.
3. **Brincos e margem ganharam pergunta própria**, com recorte próprio.

Custo: a leitura de uma folha passou de uma chamada a cinco. Medido numa
foto de 14 linhas, 220 s no total — 183 s deles na transcrição da página,
que já existia. As duas perguntas novas somam 29 s (13%).

### A margem ainda é o campo fraco

Gabarito das cinco folhas, conferido olhando foto por foto: **16 anotações**
(linhas 5 e 19 do lote 1; 5, 6 e 14 da continuação; 1, 10, 19 e 20 do lote 2;
2, 8, 10, 11, 13 e 20 da continuação; 16 do lote 3).

A pergunta própria acerta **7 linhas das 16**, com cerca de 5 falsas
sobrevivendo às guardas. Melhor que antes — o estado inicial era uma seta
virar 23 trocas de lote —, mas longe de bom.

**Por que ainda erra, medido:** a tira da direita é uma fração fixa da
largura (70% a 100%), e cada foto enquadra a folha de um jeito. Na foto do
lote 1 essa fração caiu **em cima da coluna TOTAL**: o modelo respondeu
26, 34, 33, 30… — os totais, não anotações. Não viraram 28 observações
falsas só porque a guarda que já existia descarta anotação feita só de
dígitos (era o tique de conferência ao lado do total). O sistema degradou
com segurança, mas por acidente feliz, não por desenho.

**Próximo passo, claro:** achar a borda direita da tabela na imagem em vez
de chutar uma fração. A tentativa de detectar por projeção de escuridão
esbarrou no fundo escuro da mesa e do espiral do caderno, que dominam as
colunas das pontas — precisa olhar só a faixa da folha e procurar réguas
finas, não regiões escuras.

### Três guardas, todas no código

Prompt deriva; código não. Na ordem em que agem:

1. anotação feita só de dígitos é tique, não anotação;
2. a mesma anotação em 6+ linhas cobrindo 60% da página é repetição;
3. a mesma anotação em 4 linhas SEGUIDAS é invenção em fila — foi assim que
   o modelo preencheu as linhas 21 a 27, em branco, de uma folha.

## Onde o leitor está (20/09/2026, fim do dia)

**Formulário impresso** — cinco fotos de celular de 22/07, contra as medições
já lançadas no banco (103 vacas):

| versão | cabeçalho | brinco | total | na revisão | erro certo |
|---|---|---|---|---|---|
| v6 | 2 de 5 | 87% | 53% | 82%, 10 toques | 12 |
| **v9** | **5 de 5** | 81% | **79%** | **90%**, 4 toques | 9 |

**Folha manuscrita** — 113 linhas de 25/08 contra o gabarito da planilha:
brinco 63%, nome 30%, manhã 76%, tarde 74%, total 68%, anotação 75%, com 7
linhas perdidas e 1 inventada. Identidade e contagem iguais às da v7; os
litros, ~5 pontos abaixo, sem explicação (ver known-issues).

**Margem do formulário impresso**, contra gabarito feito olhando as cinco
fotos (16 anotações reais): **6 linhas certas com o evento certo, 7 falsas**.
Começou o dia com uma seta virando 23 trocas de lote.

### A leitura de uma folha hoje

Cinco perguntas ao modelo, cada uma sobre um pedaço:

| pergunta | imagem | custo medido |
|---|---|---|
| formato (impresso ou manuscrito) | página | 3 s |
| cabeçalho (data e lote) | 32% do alto | 5 s |
| transcrição da tabela | página | 183 s |
| brincos | faixa esquerda | 22 s |
| margem | números + margem, colados | 7 s |

A transcrição da tabela é 83% do tempo. As quatro perguntas pequenas somam
menos de 40 s e são responsáveis pelos ganhos do dia.

### Três coisas que o modelo faz e o código precisa segurar

1. **Copia o exemplo da instrução.** A instrução listava "SECA" e "DOENTE"; o
   modelo devolveu as duas numa folha que não tem nenhuma. Instrução agora
   descreve a forma, não o conteúdo — e há teste para isso.
2. **Escreve "null" em vez de deixar vazio.** Virava produção fantasma.
   `_clean` trata vazio escrito por extenso como vazio.
3. **Inventa em fila.** Quando não sabe, repete: a mesma anotação em linhas
   seguidas, no rabo em branco do formulário. Duas guardas pegam isso (60%
   da página, ou 4 linhas seguidas iguais).

### O que ainda não funciona, com a causa medida

A tira da margem é fração fixa da largura, e cada foto enquadra a folha de um
jeito. Numa delas a tira caiu sobre a coluna TOTAL e o modelo respondeu os
litros; o leitor reconhece resposta numérica e pergunta de novo numa tira
colada à borda, mas naquela foto nem a segunda acerta. Tentar por geometria
(projeção de escuridão por coluna) esbarrou no fundo escuro da mesa e do
espiral do caderno, que dominam as colunas das pontas: seria preciso
endireitar a folha antes.
