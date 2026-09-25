# Troca do MinIO

## Por que

Em 24/09/2026 a MinIO arquivou o servidor de código aberto: a imagem saiu do
Docker Hub e do quay.io, e `dl.min.io` responde **410 Gone**, sem manutenção
nem correções de segurança. A ponte atual (`infra/minio/Dockerfile`) compila a
mesma versão do código no GitHub. Ela funciona, mas deixa a fazenda presa a um
programa abandonado. O risco é contido porque o MinIO só existe na rede
interna do Docker, sem porta publicada; ainda assim, não é onde as fotos e
gravações da fazenda devem ficar para sempre.

## O que o app realmente usa

`app/services/storage.py` define três operações: `save`, `load` e
`presigned_url`. Medido no código:

- **`save(chave, bytes, tipo)`** — no envio da foto ou do áudio
  (`ingestion.create_import`).
- **`load(chave)`** — no worker, para ler o arquivo, e na API, para mostrar a
  foto ou tocar o áudio ao lado das propostas (`/api/proposals/sources/{id}/media`).
- **`presigned_url`** — só o caminho antigo das Fichas usava (`review.py`),
  removido no PR `refactor/remove-fichas`. Depois dele, **ninguém usa**.

A chave é `{fazenda}/{sha256 do conteúdo}`, e `media_assets.sha256` guarda o
mesmo hash. Nenhum recurso de S3 além de gravar e ler por chave é usado.

## Opções

| | Mudança de código | O que roda | Como ficam os arquivos | Situação (24/09/2026) |
| --- | --- | --- | --- | --- |
| **A. Pasta compartilhada** | nova `FilesystemObjectStorage` (~40 linhas) + testes | nada: sai um serviço | arquivos comuns num volume do Docker | não depende de terceiros |
| **B. versitygw** | nenhuma | um servidor S3 leve | arquivos comuns numa pasta | Apache-2.0, v1.8.0 (04/09) |
| C. SeaweedFS | nenhuma | master, volume e filer | formato próprio | Apache-2.0, v4.47 (14/09), muito usado |
| D. RustFS | nenhuma | um servidor | formato próprio | Apache-2.0, **1.0.0 em 16/09** |
| E. Garage | nenhuma, mas bucket e chaves pelo CLI dele | um servidor | formato próprio | AGPL-3.0, pensado para vários nós |

**Testado neste notebook, com o cliente MinIO do próprio app:** o versitygw
(B) passou em criar o bucket, gravar, ler e no link temporário, sem mudar uma
linha, e a foto ficou no disco como arquivo comum
(`/dados/sheets/fazenda/abc123`).

Descartadas: **RustFS**, jovem demais para guardar os dados da produção (a
versão 1.0 tem uma semana); **Garage**, que resolve um problema que a fazenda
não tem (vários servidores) e pede configuração manual; **SeaweedFS**, maduro
mas com três componentes e formato próprio no disco — peças demais para um PC
de fazenda.

## Recomendação: A, pasta compartilhada

A fazenda é uma só, num PC só, e a regra é que nada sai dela: não há motivo
para manter um servidor de objetos. O app só grava e lê arquivo por chave.

- **Uma peça a menos** para rodar, atualizar e monitorar; saem as variáveis
  `MINIO_*` e a compilação do MinIO.
- **Os arquivos são arquivos**: dá para abrir uma foto direto do disco, e o
  backup continua sendo um `tar` do volume.
- **Custo:** código novo pequeno, com testes; a API e o worker montam o mesmo
  volume (no mesmo PC, isso é trivial).

**Plano B:** versitygw (B), se o titular preferir manter a interface S3 —
por exemplo, para um dia mover os arquivos para um serviço externo. Zero
código, e os arquivos também ficam comuns no disco.

## Desenho de A

- `FilesystemObjectStorage(raiz)`:
  - `save` grava num arquivo temporário e renomeia, para que um arquivo nunca
    fique pela metade;
  - `load` lê;
  - a chave é normalizada, e qualquer chave que saia da raiz (`..`, caminho
    absoluto) é recusada — as chaves são geradas pelo servidor, mas a guarda
    fica no código.
- `presigned_url` sai do protocolo (ninguém usa depois da remoção das Fichas).
- `STORAGE_DIR` na configuração (padrão `/dados/arquivos`); o compose troca o
  serviço `minio` por um volume `arquivos` montado na `api` e no `worker`.
- Testes: gravar e ler; chave com subpasta; chave que tenta sair da raiz;
  gravação interrompida não deixa arquivo parcial.

## Migração (vale para A e para B)

1. **Backup antes**, e verificado no notebook.
2. **Copiar e conferir:** um script lê cada `media_assets.object_key` do banco,
   carrega o arquivo do MinIO, grava no destino novo e confere
   `sha256(conteúdo) == media_assets.sha256`. Divergência para tudo: nada é
   trocado pela metade. Sem `--aplicar`, só mostra o que faria (como os
   scripts de `tools/manutencao`).
3. **Trocar** a configuração e o compose; subir; conferir que o número de
   arquivos no destino é o de `media_assets` e abrir algumas fotos na Revisão.
4. **Guardar o volume antigo do MinIO** por 30 dias antes de apagar.
5. **Backup:** `backup.ps1` e `verificar-backup.ps1` passam a empacotar o
   volume novo em vez de `belo-vale_minio_data`.

**Ensaio antes da produção:** restaurar o backup real no notebook (o
`verificar-backup.ps1` já monta um banco descartável) e rodar a migração
nessa cópia.

## Fora do escopo

- Armazenamento em nuvem. Se um dia for preciso, uma `S3ObjectStorage` volta
  pelo mesmo protocolo.

## Decisão pendente

O titular escolhe entre **A** (recomendada) e **B**. Com a escolha, sai o
plano de implementação.
