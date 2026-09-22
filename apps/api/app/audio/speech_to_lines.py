"""Da fala transcrita para as linhas de produção — código nosso, sem IA.

O funcionário fala em frase natural e o whisper transcreve. As três
gravações de teste do titular (21/09/2026) mostraram como a fala real é:

    Vaca 417 Pandora
    Produziu 5 litros pela manhã, 3 da tarde, totalizando 8 litros no total
    ...
    Vaca sabiá produziu 10 mais 5 litros, 15, deve ir para o primeiro lote.
    O número dela é 462, não lembro se eu falei.
    ...
    Bora lá, meu amigo, bora lá.

O whisper põe ponto NO MEIO de uma vaca, o brinco às vezes vem depois, em
outra frase, o nome vem junto, e há conversa no meio. Por isso o tradutor
não separa vaca por ponto final: **uma vaca começa numa âncora e vai até a
próxima**. As âncoras são:

1. **"vaca"**, seguida do brinco e/ou do nome, em qualquer ordem ("vaca 011,
   dominó", "vaca azeitona 117", "a vaca 389, da Agatha").
2. **Um número com cara de brinco** — três dígitos ou mais, ou zero à
   esquerda —, quando a vaca atual já tem brinco ou litros ("649, redonda,
   produziu 5 litros"). Litro de vaca nunca chega a 100 por dia; brinco
   desta fazenda tem três dígitos ou mais. É essa diferença que separa um do
   outro sem adivinhação.
3. **Nome no começo da frase seguido de "produziu"/"deu"** ("Pequina,
   pequina produziu 6,5 litros").

E o brinco que vem depois se prende à vaca atual: "o número dela é 462".

Dentro de cada vaca, "de manhã"/"pela manhã" e "à tarde"/"da tarde"/"pela
noite" reivindicam o litro mais próximo, e "no total"/"totalizando" o total.
Sem essas palavras: um número é o total; dois são manhã e tarde; três com
a + b = c são manhã, tarde e total ("10 mais 5 litros, 15").

O que sobra: ordem de secar ("deve ser secada", "o ideal é secar") vira
"secar", com o prazo se houver ("secar daqui a 7 meses"); lote vira "1º
lote"; o resto que tiver conteúdo vira observação com as palavras ditas. A
conversa ("bora lá", "não lembro se eu falei", "certo? obrigado") é
descartada — não é informação sobre vaca nenhuma, e cada frase dessas
viraria uma proposta inútil na caixa de Revisão.

Antes da primeira vaca é preâmbulo ("mensagem de teste"): descartado, a não
ser que traga litros — aí vira uma linha sem brinco, e a caixa pede a vaca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.portuguese_numbers import fold, parse_number

#: De onde veio a observação, para quem revisa saber o que está lendo.
AUDIO_ORIGIN = "No áudio"

#: Em silêncio o whisper pode repetir frases sem fim; acima disto não é fala.
MAX_COWS = 200

_COW = {"vaca"}
_MORNING = {"manha", "cedo"}
_AFTERNOON = {"tarde", "noite"}
_TOTAL = {"total", "totalizando", "totalizou"}
_MARKERS = _MORNING | _AFTERNOON | _TOTAL
_VERBS = {"deu", "da", "fez", "tirou", "foi", "produziu", "produzindo", "produz", "deram"}
#: Palavras que ligam a frase. Só saem das PONTAS do que sobra, nunca do
#: meio: "dá" (o verbo) e "da" (a preposição) são a mesma palavra sem acento,
#: e cortar no meio partiria "a bezerra da ponta curta" em dois.
_FILLER = _VERBS | {
    "litro", "litros", "l", "mais", "e", "a", "o", "as", "os", "de", "da", "do", "que", "ai",
    "entao", "vai", "para", "pra", "pro", "ir", "com", "na", "no", "em", "tambem", "ja",
    "hoje", "pela", "pelo", "por", "ela", "ele", "essa", "esta",
}
#: Conversa: palavras que não dizem nada sobre a vaca. Uma sobra feita só
#: disto (e de ligação) é descartada.
_DISCOURSE = {
    "assim", "como", "onde", "bom", "bem", "certo", "obrigado", "obrigada", "viu", "ne",
    "isso", "fim", "bora", "la", "meu", "minha", "amigo", "gente", "teste", "mensagem",
    "audio", "lembro", "lembrar", "falei", "falar", "eu", "se", "nao", "sim", "dividido",
    "voce", "sabe", "quanto", "sei", "acho", "tipo", "olha", "ok", "pronto", "beleza",
    "entendeu", "deve", "ser", "ideal", "precisa", "tem", "depois", "posteriormente",
    "disso", "logo", "aqui", "ao", "numero",
}
#: Unidades de tempo: o número antes delas é prazo, não litro ("daqui a 7 meses").
_TIME_UNITS = {
    "dia", "dias", "mes", "meses", "ano", "anos", "semana", "semanas", "hora", "horas",
    "minuto", "minutos",
}
_DRY = re.compile(r"(secar?|secad[ao]s?|secagem)")
_ORDINALS = {
    "primeiro": "1º", "primeira": "1º", "segundo": "2º", "segunda": "2º",
    "terceiro": "3º", "terceira": "3º", "quarto": "4º", "quarta": "4º",
    "quinto": "5º", "quinta": "5º", "sexto": "6º", "sexta": "6º",
}
_DIGIT_WORDS = {
    "zero": "0", "um": "1", "dois": "2", "tres": "3", "quatro": "4", "cinco": "5",
    "seis": "6", "sete": "7", "oito": "8", "nove": "9",
}
#: Palavras que, logo antes de uma âncora, fazem parte da vaca nova ("a vaca").
_ARTICLES = {"a", "o", "na", "no"}
#: O que pode ficar entre "número" e o brinco: "o número dela é 462",
#: "o número de pequina é 701".
_NUMBER_LINK = {"dela", "dele", "de", "da", "do", "e", "eh"}

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
    kind: str  # "num", "word" ou "stop"


@dataclass
class _Number:
    value: str
    first: int  # índice do primeiro token
    last: int  # índice do último token
    low_confidence: bool = False

    def brinco_like(self) -> bool:
        """Três dígitos ou mais, ou zero à esquerda: é brinco, não litro."""
        return self.value.isdigit() and (len(self.value) >= 3 or self.value.startswith("0"))


@dataclass
class _Cow:
    start: int
    brinco: _Number | None = None
    nome: str | None = None
    used: set[int] = field(default_factory=set)


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
    original = text or ""
    tokens = [
        _Token(m.group(), fold(m.group()), m.start(), m.end(), m.lastgroup or "word")
        for m in _TOKEN.finditer(original)
    ]
    numeros = _numbers(tokens)
    vacas = _cows(tokens, numeros)

    linhas: list[dict] = []
    anterior: str | None = None
    for k, vaca in enumerate(vacas[:MAX_COWS]):
        fim = vacas[k + 1].start if k + 1 < len(vacas) else len(tokens)
        linha = _line(original, tokens, numeros, vaca, fim, vacas)
        if linha is None:
            continue
        chave = fold(linha["trecho"])
        if chave == anterior:
            continue  # o transcritor repetiu a frase: é a mesma vaca
        anterior = chave
        linha["seq"] = str(len(linhas) + 1)
        linhas.append(linha)
    return {"data": None, "lote": None, "linhas": linhas}


# ------------------------------------------------------------------ números


def _numbers(tokens: list[_Token]) -> list[_Number]:
    """Os números da fala, em ordem. Um número nunca atravessa ponto final."""
    achados: list[_Number] = []
    i = 0
    while i < len(tokens):
        if tokens[i].kind == "stop":
            i += 1
            continue
        j = i
        while j < len(tokens) and tokens[j].kind != "stop":
            j += 1
        for numero in _numbers_in(tokens[i:j]):
            numero.first += i
            numero.last += i
            achados.append(numero)
        i = j
    return achados


def _numbers_in(frase: list[_Token]) -> list[_Number]:
    palavras = [t.text for t in frase]
    achados: list[_Number] = []
    i = 0
    while i < len(frase):
        # "quatro nove sete": brinco dito algarismo por algarismo
        j = i
        while j < len(frase) and frase[j].folded in _DIGIT_WORDS:
            j += 1
        if j - i >= 3:
            valor = "".join(_DIGIT_WORDS[t.folded] for t in frase[i:j])
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


# ------------------------------------------------------------------- vacas


def _cows(tokens: list[_Token], numeros: list[_Number]) -> list[_Cow]:
    """Onde começa cada vaca, com o brinco e o nome ditos na âncora."""
    por_inicio = {n.first: n for n in numeros}
    vacas: list[_Cow] = []
    atual: _Cow | None = None
    inicio_de_frase = True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.kind == "stop":
            inicio_de_frase = True
            i += 1
            continue

        # Âncora 1: "vaca", com brinco e/ou nome em qualquer ordem.
        if token.folded in _COW:
            atual = _open(vacas, tokens, i)
            atual.used.add(i)
            i = _read_identity(tokens, por_inicio, i + 1, atual)
            inicio_de_frase = False
            continue

        # O brinco que vem depois: "o número dela é 462".
        if token.folded == "numero":
            numero = _number_after_numero(tokens, por_inicio, i)
            if numero is not None and atual is not None and atual.brinco is None:
                atual.brinco = numero
                atual.used.update(range(i, numero.last + 1))
                i = numero.last + 1
                inicio_de_frase = False
                continue

        # Âncora 2: número com cara de brinco, quando a vaca atual já tem
        # brinco ou já tem litros.
        if i in por_inicio:
            numero = por_inicio[i]
            ocupada = atual is not None and (
                atual.brinco is not None or _has_liters(numeros, atual.start, i, tokens)
            )
            if numero.brinco_like() and (atual is None or ocupada):
                atual = _open(vacas, tokens, i)
                atual.brinco = numero
                atual.used.update(range(numero.first, numero.last + 1))
                i = _read_name(tokens, numero.last + 1, atual)
            else:
                i = numero.last + 1
            inicio_de_frase = False
            continue

        # Âncora 3: nome no começo da frase seguido de "produziu".
        if (
            inicio_de_frase
            and token.kind == "word"
            and _is_name_word(token)
            and _verb_follows(tokens, i)
            and (atual is None or _has_liters(numeros, atual.start, i, tokens))
        ):
            atual = _open(vacas, tokens, i)
            atual.nome = token.text.upper()
            atual.used.add(i)
            # "Pequina, pequina produziu": o nome repetido é o mesmo nome.
            if i + 1 < len(tokens) and tokens[i + 1].folded == token.folded:
                atual.used.add(i + 1)
                i += 1
        inicio_de_frase = False
        i += 1

    # Preâmbulo: o que vem antes da primeira vaca só vale se trouxer litros.
    primeira = vacas[0].start if vacas else len(tokens)
    if primeira > 0 and _has_liters(numeros, 0, primeira, tokens):
        vacas.insert(0, _Cow(start=0))
    return vacas


def _open(vacas: list[_Cow], tokens: list[_Token], i: int) -> _Cow:
    """Uma vaca nova começando em `i` — ou no artigo logo antes ("a vaca")."""
    inicio = i - 1 if i > 0 and tokens[i - 1].folded in _ARTICLES else i
    if vacas and vacas[-1].start >= inicio:
        inicio = i
    vaca = _Cow(start=inicio)
    vacas.append(vaca)
    return vaca


def _read_identity(tokens: list[_Token], por_inicio: dict[int, _Number], j: int, vaca: _Cow) -> int:
    """Depois de "vaca": o brinco e o nome, na ordem em que vierem."""
    j = _skip(tokens, j, {"a", "o", "da", "de", "do"})
    if j in por_inicio and por_inicio[j].value.isdigit():
        numero = por_inicio[j]
        vaca.brinco = numero
        vaca.used.update(range(numero.first, numero.last + 1))
        return _read_name(tokens, numero.last + 1, vaca)
    j = _read_name(tokens, j, vaca)
    if vaca.nome is not None and j in por_inicio and por_inicio[j].brinco_like():
        numero = por_inicio[j]
        vaca.brinco = numero
        vaca.used.update(range(numero.first, numero.last + 1))
        return numero.last + 1
    return j


def _read_name(tokens: list[_Token], j: int, vaca: _Cow) -> int:
    """O nome dito junto da âncora: "dominó", "da Agatha", "ponta curta"."""
    j = _skip(tokens, j, {"da", "do", "de", "a", "o"})
    if j < len(tokens) and _is_name_word(tokens[j]):
        partes = [j]
        if j + 1 < len(tokens) and _is_name_word(tokens[j + 1]):
            partes.append(j + 1)
        vaca.nome = " ".join(tokens[p].text for p in partes).upper()
        vaca.used.update(partes)
        return partes[-1] + 1
    return j


def _is_name_word(token: _Token) -> bool:
    return (
        token.kind == "word"
        and token.folded not in _FILLER
        and token.folded not in _DISCOURSE
        and token.folded not in _MARKERS
        and token.folded not in _COW
        and token.folded not in _TIME_UNITS
        and not _DRY.fullmatch(token.folded)
    )


def _skip(tokens: list[_Token], j: int, palavras: set[str]) -> int:
    while j < len(tokens) and tokens[j].kind == "word" and tokens[j].folded in palavras:
        j += 1
    return j


def _verb_follows(tokens: list[_Token], i: int) -> bool:
    return any(
        tokens[k].folded in _VERBS - {"da"}
        for k in range(i + 1, min(i + 3, len(tokens)))
        if tokens[k].kind != "stop"
    )


def _number_after_numero(tokens: list[_Token], por_inicio: dict[int, _Number], i: int) -> _Number | None:
    """ "número dela é 462" → 462. Entre "número" e o brinco só cabem palavras
    de ligação e, no máximo, um nome ("o número de pequina é 701")."""
    nomes = 0
    for k in range(i + 1, min(i + 6, len(tokens))):
        if tokens[k].kind == "stop":
            return None
        if k in por_inicio:
            return por_inicio[k] if por_inicio[k].value.isdigit() else None
        if tokens[k].folded in _NUMBER_LINK:
            continue
        nomes += 1
        if nomes > 1:
            return None
    return None


def _is_liter(numero: _Number, tokens: list[_Token]) -> bool:
    if numero.brinco_like():
        return False
    depois = numero.last + 1
    return not (depois < len(tokens) and tokens[depois].folded in _TIME_UNITS)


def _has_liters(numeros: list[_Number], de: int, ate: int, tokens: list[_Token]) -> bool:
    return any(de <= n.first < ate and _is_liter(n, tokens) for n in numeros)


# ------------------------------------------------------------------- linhas


def _line(
    original: str,
    tokens: list[_Token],
    numeros: list[_Number],
    vaca: _Cow,
    fim: int,
    vacas: list[_Cow],
) -> dict | None:
    brincos = {id(v.brinco) for v in vacas if v.brinco is not None}
    litros = [
        n for n in numeros
        if vaca.start <= n.first < fim and id(n) not in brincos and _is_liter(n, tokens)
    ]
    usados = set(vaca.used)

    papeis = _periods(tokens, vaca.start, fim, litros, usados)
    manha = next((litros[k].value for k, p in papeis.items() if p == "manha"), None)
    tarde = next((litros[k].value for k, p in papeis.items() if p == "tarde"), None)
    total = next((litros[k].value for k, p in papeis.items() if p == "total"), None)
    # Pela posição, não pelo valor: em "deu 2 e 2" manhã e tarde são iguais.
    livres = [n for k, n in enumerate(litros) if k not in papeis]

    if manha is None and tarde is None and total is None:
        if len(livres) == 1:
            total, livres = livres[0].value, []
        elif len(livres) >= 3 and _dec(livres[0].value) + _dec(livres[1].value) == _dec(livres[2].value):
            # "10 mais 5 litros, 15": manhã, tarde e o total conferido
            manha, tarde, total = livres[0].value, livres[1].value, livres[2].value
            livres = livres[3:]
        elif len(livres) >= 2:
            manha, tarde, livres = livres[0].value, livres[1].value, livres[2:]
    elif (manha is None) != (tarde is None) and livres:
        # "deu 18 de manhã e 15": o que sobrou é o outro período
        if manha is None:
            manha = livres[0].value
        else:
            tarde = livres[0].value
        livres = livres[1:]
    if manha is not None and tarde is not None and total is None:
        total = _format(_dec(manha) + _dec(tarde))

    for numero in litros:
        if numero not in livres:
            usados.update(range(numero.first, numero.last + 1))

    anotacao = _leftover(tokens, vaca.start, fim, usados)
    if vaca.brinco is None and vaca.nome is None and not litros and not anotacao:
        return None

    linha: dict = {
        "brinco": vaca.brinco.value if vaca.brinco else None,
        "nome": vaca.nome,
        "manha": manha,
        "tarde": tarde,
        "total": total,
        "anotacao": anotacao,
        "trecho": _evidence(original, tokens, vaca.start, fim),
    }
    if vaca.brinco is not None and vaca.brinco.low_confidence:
        linha["confianca"] = {"brinco": 0.5}
    return linha


def _periods(
    tokens: list[_Token], de: int, ate: int, litros: list[_Number], usados: set[int]
) -> dict[int, str]:
    """Cada palavra de período reivindica o litro mais próximo: primeiro à
    esquerda (em até 4 palavras), senão à direita."""
    reivindicados: dict[int, str] = {}  # índice em `litros` → papel
    for i in range(de, ate):
        folded = tokens[i].folded
        if folded in _MORNING:
            papel = "manha"
        elif folded in _AFTERNOON:
            papel = "tarde"
        elif folded in _TOTAL:
            papel = "total"
        else:
            continue
        usados.add(i)
        if papel in reivindicados.values():
            continue
        escolhido = _nearest(i, litros, reivindicados)
        if escolhido is not None:
            reivindicados[escolhido] = papel
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


# ---------------------------------------------------------------- anotação


def _leftover(tokens: list[_Token], de: int, ate: int, usados: set[int]) -> str | None:
    """O que foi dito e não virou brinco, nome nem litro."""
    trechos: list[list[_Token]] = [[]]
    for i in range(de, ate):
        if i in usados or tokens[i].kind == "stop":
            trechos.append([])
        else:
            trechos[-1].append(tokens[i])
    partes = [p for p in (_meaning(t) for t in trechos) if p]
    return "; ".join(dict.fromkeys(partes)) or None


def _meaning(trecho: list[_Token]) -> str | None:
    """O que um pedaço de fala quer dizer, se quiser dizer alguma coisa."""
    trecho = _trim(trecho, _FILLER)
    if not trecho:
        return None
    dobradas = [t.folded for t in trecho]

    # Ordem de secagem, com o prazo se houver: "secar daqui a 7 meses".
    for k, palavra in enumerate(dobradas):
        if _DRY.fullmatch(palavra):
            prazo = _trim(trecho[k + 1 :], _FILLER | _DISCOURSE)
            return "secar" + (" " + _text(prazo) if prazo else "")

    # Troca de lote: "primeiro lote" → "1º lote"; "lote 3" → "lote 3".
    for k, palavra in enumerate(dobradas):
        if palavra.startswith("lote"):
            if k > 0 and dobradas[k - 1] in _ORDINALS:
                return f"{_ORDINALS[dobradas[k - 1]]} lote"
            if k > 0 and trecho[k - 1].kind == "num":
                return f"{trecho[k - 1].text}º lote"
            if k + 1 < len(trecho) and trecho[k + 1].kind == "num":
                return f"lote {trecho[k + 1].text}"

    # O resto só fica se disser algo além de conversa. Palavra de tempo
    # sozinha também não diz ("no total do dia"): prazo só vale junto de uma
    # ordem, e esse caso já foi tratado acima.
    if any(
        t.kind == "word" and t.folded not in _FILLER | _DISCOURSE | _TIME_UNITS for t in trecho
    ):
        return _text(trecho)
    return None


def _trim(trecho: list[_Token], palavras: set[str]) -> list[_Token]:
    while trecho and trecho[0].folded in palavras:
        trecho = trecho[1:]
    while trecho and trecho[-1].folded in palavras:
        trecho = trecho[:-1]
    return trecho


def _text(trecho: list[_Token]) -> str:
    return " ".join(t.text for t in trecho)


def _evidence(original: str, tokens: list[_Token], de: int, ate: int) -> str:
    """O trecho como foi transcrito, com acento e maiúscula, incluindo o ponto
    final que o encerra."""
    palavras = [t for t in tokens[de:ate] if t.kind != "stop"]
    if not palavras:
        return ""
    fim = palavras[-1].end
    if fim < len(original) and original[fim] in ".!?;":
        fim += 1
    return " ".join(original[palavras[0].start : fim].split())


def _dec(texto: str) -> Decimal:
    return Decimal(texto.replace(",", "."))


def _format(valor: Decimal) -> str:
    if valor == valor.to_integral_value():
        return str(int(valor))
    return format(valor.normalize(), "f").replace(".", ",")
