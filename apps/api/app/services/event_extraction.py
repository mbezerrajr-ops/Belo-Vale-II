"""Contrato dos leitores de eventos: o que qualquer leitor entrega.

Um leitor recebe um conteúdo (foto de caderno, áudio, texto) e devolve uma
lista de eventos lidos, com o texto como foi lido. Não normaliza, não associa
ao animal, não grava — isso é trabalho de `event_normalization` e de
`event_proposals`, iguais para todos os leitores.

Os leitores reais rodam em infraestrutura própria (decisão do titular: nada
de enviar fotos ou áudios a provedores externos) e entram nas próximas fases.
Aqui ficam o contrato, um leitor falso para testes e o carregamento de uma
extração em JSON — útil também para depurar os leitores reais.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol

from app.services.event_normalization import EVENT_TYPES


@dataclass(frozen=True)
class ExtractedEvent:
    #: Um de `EVENT_TYPES`.
    event_type: str
    #: Brinco como foi lido ou dito. Única chave de associação automática.
    brinco: str | None
    #: Nome como foi lido ou dito. Só vira sugestão para quem revisa.
    nome: str | None
    #: Campos do evento, em texto, como vieram ("21,5", "ontem", "vendida").
    fields: dict[str, str | None]
    #: De onde saiu: trecho de texto, região da imagem, intervalo do áudio.
    evidence: dict[str, Any] = field(default_factory=dict)
    #: Confiança do leitor por campo, de 0 a 1.
    confidence: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EventExtraction:
    events: list[ExtractedEvent]
    extractor_name: str
    extractor_version: str
    #: Data a que o conteúdo se refere, quando o leitor a encontrou.
    reference_date: date | None = None

    def to_raw(self) -> dict[str, Any]:
        """A saída como foi entregue, para guardar sem alterações."""
        return {
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
            "reference_date": self.reference_date.isoformat() if self.reference_date else None,
            "events": [asdict(event) for event in self.events],
        }


class EventExtractor(Protocol):
    def extract(self, content: bytes, *, kind: str) -> EventExtraction: ...


class ExtractionFormatError(ValueError):
    """Extração em JSON com formato inválido. A mensagem diz onde."""


def extraction_from_dict(data: dict[str, Any]) -> EventExtraction:
    """Lê uma extração em JSON (o formato de `EventExtraction.to_raw`)."""
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ExtractionFormatError("Esperado um objeto com a lista 'events'.")
    reference = data.get("reference_date")
    try:
        reference_date = date.fromisoformat(reference) if reference else None
    except ValueError as error:
        raise ExtractionFormatError(f"reference_date inválida: {reference!r}") from error

    events = []
    for index, raw in enumerate(data["events"], start=1):
        if not isinstance(raw, dict):
            raise ExtractionFormatError(f"Evento {index}: esperado um objeto.")
        event_type = raw.get("event_type")
        if event_type not in EVENT_TYPES:
            raise ExtractionFormatError(
                f"Evento {index}: tipo {event_type!r} desconhecido "
                f"(use {', '.join(EVENT_TYPES)})."
            )
        fields = raw.get("fields") or {}
        if not isinstance(fields, dict):
            raise ExtractionFormatError(f"Evento {index}: 'fields' precisa ser um objeto.")
        events.append(
            ExtractedEvent(
                event_type=event_type,
                brinco=raw.get("brinco"),
                nome=raw.get("nome"),
                fields={str(k): None if v is None else str(v) for k, v in fields.items()},
                evidence=raw.get("evidence") or {},
                confidence=raw.get("confidence") or {},
            )
        )
    return EventExtraction(
        events=events,
        extractor_name=str(data.get("extractor_name") or "json"),
        extractor_version=str(data.get("extractor_version") or "1"),
        reference_date=reference_date,
    )


class FakeEventExtractor:
    """Leitor determinístico para testes e demonstração: não lê nada, devolve
    sempre o mesmo caderno. Nunca usado para dado real."""

    name = "fake"
    version = "1"

    def extract(self, content: bytes, *, kind: str) -> EventExtraction:
        return EventExtraction(
            events=[
                ExtractedEvent(
                    event_type="production",
                    brinco="497",
                    nome="PONTA CURTA",
                    fields={"producao": "18"},
                    evidence={"text": "497 Ponta Curta 18"},
                    confidence={"brinco": 0.95, "producao": 0.9},
                ),
                ExtractedEvent(
                    event_type="calving",
                    brinco="497",
                    nome=None,
                    fields={"data": "20/07"},
                    evidence={"text": "pariu dia 20/07"},
                    confidence={"brinco": 0.9, "data": 0.8},
                ),
            ],
            extractor_name=self.name,
            extractor_version=self.version,
            reference_date=date(2026, 7, 22),
        )
