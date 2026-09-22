"""Dá nota ao ouvido local contra gravações já conferidas.

Uso — no contêiner do worker, que tem o ffmpeg, falando com o whisper da
máquina pelo mesmo caminho da leitura de verdade::

    docker compose --env-file infra/.env.local -f infra/docker-compose.yml run --rm \\
      -v "$PWD/docs/Treinamento_audios:/gravacoes" worker \\
      uv run --no-sync python -m app.core.evaluate_transcriber --samples /gravacoes

Para cada gravação com um gabarito ao lado (`<nome>.gabarito.json`), converte
para WAV 16 kHz mono, transcreve com o whisper local, traduz com o tradutor
da fala e compara vaca a vaca **pelo brinco**: a fala não tem número de
linha, e uma vaca omitida não pode desalinhar as outras. Grava ao lado:

- `<nome>.transcricao.json` — o que o whisper ouviu; é o que diz se o erro
  foi do ouvido ou do tradutor;
- `<nome>.leitura.json` — os eventos, prontos para
  `python -m app.core.load_proposals --file <nome>.leitura.json`.

A nota separa a vaca que FALTA da que chega ERRADA. Vaca que falta não chega
à Revisão. Vaca com brinco ou total trocado chega com cara de certa,
esperando alguém aprovar — é o erro que custa caro.

Com `--ruido 0.03,0.08,0.15,0.30`, cada gravação é ouvida também com ruído
grave (marrom, parecido com motor) somado, e a nota traz a relação voz/ruído
medida. É ruído sintético: a medida que vale continua sendo a gravação feita
no curral, com a ordenhadeira ligada.

O gabarito::

    {"linhas": [
      {"brinco": "633", "nome": "GIGANTE", "manha": "2", "tarde": "2", "total": "4", "secar": true},
      {"brinco": "462", "nome": "SABIÁ", "total": "15", "lote": "1"},
      {"brinco": "649", "nome": "REDONDA", "total": "5", "secar": true, "nota": "7 meses"}
    ]}

`nota` é um pedaço do texto que a observação daquela vaca precisa ter.

As gravações são dados reais da fazenda e ficam fora do Git
(`docs/Treinamento_audios/` está no .gitignore). Nada sai da máquina: o
transcritor só aceita endereço local.
"""

from __future__ import annotations

import argparse
import array
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.audio.decoding import DECODE_TIMEOUT, to_wav_16k_mono
from app.audio.speech_reader import EXTRACTOR_NAME, GRAMMAR_VERSION
from app.audio.speech_to_lines import AUDIO_ORIGIN, speech_to_lines
from app.audio.transcriber import (
    TranscriberFormatError,
    TranscriberUnavailable,
    WhisperCppTranscriber,
)
from app.core.config import get_settings
from app.services.event_proposals import SIMILAR_NAME, name_similarity
from app.services.portuguese_numbers import fold
from app.services.production_files import parse_number_br
from app.services.reading_to_events import lines_to_events

_SAMPLE_SUFFIXES = (
    ".m4a", ".mp4", ".3gp", ".amr", ".aac", ".mp3",
    ".ogg", ".oga", ".opus", ".wav", ".webm", ".mka",
)

#: O ruído é o mesmo a cada rodada: duas versões do tradutor ou do ouvido
#: comparadas no mesmo ruído.
_NOISE_SEED = 7


@dataclass
class WrongReading:
    """Uma vaca que chegaria errada à Revisão."""

    brinco: str | None
    #: `total`, `brinco` (vaca que não foi dita) ou `repetida`.
    field: str
    expected: Any
    read: Any


@dataclass
class CowScore:
    expected: int = 0
    #: Brinco e total certos: é o que vira produção.
    right: int = 0
    #: Das vacas achadas, quantas com o nome parecido com o do gabarito.
    name_right: int = 0
    #: Das vacas achadas, quantas com manhã e tarde certas.
    milkings_right: int = 0
    missing: list[str] = field(default_factory=list)
    wrong: list[WrongReading] = field(default_factory=list)
    #: Litros sem brinco: a Revisão pede a vaca — não é erro silencioso.
    without_brinco: int = 0
    dry_off_expected: int = 0
    dry_off_found: int = 0
    lot_expected: int = 0
    lot_found: int = 0
    #: Ordem de secar ou troca de lote que ninguém deu.
    commands_invented: int = 0
    notes_expected: int = 0
    notes_found: int = 0
    #: Observação que ninguém disse: uma proposta inútil esperando alguém
    #: rejeitar.
    notes_extra: int = 0
    #: (brinco, texto) de cada observação a mais.
    extra_notes: list[tuple[str | None, str]] = field(default_factory=list)

    @property
    def found(self) -> int:
        return self.expected - len(self.missing)


