# -*- coding: utf-8 -*-
"""Deixa um .js de terceiros aceitável para o publicador de Artifacts.

O publicador recusa arquivos de texto com bytes de controle crus ou com o caractere
U+FFFD. Este script troca os dois pelos escapes JavaScript equivalentes — uma troca
sintática, sem mudança de semântica, válida dentro de literais de string.

Uso:
    python normalize_for_artifact.py pdf.min.js pdf.worker.min.js xlsx.full.min.js
    node --check xlsx.full.min.js
"""
import sys

ESCAPE_FFFD = '\\u' + 'fffd'   # o escape em si, não o caractere


def normaliza(caminho):
    bruto = open(caminho, 'rb').read()
    saida = bytearray()
    controles = 0
    for b in bruto:
        if b < 32 and b not in (9, 10, 13):
            saida.extend(('\\x%02x' % b).encode())
            controles += 1
        else:
            saida.append(b)

    texto = bytes(saida).decode('utf-8')
    fffd = texto.count('�')
    texto = texto.replace('�', ESCAPE_FFFD)
    open(caminho, 'w', encoding='utf-8', newline='').write(texto)
    print('%s | controles escapados: %d | U+FFFD escapados: %d' % (caminho, controles, fffd))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for arquivo in sys.argv[1:]:
        normaliza(arquivo)
