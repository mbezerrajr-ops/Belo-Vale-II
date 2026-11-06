# Runbook de produção — Belo Vale II no servidor

Confirmado em 05/11/2026 pelo acesso SSH e pelo estado dos serviços: a produção
roda no servidor Ubuntu `belo-vale`, com usuário `belovale`, atendendo
`https://belo-vale.taile2ed91.ts.net/`. O notebook Windows é usado para acessar
esse servidor. Executar a atualização no terminal Linux, dentro de
`~/Belo-Vale-II`, conforme este runbook.

Como o sistema roda de verdade, para a fazenda usar pelo celular. O ambiente de
desenvolvimento e testes continua no [runbook local](runbook-local.md). Até
07/10/2026 a produção rodava num PC com Windows: ver
[runbook-producao-windows.md](runbook-producao-windows.md).

## Como está montado

```
iPhone/Android ──HTTPS──> Tailscale Funnel ──> servidor belo-vale (TLS termina aqui)
                          (https://belo-vale.…ts.net)    │
                                                         └─> 127.0.0.1:8090  nginx (app + cabeçalhos de segurança)
                                                                 └─> api (FastAPI, só na rede interna do Docker)
                                                                       ├─ db (PostgreSQL)    ├─ redis
                                                                       ├─ minio (fotos e áudios)
                                                                       └─ worker ──HTTPS──> API Gemini (lê foto e voz)

backup diário cifrado ──> Backblaze B2 (Object Lock, conta da fazenda)
```

Decisões (16/10/2026):

- **Servidor:** VPS na Hostinger (KVM 2: 2 vCPU, 8 GB, 100 GB), em São Paulo,
  Ubuntu 24.04, na conta da fazenda.
- **Leitura de foto e voz:** API Gemini (`gemini-3.5-flash-lite`), na conta
  paga da fazenda, com créditos pré-pagos e sem recarga automática. Se o
  crédito acabar, só a leitura para. Ver `known-issues.md`, "Leitura pela API
  Gemini".
- **Acesso:** Tailscale Funnel, como antes. Nenhuma porta aberta além do SSH:
  o app atende só em `127.0.0.1:8090`.
- **Backup:** diário, cifrado, no Backblaze B2 da fazenda, com Object Lock de
  30 dias (nem quem invadir o servidor apaga as cópias) e apagadas depois de
  90 dias. Nada fica em conta pessoal do desenvolvedor.

## O que guarda o quê

| Onde | O quê | Se perder |
| --- | --- | --- |
| `infra/.env.production` (servidor) | senhas do banco e do MinIO, segredo das sessões, chave do Gemini | gera de novo; as sessões caem |
| `~/.belo-vale/senha-backup.txt` (servidor) | senha da criptografia do backup | **nenhuma cópia abre.** Fica também com o cliente, fora do servidor |
| `~/.belo-vale/b2.env` (servidor) | chave do Backblaze, só para o bucket | cria outra chave no painel do B2 |
| Backblaze B2 | as cópias cifradas | — |

## Servidor novo, do zero

Leva cerca de uma hora, a maior parte esperando. Os comandos com `PS>` rodam
no notebook (PowerShell); os com `$`, no servidor.

### 1. Contratar e entrar

1. No notebook, gere a chave SSH (uma vez só):

   ```powershell
   PS> ssh-keygen -t ed25519 -C "belo-vale"
   PS> Get-Content $HOME\.ssh\id_ed25519.pub
   ```

2. Contrate a VPS na Hostinger (São Paulo, Ubuntu 24.04) e, no painel, cole
   a chave pública em **SSH keys**. Anote o IP.
3. Prepare o servidor (atualiza, cria o usuário `belovale`, fecha o root e a
   senha, firewall, Docker, Tailscale):

   ```powershell
   PS> Get-Content tools\servidor\preparar-servidor.sh -Raw | ssh root@IP "bash -s"
   ```

   No fim ele mostra `ssh belovale@IP`. Daí em diante o root não entra mais.

### 2. Código

O repositório tem dados reais e é privado: o servidor lê com uma chave só de
leitura.

```bash
$ ssh-keygen -t ed25519 -f ~/.ssh/github -N "" -C "servidor belo-vale"
$ printf 'Host github.com\n  IdentityFile ~/.ssh/github\n' >> ~/.ssh/config
$ cat ~/.ssh/github.pub
```

No notebook, cadastre a chave no repositório (só leitura):

```powershell
PS> Set-Content chave.pub "<a linha do cat>"; gh repo deploy-key add chave.pub --title "servidor belo-vale"; Remove-Item chave.pub
```

```bash
$ git clone git@github.com:mbezerrajr-ops/Belo-Vale-II.git ~/Belo-Vale-II
```

### 3. Segredos

Do notebook para o servidor, a senha do backup e a chave do Gemini (nenhuma
aparece na tela):

```powershell
PS> ssh belovale@IP "mkdir -p ~/.belo-vale && chmod 700 ~/.belo-vale"
PS> scp $HOME\.belo-vale\senha-backup.txt $HOME\.belo-vale\gemini-key.txt belovale@IP:.belo-vale/
```