def _brinco(value: Any) -> str | None:
    """Brinco é identidade: "011" e "11" são vacas diferentes."""
    if value in (None, ""):
        return None
    return "".join(str(value).split()).upper() or None


def _lote(value: Any) -> str | None:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits or None


def _same_number(read: Any, truth: Any) -> bool:
    return parse_number_br(read) == parse_number_br(truth)


def compare_cows(text: str, truth: dict[str, Any]) -> CowScore:
    """A transcrição passa pelo tradutor de verdade e é comparada, vaca a
    vaca pelo brinco, com o gabarito."""
    reading = speech_to_lines(text)
    extraction = lines_to_events(
        reading,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=GRAMMAR_VERSION,
        origem=AUDIO_ORIGIN,
    )
    return _score(reading["linhas"], extraction.events, truth)


def _score(lines: list[dict[str, Any]], events: list[Any], truth: dict[str, Any]) -> CowScore:
    score = CowScore()
    expected = {
        brinco: line
        for line in truth.get("linhas") or []
        if (brinco := _brinco(line.get("brinco"))) is not None
    }
    score.expected = len(expected)
    seen: set[str] = set()
    for line in lines:
        brinco = _brinco(line.get("brinco"))
        if brinco is None:
            score.without_brinco += 1
            continue
        want = expected.get(brinco)
        if want is None:
            score.wrong.append(WrongReading(brinco, "brinco", None, brinco))
            continue
        if brinco in seen:
            score.wrong.append(WrongReading(brinco, "repetida", None, line.get("total")))
            continue
        seen.add(brinco)
        if _same_number(line.get("total"), want.get("total")):
            score.right += 1
        else:
            score.wrong.append(WrongReading(brinco, "total", want.get("total"), line.get("total")))
        if not want.get("nome") or name_similarity(line.get("nome"), want["nome"]) >= SIMILAR_NAME:
            score.name_right += 1
        if all(_same_number(line.get(key), want.get(key)) for key in ("manha", "tarde")):
            score.milkings_right += 1
    score.missing = [brinco for brinco in expected if brinco not in seen]

    dry = {_brinco(e.brinco) for e in events if e.event_type == "dry_off"}
    lots = {(_brinco(e.brinco), _lote(e.fields.get("lote"))) for e in events if e.event_type == "lot_change"}
    want_dry = {brinco for brinco, line in expected.items() if line.get("secar")}
    want_lots = {(brinco, _lote(line["lote"])) for brinco, line in expected.items() if line.get("lote")}
    score.dry_off_expected, score.dry_off_found = len(want_dry), len(want_dry & dry)
    score.lot_expected, score.lot_found = len(want_lots), len(want_lots & lots)
    score.commands_invented = len(dry - want_dry) + len(lots - want_lots)

    want_notes = {brinco: fold(line["nota"]) for brinco, line in expected.items() if line.get("nota")}
    found_notes: set[str] = set()
    for event in events:
        if event.event_type != "note":
            continue
        brinco, text = _brinco(event.brinco), fold(str(event.fields.get("texto") or ""))
        want = want_notes.get(brinco) if brinco else None
        if want is not None and want in text and brinco not in found_notes:
            found_notes.add(brinco)
        else:
            score.notes_extra += 1
            score.extra_notes.append((brinco, str(event.fields.get("texto") or "")))
    score.notes_expected, score.notes_found = len(want_notes), len(found_notes)
    return score


# ------------------------------------------------------------------- ruído


