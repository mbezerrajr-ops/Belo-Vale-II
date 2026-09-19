# Status do provedor de visão/OCR

Esta é uma classificação explícita, para não confundir "implementação
estruturalmente pronta" com "integração externa validada".

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