No servidor, a chave do Backblaze (o `read -s` não mostra o que é digitado):

```bash
$ read -p "keyID: " K; read -s -p "applicationKey: " A; echo; read -p "bucket: " B
$ (umask 077; printf 'B2_KEY_ID=%s\nB2_APP_KEY=%s\nB2_BUCKET=%s\n' "$K" "$A" "$B" > ~/.belo-vale/b2.env); unset K A B
$ chmod 600 ~/.belo-vale/*
$ cd ~/Belo-Vale-II && python3 tools/gerar_env_producao.py
```

O nome do bucket é exatamente o do Backblaze, com maiúsculas e minúsculas
(`Belo-vale-backup` não é `belo-vale-backup`): errado, o backup falha com
`401 unauthorized`. O gerador cria senhas novas e põe a chave do Gemini no
`.env.production`.

### 4. Dados

Copie a cópia mais recente para o servidor e restaure. Restaurar recusa um
banco que já tem animais.

```powershell
PS> scp "$env:OneDrive\BeloVale-backup\belo-vale-AAAA-MM-DD_HHMM.tar.gpg" belovale@IP:
```

```bash
$ tools/servidor/restaurar.sh ~/belo-vale-AAAA-MM-DD_HHMM.tar.gpg
```

A primeira vez **compila o MinIO** do código-fonte (cerca de 10 minutos; ver
`known-issues.md`, "MinIO arquivado"). No fim, as contagens são conferidas com
o manifesto do backup. Todos entram de novo com a própria senha.

### 5. Internet

```bash
$ sudo tailscale up
```

Abra o link que aparece e entre com a conta Tailscale **da fazenda**. No painel
(login.tailscale.com/admin): **DNS → MagicDNS** e **HTTPS Certificates**
ligados, e o Funnel permitido para o servidor (o painel oferece o atalho no
primeiro uso). Então:

```bash
$ sudo tailscale funnel --bg --https=443 http://127.0.0.1:8090
$ sudo tailscale funnel status
```

O endereço do app é o do `status` (`https://belo-vale.….ts.net`). Quem tinha o
app instalado no celular abre o endereço novo e instala de novo.

### 6. Backup

```bash
$ tools/servidor/producao.sh backup       # o primeiro, à mão
$ tools/servidor/producao.sh verificar    # prova que restaura
$ sudo tools/servidor/instalar-agendamentos.sh
```

Daí em diante: backup todo dia às 3h30 e verificação aos domingos às 4h30
(`systemctl list-timers 'belo-vale-*'`). Servidor desligado no horário: roda
quando voltar.

Depois da primeira verificação, os backups antigos (feitos no Windows) podem
ir para o B2 e sair do OneDrive pessoal:
`rclone copy <pasta> b2:<bucket>` com as variáveis do `b2.env`.

## Dia a dia

```bash
$ cd ~/Belo-Vale-II
$ tools/servidor/producao.sh estado         # o que está no ar, último backup e verificação
$ tools/servidor/producao.sh registros worker
$ tools/servidor/producao.sh backup
```

## Atualizar depois de um merge

```bash
$ tools/servidor/producao.sh atualizar
```

Faz o backup, baixa o código (`git pull`), reconstrói, aplica as migrações,
confere que o app voltou e apaga as imagens antigas.

## Restaurar

- **Um backup específico, num servidor novo:** seção "Servidor novo", passo 4.
  As cópias ficam no B2 (`rclone lsf b2:<bucket>`) e as últimas 7 também em
  `~/.belo-vale/copias/`.
- **Só conferir uma cópia**, sem tocar na produção:
  `tools/servidor/verificar-backup.sh <arquivo.tar.gpg>`. Abre também as
  cópias feitas no Windows.

## Leitura por IA (Gemini)

- O custo medido é de cerca de R$ 0,05 por folha e R$ 0,002 por gravação. O
  saldo e o consumo ficam no Google AI Studio, em Faturamento.
- Sem crédito (ou com o Google fora do ar), a leitura falha com o motivo
  `reader_unavailable`: quem enviou vê que o leitor está fora do ar e que o
  arquivo está bom, e envia de novo depois. Lançamento, importação, folha e
  exportação continuam.
- Trocar o modelo é uma variável no `.env.production` (`READER_MODEL`,
  `AUDIO_MODEL`) e um `atualizar`. Meça antes: `docs/vision-provider-status.md`.

## Segurança — o que vale no servidor

- SSH só por chave, sem root e sem senha; firewall fechado, só com o SSH aberto.
- Atualizações de segurança do Ubuntu automáticas.
- A API se recusa a subir em produção sem segredo forte, com o cookie de sessão
  sem `Secure`, com leitor falso ou sem a chave do Gemini.
- Limite de tentativas de login, política de senha, sessão curta com renovação
  em cookie `HttpOnly`/`Secure`; CSP só da própria origem; HSTS.
- Fotos e gravações só saem para a API Gemini, endereço fixo no código.
- Backup cifrado (AES-256) antes de sair do servidor; a chave do B2 só alcança
  o bucket e não apaga as cópias dentro dos 30 dias do Object Lock.
