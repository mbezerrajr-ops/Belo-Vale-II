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
