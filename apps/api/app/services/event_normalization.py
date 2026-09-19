"""Normalização dos eventos lidos por um leitor (visão, transcrição).

Recebe os campos como vieram — texto solto, do caderno ou da fala — e devolve
o `payload` no formato do domínio mais uma lista de alertas. A regra é a
mesma da importação de planilhas: o que não dá para ler fica vazio, com o
motivo, e quem revisa decide. Nada é completado por palpite.

Cada tipo de evento tem um payload fixo:

- ``production``: ``measured_on``, ``producao`` (litros)
- ``calving`` (parto): ``calved_on``
- ``dry_off`` (secagem): ``dried_on``
- ``exit`` (baixa): ``exited_on``, ``reason``, ``notes``
- ``lot_change``: ``lote``, ``valid_from``
- ``note`` (observação): ``text``

DEL não é um campo: é calculado da data do parto. Quando o leitor encontra
"DEL 120", a proposta vira uma data de parto calculada, com alerta — o
sistema nunca guarda um DEL solto que discorde da data do parto.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from app.core.farm_clock import farm_today
from app.services.production_entry import MAX_LITERS
from app.services.production_files import parse_number_br

EVENT_TYPES = ("production", "calving", "dry_off", "exit", "lot_change", "note")

#: Data mais antiga que isto (em dias) vira alerta para conferir o ano.
OLD_DATE_DAYS = 180

#: Palavras de baixa, sem acento e em minúsculas, para o motivo fechado.
_EXIT_WORDS: tuple[tuple[str, str], ...] = (
    ("vend", "venda"),
    ("morr", "morte"),
    ("mort", "morte"),
    ("obito", "morte"),
    ("descart", "descarte"),
    ("doa", "doacao"),
    ("outro", "outro"),
)

_RELATIVE_DAYS = {"hoje": 0, "ontem": 1, "anteontem": 2}

_FULL_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DAY_MONTH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})$")


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_event_date(raw: str | None, *, reference: date | None) -> date | None:
    """Data lida do caderno ou da fala. Ilegível ou impossível → ``None``.

    "25/08" usa o ano da referência — ou o anterior, se a data cairia depois
    dela (em agosto, "15/12" só pode ser o dezembro passado). "ontem" conta a
    partir da referência, que é o dia do registro.
    """
    if raw is None:
        return None
    text = _fold(str(raw))
    if not text:
        return None
    if text in _RELATIVE_DAYS:
        return None if reference is None else reference - timedelta(days=_RELATIVE_DAYS[text])

    if match := _ISO_DATE.match(text):
        return _make(int(match[1]), int(match[2]), int(match[3]))
    if match := _FULL_DATE.match(text):
        year = int(match[3])
        if year < 100:
            year += 2000
        return _make(year, int(match[2]), int(match[1]))
    if match := _DAY_MONTH.match(text):
        if reference is None:
            return None
        candidate = _make(reference.year, int(match[2]), int(match[1]))
        if candidate is not None and candidate > reference:
            candidate = _make(reference.year - 1, int(match[2]), int(match[1]))
        return candidate
    return None


def _first(fields: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = fields.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


class _Alerts:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, code: str, message: str, field: str | None = None) -> None:
        alert = {"code": code, "message": message}
        if field:
            alert["field"] = field
        self.items.append(alert)


def _date_field(
    fields: dict[str, Any],
    names: tuple[str, ...],
    *,
    reference: date | None,
    target: str,
    alerts: _Alerts,
    label: str,
) -> str | None:
    """Data do evento: a escrita, ou a data do registro quando não há outra."""
    raw = _first(fields, *names)
    if raw is None:
        if reference is None:
            alerts.add("missing_field", f"Sem {label}. Informe na revisão.", target)
            return None
        parsed = reference
    else:
        parsed = parse_event_date(raw, reference=reference)
        if parsed is None:
            alerts.add("illegible_field", f"{label.capitalize()} ilegível: “{raw}”.", target)
            return None
    today = farm_today()
    if parsed > today:
        alerts.add("future_date", f"{label.capitalize()} no futuro: {parsed:%d/%m/%Y}.", target)
    elif (today - parsed).days > OLD_DATE_DAYS:
        # O ano é o que o leitor mais erra no cabeçalho (2026 lido como 2024).
        alerts.add(
            "old_date",
            f"{label.capitalize()} de mais de 6 meses atrás: {parsed:%d/%m/%Y}. Confira o ano.",
            target,
        )
    return parsed.isoformat()


def _production(fields, reference, alerts) -> dict[str, Any]:
    measured_on = _date_field(
        fields, ("data", "measured_on"), reference=reference,
        target="measured_on", alerts=alerts, label="data da coleta",
    )
    raw = _first(fields, "producao", "litros", "total")
    producao = parse_number_br(raw) if raw is not None else None
    if raw is None:
        alerts.add("missing_field", "Sem litros. Informe na revisão.", "producao")
    elif producao is None:
        alerts.add("illegible_field", f"Litros ilegíveis: “{raw}”.", "producao")
    elif not 0 <= producao <= MAX_LITERS:
        alerts.add(
            "implausible_value",
            f"{raw} L está fora do plausível (0 a {MAX_LITERS:g}). Confira a leitura.",
            "producao",
        )
    raw_parts = _first(fields, "parcelas")
    if raw_parts is not None and producao is not None:
        _check_milkings(raw_parts, producao, alerts)
    return {"measured_on": measured_on, "producao": producao}


def _fmt_liters(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _check_milkings(raw_parts: str, total: float, alerts: _Alerts) -> None:
    """Folha de pesagem: "manhã + tarde = total". Grava-se o total; as
    parcelas só conferem a leitura. Soma que não fecha → alerta, sem escolher
    qual dos números está certo."""
    parts = [parse_number_br(part) for part in raw_parts.split("+")]
    if len(parts) < 2 or any(part is None for part in parts):
        alerts.add(
            "sum_mismatch",
            f"Ordenhas ilegíveis: “{raw_parts}”. Confira o total de {_fmt_liters(total)} L.",
            "producao",
        )
        return
    soma = sum(parts)  # type: ignore[arg-type]
    if abs(soma - total) > 0.01:
        conta = " + ".join(_fmt_liters(part) for part in parts)  # type: ignore[arg-type]
        alerts.add(
            "sum_mismatch",
            f"As ordenhas não fecham: {conta} = {_fmt_liters(soma)}, "
            f"mas o total lido é {_fmt_liters(total)} L. Confira a leitura.",
            "producao",
        )


def _calving(fields, reference, alerts) -> dict[str, Any]:
    raw_del = _first(fields, "del")
    if raw_del is None:
        calved_on = _date_field(
            fields, ("data_parto", "data"), reference=reference,
            target="calved_on", alerts=alerts, label="data do parto",
        )
        return {"calved_on": calved_on}

    days = parse_number_br(raw_del)
    base_raw = _first(fields, "data")
    base = parse_event_date(base_raw, reference=reference) if base_raw else reference
    if days is None or days < 0 or not float(days).is_integer() or base is None:
        alerts.add("illegible_field", f"DEL ilegível: “{raw_del}”.", "calved_on")
        return {"calved_on": None}
    calved = base - timedelta(days=int(days))
    alerts.add(
        "derived_from_del",
        f"Data de parto calculada a partir de DEL {int(days)} em {base:%d/%m/%Y}: "
        f"{calved:%d/%m/%Y}. Confirme a data.",
        "calved_on",
    )
    return {"calved_on": calved.isoformat()}


def _dry_off(fields, reference, alerts) -> dict[str, Any]:
    dried_on = _date_field(
        fields, ("data",), reference=reference,
        target="dried_on", alerts=alerts, label="data da secagem",
    )
    if _first(fields, "ordem") is not None:
        # "→ SECAR" na folha é uma ordem, não o registro de que secou: a data
        # da folha é só ponto de partida (decisão do titular, 19/09/2026).
        alerts.add(
            "dry_off_order",
            "Ordem de secagem na folha. Confirme a data em que a vaca foi secada.",
            "dried_on",
        )
    return {"dried_on": dried_on}


def _exit(fields, reference, alerts) -> dict[str, Any]:
    exited_on = _date_field(
        fields, ("data",), reference=reference,
        target="exited_on", alerts=alerts, label="data da baixa",
    )
    raw_reason = _first(fields, "motivo", "reason")
    reason = None
    if raw_reason is not None:
        folded = _fold(raw_reason)
        reason = next((value for prefix, value in _EXIT_WORDS if folded.startswith(prefix)), None)
    if raw_reason is None:
        alerts.add("missing_field", "Sem motivo da baixa. Informe na revisão.", "reason")
    elif reason is None:
        alerts.add("illegible_field", f"Motivo não reconhecido: “{raw_reason}”.", "reason")
    return {"exited_on": exited_on, "reason": reason, "notes": _first(fields, "observacao", "notes")}


def _lot_change(fields, reference, alerts) -> dict[str, Any]:
    raw = _first(fields, "lote")
    lote = None
    if raw is None:
        alerts.add("missing_field", "Sem lote. Informe na revisão.", "lote")
    else:
        collapsed = re.sub(r"\s+", " ", raw).strip().upper()
        lote = f"LOTE {collapsed}" if collapsed.isdigit() else collapsed
    valid_from = _date_field(
        fields, ("data",), reference=reference,
        target="valid_from", alerts=alerts, label="data da mudança",
    )
    return {"lote": lote, "valid_from": valid_from}


def _note(fields, reference, alerts) -> dict[str, Any]:
    text = _first(fields, "texto", "text")
    if text is None:
        alerts.add("missing_field", "Observação vazia.", "text")
    return {"text": text}


_NORMALIZERS = {
    "production": _production,
    "calving": _calving,
    "dry_off": _dry_off,
    "exit": _exit,
    "lot_change": _lot_change,
    "note": _note,
}


def normalize_event(
    event_type: str, fields: dict[str, Any], *, reference_date: date | None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(payload, alertas)`` para um evento lido."""
    normalizer = _NORMALIZERS.get(event_type)
    if normalizer is None:
        raise ValueError(f"tipo de evento desconhecido: {event_type!r}")
    alerts = _Alerts()
    payload = normalizer(fields, reference_date, alerts)
    return payload, alerts.items
