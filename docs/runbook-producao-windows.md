# Runbook de produção no Windows

> **Histórico.** A hospedagem atual foi confirmada em 05/11/2026 no servidor
> Ubuntu `belo-vale`: seguir o [runbook Linux](runbook-producao.md).
> O notebook Windows é a estação de acesso. Os procedimentos abaixo continuam
> disponíveis para instalações Windows, mas não atualizam a hospedagem atual.

## Atualização da ampliação para produtores e fazendas

No notebook que hospeda o site, abrir PowerShell na pasta do projeto, com
Docker Desktop em execução. Depois de a mudança estar integrada à `main`:

```powershell
git switch main
git pull --ff-only
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 atualizar
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 estado
```

Confirmar o backup oferecido pelo comando. Se ele falhar, a atualização para
antes de alterar os serviços ou o banco. As imagens são compiladas e as
migrações aplicadas antes de substituir os serviços. Manter o arquivo existente
`infra/.env.production`; não gerar novamente os segredos de uma instalação
que já está em uso.

Cadastro público, convites e recuperação por e-mail precisam de `PUBLIC_APP_URL`
e SMTP configurados nesse arquivo, conforme
[Produtores e fazendas](produtores-e-fazendas.md#e-mails-transacionais).
Os acessos legados preservados pela migração não exigem uma nova confirmação.

Como o sistema roda de verdade, para a fazenda usar pelo celular. O ambiente de
desenvolvimento e testes continua no [runbook local](runbook-local.md).

## Como está montado

```
iPhone/Android ──HTTPS──> Tailscale Funnel ──> este PC (TLS termina aqui)
                          (https://…ts.net)       │
                                                  └─> 127.0.0.1:8090  nginx (app + cabeçalhos de segurança)
                                                          └─> api (FastAPI, só na rede interna do Docker)
                                                                ├─ db (PostgreSQL)    ├─ redis
                                                                ├─ minio (fotos e áudios)
                                                                └─ worker ──> Ollama :11434 (fotos)
                                                                          └─> whisper :8081 (áudio)   (RX 7600)
```

Decisões (22/09/2026):

- **Servidor:** este PC, porque a leitura de foto e áudio precisa da RX 7600 e
  não sai da fazenda.
- **Acesso:** Tailscale Funnel. Não precisa abrir porta no roteador e funciona
  com internet rural de IP compartilhado. O HTTPS termina **neste PC**: a
  Tailscale repassa o tráfego cifrado e não vê senhas, fotos nem áudios.
- **Nenhuma porta aberta na rede local:** a API não é publicada, e o app só
  atende em `127.0.0.1:8090`. O único caminho de fora é o Funnel.
- **Backup:** diário, num HD externo e numa cópia criptografada no OneDrive.

## Uma vez só (feito ou pendente)

| Passo | Estado |
| --- | --- |
| Segredos de produção (`python tools/gerar_env_producao.py`) | feito |
| Subir a produção e aplicar as migrações | feito |
| Fazenda + baseline (401 animais, 152 medições, insumos, preço do leite) | feito |
| Backup diário (3h30) e verificação semanal (domingo 4h30) agendados | feito |
| PC sem suspender na tomada; Docker Desktop abrindo com o Windows | já estava |
| Criar a conta do administrador | feito |
| Instalar a Tailscale e ligar o Funnel (`https://desktop-caio.tailf88007.ts.net`) | feito |
| Guardar a senha do backup fora do PC | feito (24/09/2026) |
| **Conectar o OneDrive neste PC.** Sem ele e sem o HD, nenhuma cópia sai daqui (ver "Backup") | **pendente: você** |
| Conectar o HD externo e indicar a pasta | **pendente: você** |

### Criar a conta do administrador

A senha é digitada por você e nunca aparece na tela nem passa por outra
pessoa. No terminal, na pasta do projeto:

```powershell
docker compose -p belo-vale --env-file infra/.env.production -f infra/docker-compose.yml -f infra/docker-compose.prod.yml exec api uv run --no-sync python -m app.core.bootstrap_admin --email SEU_EMAIL
```

O comando pede a senha duas vezes e recusa senha fraca. Ele só funciona
enquanto não existir nenhuma conta. Depois disso, as outras contas se criam
pelo app, em **Contas**.

### Tailscale Funnel

1. Instale a Tailscale para Windows (tailscale.com/download) e entre com a sua
   conta (Google, Microsoft ou e-mail).
2. No painel da Tailscale (login.tailscale.com/admin):
   - **DNS → MagicDNS**: ligado;
   - **DNS → HTTPS Certificates**: ligar;
   - **Access controls**: permitir Funnel para este PC. O painel oferece
     o atalho ao rodar o comando abaixo pela primeira vez.
3. No terminal:

   ```powershell
   tailscale funnel --bg --https=443 http://127.0.0.1:8090
   tailscale funnel status
   ```

   O `--bg` deixa o Funnel ligado inclusive depois de reiniciar o PC. O
   endereço aparece no `status`, no formato `https://nome-do-pc.xxxx.ts.net`.
4. Conferido em 22/09/2026: certificado válido, cabeçalhos de segurança
   presentes, e a API enxerga o IP de quem acessa (não o do proxy) — o
   bloqueio de tentativas de login vale por pessoa.

Para desligar o acesso pela internet (sem parar o sistema):
`tailscale funnel --https=443 http://127.0.0.1:8090 off`.

## Dia a dia

```powershell
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 estado      # o que está no ar
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 registros api
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 backup      # backup agora
```

- **Não saia da conta do Windows.** O Docker Desktop só roda com a sessão
  aberta. Para se afastar, **bloqueie** a tela (Windows + L): o sistema
  continua no ar.
- Depois de uma queda de energia, o PC precisa ser ligado e alguém precisa
  entrar na conta do Windows. Com isso, Docker, whisper e Ollama voltam
  sozinhos, e os contêineres de produção também (`restart: unless-stopped`).
  Um nobreak evita a maior parte disso.
- Nos celulares, o que for lançado enquanto o PC estiver fora do ar fica
  guardado e é enviado quando ele voltar.

## Atualizar depois de um merge

```powershell
git checkout main
git pull
powershell -ExecutionPolicy Bypass -File tools\producao.ps1 atualizar
```

O `atualizar` oferece um backup antes, reconstrói com o código novo, aplica as
migrações do banco e confere que o app voltou.

**A primeira atualização depois de 24/09/2026 compila o MinIO** a partir do
código-fonte, porque a imagem pronta saiu do ar (ver `known-issues.md`). A
versão é a mesma, e os dados não mudam. Leva alguns minutos e ocupa alguns GB
de cache: libere espaço no C: antes e, depois que o app voltar, rode
`docker builder prune -f`.

## Backup

- **Diário, 3h30** (tarefa `BeloVale-Backup`). Se o PC estiver desligado nesse
  horário, roda assim que ligar.
- **O que vai:** o banco inteiro (pg_dump) e todas as fotos e gravações, com
  um manifesto de contagens e somas SHA-256.
- **HD externo:** a cópia como está; ficam as últimas 30. Informe a pasta uma
  vez:

  ```powershell
  Set-Content "$env:USERPROFILE\.belo-vale\hd-destino.txt" "E:\BeloVale-backup"
  ```

- **OneDrive, pasta `BeloVale-backup`:** a cópia criptografada com AES-256;
  ficam as últimas 14. Depois de subir, ela deixa de ocupar o disco C:.
  **Só sobe se o OneDrive estiver conectado com uma conta** neste PC. Entre
  com a mesma conta do notebook: cada cópia chega lá sozinha, e o notebook
  vira o segundo lugar.
- **Senha da criptografia:** fica em `%USERPROFILE%\.belo-vale\senha-backup.txt`,
  legível só pela sua conta do Windows. **Guarde-a também longe do PC.** Se o
  PC se perder, é a única forma de abrir a cópia da nuvem.
- **Registro:** `%USERPROFILE%\.belo-vale\backup.log`.

**Só conta o que sai do PC.** Uma cópia no mesmo disco não sobrevive a ele.
Se o OneDrive não estiver conectado e o HD não estiver ligado (ou a pasta do
HD estiver no C:), a cópia fica gravada aqui mesmo, mas o backup termina como
**FALHOU**, com o motivo no registro, e o `producao.ps1 estado` mostra:

```
Último backup: belo-vale-2026-09-23_0330 (80,1 MB)
A ÚLTIMA TENTATIVA DE BACKUP FALHOU: ... nenhuma cópia saiu deste PC ...
```

Até 24/09/2026 era diferente, e foi assim que o desktop foi para o conserto
sem nenhuma cópia fora dele (ver `known-issues.md`).

### Verificação semanal

Todo domingo às 4h30 (tarefa `BeloVale-VerificaBackup`), a cópia mais recente
é decifrada e restaurada num banco descartável, sem rede, e as contagens são
comparadas com o manifesto. Nada na produção é tocado. O resultado fica em
`%USERPROFILE%\.belo-vale\verificacao.log`. Para rodar à mão:

```powershell
powershell -ExecutionPolicy Bypass -File tools\backup\verificar-backup.ps1
```

Uma cópia adulterada ou corrompida é recusada: a criptografia detecta a
alteração, e as somas conferem cada arquivo.

### Restaurar depois de perder o PC

Num PC novo, com Docker Desktop e o repositório clonado:

1. `python tools/gerar_env_producao.py` (segredos novos; as sessões antigas
   caem, e todos entram de novo com a própria senha).
2. Suba só o armazenamento. O MinIO é compilado do código no GitHub; sem
   acesso a ele, carregue a imagem guardada no OneDrive (`BeloVale-infra`,
   siga o LEIA-ME) e troque, no compose, o `build` do `minio` pela imagem
   carregada:

   ```powershell
   $P = "compose -p belo-vale --env-file infra/.env.production -f infra/docker-compose.yml -f infra/docker-compose.prod.yml"
   docker $P.Split() up -d --wait db minio redis
   ```

3. Abra a cópia. Da nuvem, decifre primeiro (pede a senha anotada):

   ```powershell
   & "C:\Program Files\Git\usr\bin\gpg.exe" --output backup.tar --decrypt belo-vale-AAAA-MM-DD_HHMM.tar.gpg
   mkdir restaura; tar -xf backup.tar -C restaura
   ```

4. Banco e mídia:

   ```powershell
   $db = docker $P.Split() ps -q db
   docker cp restaura\banco.dump "${db}:/tmp/banco.dump"
   docker $P.Split() exec -T db pg_restore -U ingestion -d ingestion --no-owner --exit-on-error /tmp/banco.dump
   docker run --rm -v belo-vale_minio_data:/data -v "${PWD}\restaura:/b:ro" postgres:17-alpine tar xzf /b/midia.tgz -C /data
   ```

5. Suba o resto e aplique as migrações, caso o código seja mais novo que a
   cópia:

   ```powershell
   docker $P.Split() up -d --build --wait
   docker $P.Split() exec -T api uv run --no-sync alembic upgrade head
   ```

6. Confira as contagens com as do `manifesto.txt` da cópia.

## Espaço em disco

Em 22/09/2026 o disco C: tinha **6 GB livres de 222 GB**:

- **Docker: 24 GB.** Apaguei 13 GB de cache de build, mas o disco virtual do
  Docker não encolhe sozinho. O espaço ficou livre para o banco, as fotos e as
  gravações, dentro do Docker, e não para o Windows.
- **Downloads: 8 GB. OneDrive: 15 GB guardados no PC.**

Para devolver espaço ao C:, sem risco para os dados:

1. **Compactar o disco do Docker** (`docker_data.vhdx`, 24 GB). Isso **para
   todos os contêineres, inclusive os de outros projetos**. Feche o Docker
   Desktop (ícone perto do relógio → Quit) e, num PowerShell **como
   administrador**:

   ```powershell
   wsl --shutdown
   diskpart
   ```

   Dentro do `diskpart`:

   ```
   select vdisk file="C:\Users\caiol\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
   attach vdisk readonly
   compact vdisk
   detach vdisk
   exit
   ```

   Depois, abra o Docker Desktop de novo; a produção volta sozinha.
2. No OneDrive: clicar com o botão direito na pasta → **Liberar espaço**.
3. Revisar a pasta Downloads.

## Segurança — o que já vale

- A API se recusa a subir em produção sem segredo forte, com o cookie de sessão
  sem `Secure` ou com leitor ou transcritor falso.
- Limite de tentativas de login (por conta e por origem), política de senha,
  sessão curta com renovação em cookie `HttpOnly`/`Secure`.
- Cabeçalhos: CSP só da própria origem, sem iframe, sem sniffing, microfone
  só para o app.
- Compressão só nos arquivos do app, nunca nas respostas da API (BREACH).
- Nenhuma porta aberta na rede local; o único caminho de fora é o Funnel.
- HSTS (`max-age` de um ano, só para o endereço do sistema) e o nginx sem
  anunciar a versão.
- O IP de origem chega à API pelo Funnel: o limite de login distingue quem
  tenta.
