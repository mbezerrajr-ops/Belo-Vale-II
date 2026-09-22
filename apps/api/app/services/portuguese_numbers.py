"""Número dito em português, do jeito que chega da transcrição.

O whisper converte quase tudo em algarismo ("quatrocentos e noventa e sete"
vira "497"), mas não tudo: "dez e meio" sai "10 e meio", e no barulho do
curral a conversão falha mais. Então este leitor entende as três formas —
algarismo, por extenso e misturado — e devolve sempre texto no formato
brasileiro ("18", "18,5"), que é o que o resto do sistema já sabe ler.

Duas regras protegem o brinco, que é o erro mais caro:

- **"meia" sozinha não é lida.** Na fala de fazenda ela tanto é meio litro
  quanto o algarismo 6 ("meia dúzia", ditado de número). Só "e meio"/"e meia"
  depois de um número vira ",5".
- **"e" só junta o que a gramática junta.** "dezoito e quinze" são dois
  números (manhã e tarde), não um; "quatrocentos e noventa e sete" é um só.
  O "e" é engolido apenas quando o que vem depois cabe na casa que falta.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
}
_TEENS = {
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
    "quinze": 15, "dezesseis": 16, "dezasseis": 16, "dezessete": 17, "dezassete": 17,
    "dezoito": 18, "dezenove": 19, "dezanove": 19,
}
_TENS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    "setenta": 70, "oitenta": 80, "noventa": 90,
}
_HUNDREDS = {
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300,
    "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500,
    "quinhentas": 500, "seiscentos": 600, "seiscentas": 600, "setecentos": 700,
    "setecentas": 700, "oitocentos": 800, "oitocentas": 800, "novecentos": 900,
    "novecentas": 900,
}
_HALF = {"meio", "meia"}
_DECIMAL_MARK = {"virgula", "ponto"}

#: "1.015" é milhar com ponto (brinco de quatro dígitos, do jeito que o
#: whisper escreve em português); "12.5" e "12,5" são decimais.
_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def parse_number(words: list[str], start: int) -> tuple[str | None, int]:
    """O número que começa em `words[start]`: (texto no formato brasileiro,
    quantas palavras ele ocupou). Sem número ali: (None, 0)."""
    folded = [fold(w) for w in words]
    inteiro, fim = _integer(folded, words, start)
    # Algarismo puro sai como foi escrito: "011" é brinco com zero à esquerda,
    # e o cadastro guarda assim.
    cru = words[start] if start < len(words) else ""
    if re.fullmatch(r"\d+", cru) and fim == start + 1 and not _continues(folded, fim):
        return cru, 1
    if inteiro is None:
        return None, 0
    valor = inteiro
    # "dezoito e meio"
    if fim + 1 < len(folded) and folded[fim] == "e" and folded[fim + 1] in _HALF:
        if valor == valor.to_integral_value():
            return _format(valor + Decimal("0.5")), fim + 2 - start
    # "vinte e dois vírgula cinco": a parte depois da vírgula vale como escrita
    if fim < len(folded) and folded[fim] in _DECIMAL_MARK and valor == valor.to_integral_value():
        fracao, depois = _integer(folded, words, fim + 1)
        if fracao is not None and fracao == fracao.to_integral_value():
            return _format(Decimal(f"{int(valor)}.{int(fracao)}")), depois - start
    return _format(valor), fim - start


def _continues(folded: list[str], fim: int) -> bool:
    """O número segue depois daqui? ("e meio", "vírgula cinco")."""
    if fim < len(folded) and folded[fim] in _DECIMAL_MARK:
        return True
    return fim + 1 < len(folded) and folded[fim] == "e" and folded[fim + 1] in _HALF


def _integer(folded: list[str], words: list[str], i: int) -> tuple[Decimal | None, int]:
    """Um número inteiro (ou um algarismo já com decimal) a partir de `i`."""
    if i >= len(folded):
        return None, i
    raw = words[i]
    if _THOUSANDS.fullmatch(raw):
        return Decimal(raw.replace(".", "")), i + 1
    if _DIGITS.fullmatch(raw):
        return Decimal(raw.replace(",", ".")), i + 1

    total = 0
    grupo, j = _group(folded, words, i)
    if folded[i] == "mil" or (grupo is not None and j < len(folded) and folded[j] == "mil"):
        milhar = 1 if folded[i] == "mil" else grupo
        j = i + 1 if folded[i] == "mil" else j + 1
        total = milhar * 1000
        # "mil e duzentos", "mil duzentos"
        k = j + 1 if j < len(folded) and folded[j] == "e" else j
        resto, depois = _group(folded, words, k)
        if resto is not None:
            return Decimal(total + resto), depois
        return Decimal(total), j
    if grupo is None:
        return None, i
    return Decimal(grupo), j


def _group(folded: list[str], words: list[str], i: int) -> tuple[int | None, int]:
    """Um grupo de 0 a 999 por extenso, com algarismo aceito na casa que falta
    ("quatrocentos e 97")."""
    if i >= len(folded):
        return None, i
    palavra = folded[i]
    if palavra in _HUNDREDS:
        valor = _HUNDREDS[palavra]
        j = i + 1
        if palavra == "cem":  # "cem" não leva complemento; "cento e um" leva
            return valor, j
        resto, depois = _below_hundred(folded, words, _skip_e(folded, j))
        if resto is not None:
            return valor + resto, depois
        return valor, j
    return _below_hundred(folded, words, i)


def _below_hundred(folded: list[str], words: list[str], i: int) -> tuple[int | None, int]:
    if i >= len(folded):
        return None, i
    palavra = folded[i]
    if palavra in _TENS:
        valor = _TENS[palavra]
        j = i + 1
        k = _skip_e(folded, j)
        if k != j and k < len(folded):
            if folded[k] in _UNITS and _UNITS[folded[k]] > 0:
                return valor + _UNITS[folded[k]], k + 1
            if re.fullmatch(r"[1-9]", words[k]):  # "vinte e 2"
                return valor + int(words[k]), k + 1
        return valor, j
    if palavra in _TEENS:
        return _TEENS[palavra], i + 1
    if palavra in _UNITS:
        return _UNITS[palavra], i + 1
    if re.fullmatch(r"\d{1,2}", words[i]):  # a casa que faltava veio em algarismo
        return int(words[i]), i + 1
    return None, i


def _skip_e(folded: list[str], j: int) -> int:
    """Pula o "e" de ligação, se houver. Quem chama decide se o que vem depois
    cabe na casa; se não couber, o "e" fica para o próximo número."""
    return j + 1 if j < len(folded) and folded[j] == "e" else j


def _format(valor: Decimal) -> str:
    if valor == valor.to_integral_value():
        return str(int(valor))
    texto = format(valor.normalize(), "f")
    return texto.replace(".", ",")
