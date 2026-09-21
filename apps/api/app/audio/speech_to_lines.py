"""Da fala transcrita para as linhas de produção — código nosso, sem IA.

O funcionário fala em frase natural ("a quatrocentos e noventa e sete deu
dezoito litros de manhã e quinze à tarde"). O whisper transcreve, e costuma
entregar algarismos e um ponto final entre as vacas:

    A 497 deu 18 litros de manhã e 15 à tarde.
    A 389 deu 10 e meio de manhã e 12,5 à tarde.

(saída real na RX 7600, em 21/09/2026). Mas nem sempre: "10 e meio" veio
misturado, e no barulho do curral a conversão falha mais. Este tradutor
entende as duas coisas e devolve a mesma estrutura que a leitura da folha
devolve — uma linha por vaca —, para que daí em diante o caminho seja um só.

As regras, em ordem:

1. **Uma vaca por trecho.** Ponto final separa. Dentro da frase, uma nova
   vaca começa em "a"/"vaca"/"brinco" seguido de número, desde que o trecho
   atual já tenha brinco e litros ("a 497 deu 18 e 15, a 389 deu 20").
2. **O brinco é o número logo depois de "a"/"vaca"/"brinco"**; sem isso, o
   primeiro número de um trecho que tem mais de um. Número sozinho, sem
   âncora, é litro de ninguém: a linha fica sem brinco e a caixa pede a vaca.
3. **"de manhã" e "à tarde" reivindicam o número mais próximo**, à esquerda
   primeiro. Dois números sem período são manhã e tarde, nessa ordem — é
   assim que se fala no curral ("deu dezoito e quinze"). Um número só é o
   total, e não se inventa parcela.
4. **O que sobra vira anotação**, com as palavras como foram ditas. "Secar" e
   "terceiro lote" são reconhecidos depois, pelo mesmo tradutor da folha; o
   resto vira observação. Nada se perde em silêncio.
5. **Guardas contra delírio do transcritor**: trechos repetidos seguidos
   contam uma vez só (em silêncio o whisper entra em laço), há um teto de
   trechos, e uma gravação que é só frase-fantasma de legenda não gera nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.services.portuguese_numbers import fold, parse_number

#: De onde veio a observação, para quem revisa saber o que está lendo.
AUDIO_ORIGIN = "No áudio"

#: Em silêncio o whisper pode repetir frases sem fim; acima disto não é fala.
MAX_SEGMENTS = 200

#: Palavras que apontam o brinco: "a 497", "vaca 497", "brinco 497".
_IDENTITY = {"a", "o", "vaca", "brinco", "numero", "na", "no", "da", "do"}
#: Onde começa outra vaca, além de "a"/"vaca"/"brinco".
_NEXT = {"proxima", "depois", "agora"}
_MORNING = {"manha", "cedo"}
_AFTERNOON = {"tarde"}
_TOTAL = {"total"}
#: Palavras que ligam a frase e não significam nada sozinhas. Só são tiradas
#: das PONTAS do que sobra, nunca do meio: "dá" (o verbo) e "da" (a
#: preposição) são a mesma palavra sem acento, e cortar no meio partiria
#: "a bezerra da ponta curta" em dois pedaços.
_PRODUCTION = {"deu", "da", "fez", "tirou", "foi", "produziu", "deram", "litro", "litros", "l"}
_FILLER = _PRODUCTION | {
    "e", "a", "o", "as", "os", "de", "da", "do", "que", "ai", "entao", "vai", "para", "pra",
    "pro", "ir", "com", "na", "no", "em", "tambem", "ja", "hoje", "ela", "essa", "esta",
}
_ORDINALS = {
    "primeiro": "1º", "primeira": "1º", "segundo": "2º", "segunda": "2º",
    "terceiro": "3º", "terceira": "3º", "quarto": "4º", "quarta": "4º",
    "quinto": "5º", "quinta": "5º", "sexto": "6º", "sexta": "6º",
}
_DIGIT_WORDS = {
    "zero": "0", "um": "1", "dois": "2", "tres": "3", "quatro": "4", "cinco": "5",
    "seis": "6", "sete": "7", "oito": "8", "nove": "9",
}

#: Frases que o whisper inventa sobre silêncio: legenda de vídeo, despedida.
_PHANTOMS = (
    "legendas pela comunidade amara org",
    "obrigado por assistir",
    "obrigada por assistir",
    "inscreva se no canal",
    "tchau",
    "musica",
)

_TOKEN = re.compile(
    r"(?P<num>\d{1,3}(?:\.\d{3})+(?!\d)|\d+(?:[.,]\d+)?)"
    r"|(?P<word>[^\W\d_]+)"
    r"|(?P<stop>[.!?;\n])"
)


@dataclass(frozen=True)
class _Token:
    text: str
    folded: str
    start: int
    end: int


@dataclass
class _Number:
    value: str
    first: int  # índice do primeiro token
    last: int  # índice do último token
    low_confidence: bool = False


def is_phantom(text: str) -> bool:
    """A gravação inteira é só frase-fantasma do transcritor (ou nada)?"""
    limpo = " ".join(re.findall(r"[a-z0-9]+", fold(text or "")))
    for frase in _PHANTOMS:
        limpo = limpo.replace(frase, " ")
    return not limpo.strip()


def speech_to_lines(text: str) -> dict:
    """A fala transcrita vira a estrutura intermediária da leitura:
    `{"data": None, "lote": None, "linhas": [...]}`, uma linha por vaca.

    A data fica vazia: a fala não tem cabeçalho, e quem chama informa a data
    da fazenda.
    """
    linhas: list[dict] = []
    anterior: str | None = None
    for sentence in _sentences(text or ""):
        for trecho in _cows(sentence):
            if len(linhas) >= MAX_SEGMENTS:
                break
            linha = _line(text, trecho)
            if linha is None:
                continue
            chave = fold(linha["trecho"])
            if chave == anterior:
                continue  # o transcritor repetiu a frase: é a mesma vaca
            anterior = chave
            linha["seq"] = str(len(linhas) + 1)
            linhas.append(linha)
    return {"data": None, "lote": None, "linhas": linhas}


def _sentences(text: str) -> list[list[_Token]]:
    """Os tokens, cortados em frases pelo ponto final (e afins)."""
    frases: list[list[_Token]] = [[]]
    for match in _TOKEN.finditer(text):
        if match.lastgroup == "stop":
            frases.append([])
            continue
        frases[-1].append(_Token(match.group(), fold(match.group()), match.start(), match.end()))
    return [frase for frase in frases if frase]


def _numbers(tokens: list[_Token]) -> list[_Number]:
    """Os números da frase, em ordem, com o trecho que cada um ocupa."""
    palavras = [t.text for t in tokens]
    achados: list[_Number] = []
    i = 0
    while i < len(tokens):
        # "quatro nove sete": brinco dito algarismo por algarismo
        j = i
        while j < len(tokens) and tokens[j].folded in _DIGIT_WORDS:
            j += 1
        if j - i >= 3:
            valor = "".join(_DIGIT_WORDS[t.folded] for t in tokens[i:j])
            achados.append(_Number(valor, i, j - 1, low_confidence=True))
            i = j
            continue
        valor, usadas = parse_number(palavras, i)
        if valor is not None:
            achados.append(_Number(valor, i, i + usadas - 1))
            i += usadas
        else:
            i += 1
    return achados


def _cows(tokens: list[_Token]) -> list[list[_Token]]:
    """A frase cortada em uma vaca por trecho."""
    numeros = _numbers(tokens)
    inicio_de_numero = {n.first for n in numeros}
    cortes = [0]
    vistos = 0  # números no trecho atual
    for i, token in enumerate(tokens):
        if i in inicio_de_numero:
            vistos += 1
        abre_vaca = (
            (token.folded in _IDENTITY or token.folded in _NEXT)
            and (i + 1) in inicio_de_numero
            and vistos >= 2
        )
        if abre_vaca:
            cortes.append(i)
            vistos = 0
    cortes.append(len(tokens))
    return [tokens[a:b] for a, b in zip(cortes, cortes[1:]) if tokens[a:b]]


def _line(original: str, tokens: list[_Token]) -> dict | None:
    numeros = _numbers(tokens)
    usados: set[int] = set()  # tokens que já significam alguma coisa

    brinco: _Number | None = None
    if numeros:
        primeiro = numeros[0]
        ancorado = primeiro.first > 0 and tokens[primeiro.first - 1].folded in _IDENTITY
        if (ancorado or len(numeros) >= 2) and "," not in primeiro.value:
            brinco = primeiro
            if ancorado:
                usados.add(primeiro.first - 1)
    litros = [n for n in numeros if n is not brinco]

    papeis = _periods(tokens, litros, usados)  # índice em `litros` → papel
    manha = next((litros[k].value for k, p in papeis.items() if p == "manha"), None)
    tarde = next((litros[k].value for k, p in papeis.items() if p == "tarde"), None)
    total = next((litros[k].value for k, p in papeis.items() if p == "total"), None)
    # Pela posição, não pelo valor: em "deu 2 e 2" manhã e tarde são iguais.
    livres = [n for k, n in enumerate(litros) if k not in papeis]
    if manha is None and tarde is None and total is None:
        if len(livres) == 1:
            total = livres[0].value
            livres = []
        elif len(livres) >= 2:
            manha, tarde = livres[0].value, livres[1].value
            livres = livres[2:]
    elif (manha is None) != (tarde is None) and total is None and len(livres) == 1:
        # "deu 18 de manhã e 15": o que sobrou é o outro período
        if manha is None:
            manha = livres[0].value
        else:
            tarde = livres[0].value
        livres = []
    if manha is not None and tarde is not None:
        total = _format(_decimal(manha) + _decimal(tarde))

    for numero in numeros:
        if numero not in livres:
            usados.update(range(numero.first, numero.last + 1))
    for i, token in enumerate(tokens):
        if token.folded in _MORNING | _AFTERNOON | _TOTAL:
            usados.add(i)

    anotacao = _leftover(tokens, usados)
    if brinco is None and not litros and not anotacao:
        return None

    linha: dict = {
        "brinco": brinco.value if brinco else None,
        "nome": None,
        "manha": manha,
        "tarde": tarde,
        "total": total,
        "anotacao": anotacao,
        "trecho": _evidence(original, tokens),
    }
    if brinco is not None and brinco.low_confidence:
        linha["confianca"] = {"brinco": 0.5}
    return linha


def _periods(tokens: list[_Token], litros: list[_Number], usados: set[int]) -> dict[int, str]:
    """Cada palavra de período reivindica o litro mais próximo: primeiro à
    esquerda (em até 4 palavras), senão à direita."""
    reivindicados: dict[int, str] = {}  # índice do número em `litros` → papel
    for i, token in enumerate(tokens):
        if token.folded in _MORNING:
            papel = "manha"
        elif token.folded in _AFTERNOON:
            papel = "tarde"
        elif token.folded in _TOTAL:
            papel = "total"
        else:
            continue
        if papel in reivindicados.values():
            continue
        escolhido = _nearest(i, litros, reivindicados)
        if escolhido is not None:
            reivindicados[escolhido] = papel
            usados.add(i)
    return reivindicados


def _nearest(posicao: int, litros: list[_Number], tomados: dict[int, str]) -> int | None:
    esquerda = [
        (posicao - n.last, k) for k, n in enumerate(litros)
        if k not in tomados and n.last < posicao and posicao - n.last <= 4
    ]
    if esquerda:
        return min(esquerda)[1]
    direita = [
        (n.first - posicao, k) for k, n in enumerate(litros)
        if k not in tomados and n.first > posicao and n.first - posicao <= 4
    ]
    return min(direita)[1] if direita else None


def _leftover(tokens: list[_Token], usados: set[int]) -> str | None:
    """O que foi dito e não virou brinco nem litro: fica como anotação, com as
    palavras como foram ditas, sem as de ligação nas pontas."""
    trechos: list[list[_Token]] = [[]]
    for i, token in enumerate(tokens):
        if i in usados:
            trechos.append([])
        else:
            trechos[-1].append(token)
    partes = []
    for trecho in trechos:
        while trecho and trecho[0].folded in _FILLER:
            trecho = trecho[1:]
        while trecho and trecho[-1].folded in _FILLER:
            trecho = trecho[:-1]
        if not trecho or not any(t.folded.isalpha() for t in trecho):
            continue
        palavras = []
        for k, token in enumerate(trecho):
            proxima = trecho[k + 1].folded if k + 1 < len(trecho) else ""
            if token.folded in _ORDINALS and proxima.startswith("lote"):
                palavras.append(_ORDINALS[token.folded])
            else:
                palavras.append(token.text)
        partes.append(" ".join(palavras))
    return "; ".join(partes) or None


def _evidence(original: str, tokens: list[_Token]) -> str:
    """O trecho como foi transcrito, com acento e maiúscula, incluindo o ponto
    final que o encerra."""
    fim = tokens[-1].end
    if fim < len(original) and original[fim] in ".!?;":
        fim += 1
    return original[tokens[0].start : fim].strip()


def _decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(",", "."))


def _format(valor: Decimal) -> str:
    if valor == valor.to_integral_value():
        return str(int(valor))
    return format(valor.normalize(), "f").replace(".", ",")
