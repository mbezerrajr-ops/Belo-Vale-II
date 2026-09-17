# vendor/ — bibliotecas de terceiros servidas junto com a plataforma

A plataforma usa duas bibliotecas na importação de leite (`Importar leite`):

| arquivo | biblioteca | versão | origem |
|---|---|---|---|
| `pdf.min.js` + `pdf.worker.min.js` | [pdf.js](https://mozilla.github.io/pdf.js/) (Mozilla, Apache-2.0) | 2.16.105 | cdnjs |
| `xlsx.full.min.js` | [SheetJS](https://sheetjs.com/) (Apache-2.0) | 0.18.5 | cdnjs |

Antes elas vinham do CDN (`cdnjs.cloudflare.com`). **O Artifact do Claude bloqueia
requisições a hosts externos** (CSP), então no link publicado os dois `<script src>`
falhavam em silêncio e o botão "Importar leite" não fazia nada. Agora são arquivos do
próprio artefato, referenciados por caminho relativo (`vendor/...`) — o que também faz a
importação funcionar ao abrir o HTML local sem internet.

## Os arquivos foram modificados (e por quê)

O publicador de artefatos recusa arquivos de texto com bytes de controle crus ou com o
caractere U+FFFD. Os builds originais têm os dois, dentro de literais de string (tabelas de
codepage do SheetJS, principalmente). Os arquivos aqui passaram por uma troca puramente
sintática, **sem mudança de semântica**:

- bytes de controle (`0x00`–`0x1F`, exceto tab/CR/LF) → escape `\xNN`;
- caractere U+FFFD literal → escape `\ufffd`.

Ambas as formas são equivalentes dentro de literais de string JavaScript. Depois da troca,
os três arquivos passam em `node --check`, e o `xlsx.full.min.js` foi validado com um
round-trip de planilha (`aoa_to_sheet` → `write` → `read` → `sheet_to_json`).

## Ao atualizar uma dessas bibliotecas

1. baixe o build novo do cdnjs para esta pasta;
2. rode `python normalize_for_artifact.py <arquivo.js>` (faz as duas trocas acima);
3. rode `node --check` nos três arquivos e um round-trip de planilha antes de publicar;
4. republique o artefato passando os arquivos de `vendor/` junto com o HTML.
