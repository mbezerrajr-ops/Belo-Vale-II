# Belo Vale II

Sistema de gestão do rebanho leiteiro da fazenda Belo Vale II: cadastro dos
animais, produção de leite por vaca e por dia, lotes, insumos e custos. É
usado pelo celular, no curral, pelo dono e pelos funcionários.

O diferencial é ler, **na própria fazenda**, a foto da folha de pesagem e a
gravação da ordenha. O que é lido vira **proposta** numa caixa de Revisão:
nada entra no rebanho sem alguém aprovar, e nenhuma foto ou gravação sai
para serviço externo.

**ATENÇÃO — dados reais.** Este repositório contém os dados do rebanho (401
animais, produção, custos). Trate como confidencial e mantenha-o **privado**.

---

## O que o sistema faz

- **Produção:** lançar os litros do dia, lote por lote, inclusive sem sinal
  (fica guardado no celular e sobe quando o sinal volta); importar a coleta
  de uma planilha ou PDF; imprimir a folha de coleta, em branco ou preenchida.
- **Revisão:** enviar a foto da folha ou gravar a ordenha pelo próprio app;
  o que for lido chega como proposta, com a foto ou o áudio ao lado, para
  aprovar, corrigir ou rejeitar.
- **Animais:** buscar, ver a ficha e o histórico de produção, vincular ou
  tirar o brinco, mudar de lote, dar baixa, juntar fichas duplicadas.
- **Painel, Insumos e Medições:** a produção do rebanho e de cada lote, os
  preços e dietas dos insumos, o preço do leite e as medições oficiais.
- **Contas:** três perfis — operador (lança), revisor (corrige, aprova,
  mexe no cadastro) e administrador (também gerencia as contas).

## Princípios que o código defende

- **O brinco é a única identidade.** Nome é descrição: nunca associa um
  animal sozinho, só sugere.
- **Nada entra sem aprovação.** Toda leitura de foto, áudio ou texto vira
  proposta; aprovar usa as mesmas regras do cadastro.
- **Nada se apaga.** Cada medição guarda a origem (base antiga, lançamento,
  arquivo, proposta). Corrigir ou anular cria versão nova, com motivo e autor,
  e o banco garante isso com gatilhos.
- **Nada sai da fazenda.** Os leitores de foto e voz só aceitam endereço
  local (`app/core/local_url.py`).
- **O que protege contra erro do modelo fica no código, não na instrução.**
  Prompt deriva; código não. Cada versão do leitor é medida contra gabaritos.

## Como está montado

| Pasta | O quê |
| --- | --- |
| `apps/api` | API em FastAPI (Python 3.13), PostgreSQL 17 com migrações Alembic, worker Celery que lê fotos (Ollama, `qwen2.5vl`) e áudios (whisper.cpp) |
| `apps/web` | App em React + Vite, instalável no celular, com fila offline no próprio aparelho |
| `infra` | Docker Compose (api, worker, PostgreSQL, Redis, MinIO, nginx) e a variante de produção |
| `tools` | Operação da produção (`producao.ps1`), backup e verificação, varredura de credenciais, scripts de manutenção de dados |
| `docs` | Runbooks, decisões registradas, pendências, relatórios |
| `belo-vale-ii-projeto-completo` | A plataforma antiga e a base de dados de origem (ver abaixo) |

A produção roda num PC da fazenda, com placa de vídeo para a leitura, e é
acessada pela internet pelo Tailscale Funnel, com HTTPS. Os leitores rodam
fora do Docker, na mesma máquina.

## Documentação

- [`docs/runbook-producao.md`](docs/runbook-producao.md) — como a produção roda, atualizar, backup, restaurar.
- [`docs/runbook-local.md`](docs/runbook-local.md) — ambiente de desenvolvimento, testes, leitores locais.
- [`docs/known-issues.md`](docs/known-issues.md) — **pendências abertas** (no topo) e todas as decisões registradas.
- [`docs/vision-provider-status.md`](docs/vision-provider-status.md) — o leitor de folhas, versão a versão, com as medições.
- [`docs/teste-de-campo-iphone.md`](docs/teste-de-campo-iphone.md) — roteiro do teste no curral.
- [`docs/superpowers/`](docs/superpowers/) — especificações e planos de cada fase.

## Testes e CI

`.github/workflows/ci.yml` roda em todo push e PR: varredura de credenciais,
regras do backup, contrato da base antiga, a suíte do backend contra
PostgreSQL e Redis reais (com a migração mais recente descendo e subindo),
os testes, os tipos e o build do frontend, e o Playwright contra a pilha
Docker inteira. Como rodar cada parte à mão está no runbook local.

---

## Plataforma antiga (legado)

Antes do sistema atual, a fazenda usava uma página única publicada como
Artifact do Claude, sem backend. Ela e os dados de origem ficam em
[`belo-vale-ii-projeto-completo/`](belo-vale-ii-projeto-completo/README.md),
como histórico e como fonte da base importada.

A fonte versionada da base antiga é
`belo-vale-ii-projeto-completo/plataforma/state_canonical.json` (401 animais,
152 medições), validada no CI:

```powershell
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py validate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json
```

**Credenciais legadas.** A senha do login antigo ficava em texto puro no estado
e na documentação; foi **redigida do HEAD** e substituída pelo marcador
`LEGADO-SEM-SEGURANCA`, e `tools/credential_scan.py` impede a reintrodução. O
histórico Git não foi reescrito, por decisão registrada: a mitigação é a
rotação da credencial. Detalhes em `docs/known-issues.md`.
