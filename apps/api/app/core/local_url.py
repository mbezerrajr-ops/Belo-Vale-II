"""A guarda que mantém os modelos dentro de casa.

Decisão do titular: nenhuma foto e nenhuma gravação sai para provedor
externo. Quem garante isso não é disciplina, é esta função: o endereço de um
modelo só é aceito se for da própria máquina ou da rede interna, e a recusa
acontece na construção do leitor — não na primeira leitura.

Vale para os dois modelos (o de visão e o de fala), por isso mora aqui e não
dentro de um deles.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

#: Nomes que apontam para a própria máquina, apesar do ponto.
#: `host.docker.internal` é o apelido que o Docker dá ao hospedeiro — é por
#: ele que o worker em contêiner alcança um modelo rodando fora do Docker
#: (no Windows, onde a GPU AMD não passa para o contêiner).
LOCAL_NAMES = frozenset({"localhost", "host.docker.internal"})


def ensure_local_url(url: str) -> str:
    """Aceita só a própria máquina e a rede interna. Devolve a URL sem "/" final.

    Nome de serviço sem ponto ("ollama", "whisper") é aceito: é assim que um
    contêiner acha outro na rede interna do Docker Compose. Domínio com ponto
    é recusado mesmo que resolva para IP interno — não dá para garantir que
    continue assim.
    """
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Endereço do modelo inválido: {url!r}.")
    host = parts.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host in LOCAL_NAMES or "." not in host:
            return url.rstrip("/")
        raise ValueError(
            f"O modelo precisa rodar na própria infraestrutura; {host} não é endereço interno."
        ) from None
    if address.is_loopback or address.is_private:
        return url.rstrip("/")
    raise ValueError(
        f"O modelo precisa rodar na própria infraestrutura; {host} não é endereço interno."
    )
