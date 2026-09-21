"""A gravação do celular vira WAV 16 kHz mono, que é o que o whisper ouve.

O celular manda m4a (Android e iPhone), às vezes 3gp ou amr. O ffmpeg, no
contêiner do worker, converte tudo — e é a partir daqui que a duração conta:
`-t` corta a gravação no limite, para que um áudio de uma hora não prenda a
GPU. `-vn` descarta qualquer faixa de vídeo que tenha passado.

O original vai para um arquivo temporário, não para a entrada padrão: o
índice de um m4a de Android costuma vir no FIM do arquivo, e ler pela
entrada padrão não permite voltar até ele. A saída também vai para arquivo,
não para a saída padrão: num cano o ffmpeg não consegue voltar ao começo e
gravar o tamanho no cabeçalho do WAV, e deixa ali "tamanho desconhecido" —
medido, um corte de 1 s aparecia como 134.217 s para quem lê o cabeçalho.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.audio.transcriber import TranscriberFormatError, TranscriberUnavailable

#: Prazo da conversão. Uma gravação de 5 minutos converte em segundos.
DECODE_TIMEOUT = 120.0


def to_wav_16k_mono(content: bytes, *, max_seconds: int) -> bytes:
    """A gravação em WAV 16 kHz mono, cortada em `max_seconds`."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscriberUnavailable(
            "ffmpeg não está instalado no worker; a gravação não pode ser convertida."
        )
    descritor, entrada = tempfile.mkstemp(suffix=".audio")
    saida = entrada + ".wav"
    try:
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(content)
        resultado = subprocess.run(
            [
                ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", entrada,
                "-vn", "-ac", "1", "-ar", "16000", "-t", str(max_seconds),
                "-f", "wav", saida,
            ],
            capture_output=True,
            timeout=DECODE_TIMEOUT,
            check=False,
        )
        wav = Path(saida).read_bytes() if os.path.exists(saida) else b""
    except subprocess.TimeoutExpired as error:
        raise TranscriberFormatError("A conversão da gravação passou do tempo.") from error
    finally:
        for caminho in (entrada, saida):
            try:
                os.remove(caminho)
            except OSError:
                pass
    # Um WAV sem amostra nenhuma tem só o cabeçalho (44 bytes).
    if resultado.returncode != 0 or len(wav) <= 44:
        detalhe = resultado.stderr.decode(errors="replace").strip()[:200]
        raise TranscriberFormatError(
            "A gravação não tem áudio que se possa ouvir." + (f" ({detalhe})" if detalhe else "")
        )
    return wav