def _samples(wav: bytes) -> array.array:
    with wave.open(io.BytesIO(wav)) as arquivo:
        if arquivo.getsampwidth() != 2:
            raise ValueError("Esperado WAV de 16 bits.")
        frames = arquivo.readframes(arquivo.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _rms(values) -> float:
    total, count = 0.0, 0
    for value in values:
        total += value * value
        count += 1
    return math.sqrt(total / count) if count else 0.0


def snr_db(clean_wav: bytes, noisy_wav: bytes) -> float:
    """Relação voz/ruído, medida: o ruído é a diferença entre a gravação com
    ruído e a limpa, amostra a amostra."""
    clean, noisy = _samples(clean_wav), _samples(noisy_wav)
    size = min(len(clean), len(noisy))
    noise = _rms(noisy[i] - clean[i] for i in range(size))
    voice = _rms(clean[i] for i in range(size))
    if noise == 0:
        return math.inf
    return 20 * math.log10(voice / noise) if voice else -math.inf


def _add_brown_noise(wav: bytes, amplitude: float) -> bytes:
    """Ruído grave (marrom) somado à gravação, com o ffmpeg do worker."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscriberUnavailable("ffmpeg não está instalado aqui; rode no contêiner do worker.")
    descritor, entrada = tempfile.mkstemp(suffix=".wav")
    saida = entrada + ".ruido.wav"
    try:
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(wav)
        subprocess.run(
            [
                ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", entrada,
                "-f", "lavfi", "-i",
                f"anoisesrc=color=brown:amplitude={amplitude}:sample_rate=16000:seed={_NOISE_SEED}",
                "-filter_complex", "[0][1]amix=inputs=2:duration=first:normalize=0",
                "-ac", "1", "-ar", "16000", "-f", "wav", saida,
            ],
            capture_output=True,
            timeout=DECODE_TIMEOUT,
            check=True,
        )
        return Path(saida).read_bytes()
    finally:
        for caminho in (entrada, saida):
            try:
                os.remove(caminho)
            except OSError:
                pass


# ----------------------------------------------------------------- comando


@dataclass
class _Total:
    expected: int = 0
    right: int = 0
    missing: int = 0
    wrong: int = 0
    notes_extra: int = 0
    recordings: int = 0
    snr: list[float] = field(default_factory=list)

    def add(self, score: CowScore, snr: float | None) -> None:
        self.expected += score.expected
        self.right += score.right
        self.missing += len(score.missing)
        self.wrong += len(score.wrong)
        self.notes_extra += score.notes_extra
        self.recordings += 1
        if snr is not None and math.isfinite(snr):
            self.snr.append(snr)


def _level_label(level: float, snr: float | None) -> str:
    if level == 0:
        return "limpo"
    measured = f" · voz/ruído {snr:.0f} dB" if snr is not None and math.isfinite(snr) else ""
    return f"ruído {level:g}{measured}"


def _report(name: str, label: str, score: CowScore, seconds: float) -> str:
    rows = [
        f"== {name} · {label}  ({seconds:.0f}s)",
        f"   {score.right}/{score.expected} vacas certas · {len(score.missing)} faltando · "
        f"{len(score.wrong)} erradas · {score.without_brinco} sem brinco",
        f"   nome {score.name_right}/{score.found} · manhã e tarde {score.milkings_right}/{score.found}"
        " (das achadas)",
        f"   secar {score.dry_off_found}/{score.dry_off_expected} · lote "
        f"{score.lot_found}/{score.lot_expected} · observações "
        f"{score.notes_found}/{score.notes_expected} · ordens a mais {score.commands_invented}"
        f" · observações a mais {score.notes_extra}",
    ]
    rows += [f"   - falta: {brinco}" for brinco in score.missing]
    rows += [
        f"   - errada: {w.brinco} {w.field} (esperado {w.expected!r}, lido {w.read!r})"
        for w in score.wrong
    ]
    rows += [f"   - observação a mais: {brinco or 'sem brinco'}: {texto!r}" for brinco, texto in score.extra_notes]
    return "\n".join(rows)


def _transcription_path(sample: Path, level: float) -> Path:
    suffix = "" if level == 0 else f".ruido-{level:g}"
    return sample.with_name(f"{sample.stem}{suffix}.transcricao.json")


def _heard(
    sample: Path,
    level: float,
    wav: bytes,
    transcribe: Callable[[bytes], str],
    model: str,
    reuse: bool,
) -> str:
    """O que o ouvido entendeu, salvo ao lado da gravação."""
    saved = _transcription_path(sample, level)
    if reuse and saved.exists():
        previous = json.loads(saved.read_text(encoding="utf-8"))
        if previous.get("_ouvido") == model:
            return previous["texto"]
    text = transcribe(wav)
    saved.write_text(
        json.dumps({"_ouvido": model, "ruido": level, "texto": text}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return text


def main(
    argv: list[str] | None = None,
    *,
    transcribe: Callable[[bytes], str] | None = None,
    decode: Callable[[bytes], bytes] | None = None,
    add_noise: Callable[[bytes, float], bytes] | None = None,
    measure: Callable[[bytes, bytes], float] | None = None,
    model: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", required=True, type=Path, help="Pasta com as gravações.")
    parser.add_argument("--url", default=None, help="Endereço do whisper (padrão: AUDIO_URL).")
    parser.add_argument("--model", default=None, help="Nome do modelo (padrão: AUDIO_MODEL).")
    parser.add_argument("--pattern", default="*", help="Só as gravações cujo nome casa com o padrão.")
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reaproveita a transcrição salva do mesmo modelo: mexer no tradutor não precisa de GPU.",
    )
    parser.add_argument(
        "--ruido",
        default="",
        help="Níveis de ruído grave somado (amplitude), separados por vírgula. Ex.: 0.03,0.08,0.15,0.30",
    )
    args = parser.parse_args(argv)
    settings = get_settings()

    if transcribe is None:
        transcriber = WhisperCppTranscriber(
            url=args.url or settings.audio_url,
            model=args.model or settings.audio_model,
            language=settings.audio_language,
        )
        transcribe = transcriber.transcribe
    model = model or args.model or settings.audio_model
    if decode is None:
        decode = lambda content: to_wav_16k_mono(content, max_seconds=settings.audio_max_seconds)  # noqa: E731
    add_noise = add_noise or _add_brown_noise
    measure = measure or snr_db
    levels = [float(level) for level in args.ruido.split(",") if level.strip()]

    candidates = sorted(
        path
        for path in args.samples.glob(args.pattern)
        if path.suffix.lower() in _SAMPLE_SUFFIXES
        and path.with_name(f"{path.stem}.gabarito.json").exists()
    )
    if not candidates:
        print(f"Nenhuma gravação com gabarito em {args.samples}.", file=sys.stderr)
        return 2

    print(f"ouvido: {model} · tradutor: {GRAMMAR_VERSION}")
    totals: dict[float, _Total] = {}
    for sample in candidates:
        truth = json.loads(sample.with_name(f"{sample.stem}.gabarito.json").read_text(encoding="utf-8"))
        try:
            clean = decode(sample.read_bytes())
        except TranscriberUnavailable as error:
            print(f"erro: {error}", file=sys.stderr)
            return 2
        except TranscriberFormatError as error:
            # Uma gravação estragada não pode derrubar a nota das outras.
            print(f"-- {sample.name}: gravação recusada ({error})")
            continue
        for level in [0.0, *levels]:
            started = time.monotonic()
            wav = clean if level == 0 else add_noise(clean, level)
            snr = None if level == 0 else measure(clean, wav)
            label = _level_label(level, snr)
            try:
                text = _heard(sample, level, wav, transcribe, model, args.reuse)
            except TranscriberUnavailable as error:
                print(f"erro: {error}", file=sys.stderr)
                return 2
            except TranscriberFormatError as error:
                print(f"-- {sample.name} · {label}: transcrição recusada ({error})")
                continue
            score = compare_cows(text, truth)
            print(_report(sample.name, label, score, time.monotonic() - started))
            totals.setdefault(level, _Total()).add(score, snr)
            if level == 0:
                extraction = lines_to_events(
                    speech_to_lines(text),
                    extractor_name=EXTRACTOR_NAME,
                    extractor_version=f"{model}/{GRAMMAR_VERSION}",
                    origem=AUDIO_ORIGIN,
                )
                sample.with_name(f"{sample.stem}.leitura.json").write_text(
                    json.dumps(extraction.to_raw(), ensure_ascii=False, indent=2), encoding="utf-8"
                )

    if totals:
        first = next(iter(totals.values()))
        print(f"\nresumo ({first.expected} vacas em {first.recordings} gravações):")
        for level, total in totals.items():
            snr = sum(total.snr) / len(total.snr) if total.snr else None
            print(
                f"   {_level_label(level, snr):<28} {total.right}/{total.expected} certas · "
                f"{total.missing} faltando · {total.wrong} erradas · "
                f"{total.notes_extra} observações a mais"
            )
        if levels:
            print("   (ruído sintético somado à gravação: não é o curral)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
