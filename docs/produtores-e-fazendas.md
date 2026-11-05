# Produtores e fazendas

Implementação técnica das frentes offline, biblioteca e ampliação do plano de
05/11/2026. Teste de campo, piloto externo, aplicativo Android e Google Play são
as próximas etapas; esta entrega não representa implantação no servidor real.

## Modelo e autorização

- Uma identidade de usuário pode pertencer a várias fazendas.
- A conta produtora reúne as fazendas e tem um proprietário. A transferência
  mantém o antigo proprietário como administrador; o novo proprietário pode
  remover esse vínculo e seus acessos às fazendas da conta.
- Funcionários têm vínculo e papel por fazenda: operador, revisor ou administrador.
- O papel histórico em `users.role` não concede acesso global aos produtores.
  A administração da plataforma não é concedida ao criar uma conta produtora.
- A aplicação envia `X-Farm-ID` e o servidor verifica o vínculo em cada operação.
  Com uma só fazenda acessível, pode inferi-la; com várias, exige seleção.
- Mídias, propostas, importações, exportações, equipes e processamento em segundo
  plano respeitam o contexto da fazenda. O worker confere novamente o acesso do
  remetente antes da leitura. Brincos repetidos entre fazendas são válidos.
- A carga de propostas e a avaliação do leitor aceitam `--farm-id`. Não escolhem
  entre várias fazendas por posição no banco. Scripts históricos de manutenção
  recusam instalações com mais de uma fazenda; devem rodar só em cópia isolada.
- Gatilhos no banco recusam relações entre animais, origens e medições de
  fazendas diferentes. Referências históricas e correções continuam preservadas.

## Começar pelo aplicativo

1. Na entrada, escolher **Sou produtor: criar conta**, informar e-mail, senha,
   nome do produtor/empresa e nome da primeira fazenda.
2. Confirmar o link recebido por e-mail e entrar. A primeira fazenda começa
   vazia; não recebe cópias de animais, insumos ou preços de outro produtor.
3. Em **Fazendas e equipe**, configurar fuso e lotes. Cada linha de lote começa
   com `ordenha:` ou `manejo:`. Não é permitido remover/mudar o tipo de um lote
   com animais ainda atribuídos a ele.
4. Cadastrar os animais em **Animais** ou importar CSV em **Fazendas e equipe**.
   O arquivo tem `brinco;nome;lote`; lote é opcional. A prévia informa erros e
   registros já existentes. Linhas inválidas impedem a aplicação; os existentes
   permanecem intactos. O limite é de 5000 linhas e 5 MB.
5. Configurar insumos, dietas e preço do leite na área de Insumos.
6. Adicionar outras fazendas e alternar pelo seletor do topo.
7. Convidar integrantes pelo e-mail. A pessoa aceita entrando com a identidade
   destinatária; um produtor pode trabalhar como operador em outra fazenda.

O convite pode ser cancelado ou vencer. Sua aceitação também verifica se o
remetente ainda pode administrar a fazenda. Remover alguém da equipe não muda
sua senha nem encerra sua identidade em outras operações. A recuperação de
senha é feita pelo próprio usuário por e-mail; redefinição administrativa de
uma senha compartilhada com outras áreas de trabalho é recusada.

## E-mails transacionais

No ambiente da API, configurar:

```dotenv
PUBLIC_APP_URL=https://endereco-do-produto
SMTP_HOST=servidor-smtp
SMTP_PORT=587
SMTP_FROM=contas@dominio-do-produto
SMTP_USER=
SMTP_PASSWORD=
SMTP_STARTTLS=true
```

O Compose transmite essas variáveis somente à API. `PUBLIC_APP_URL` é a origem
dos links, não um endereço enviado pelo navegador. Na produção, usar HTTPS e
configurar o SMTP de quem opera o produto. Sem configuração, os fluxos que
precisam enviar e-mail informam indisponibilidade; nenhum token é mostrado na
resposta HTTP ou guardado em texto puro no banco.

Confirmação e convites vencem em 24 horas; recuperação em uma hora. Links são
de uso único, uma nova emissão invalida a anterior do mesmo contexto e há limite
de solicitações por ação/origem. A recuperação revoga sessões renováveis.

Nos E2E, usar os dois arquivos Compose. O Mailpit em `http://localhost:8025`
recebe as mensagens exclusivamente da pilha descartável de testes.

## Migração da Belo Vale

As migrações `0017_producers_and_farms` e `0018_farm_integrity` são aditivas.
A primeira cria a conta produtora da fazenda existente e seus vínculos de equipe;
o administrador ativo mais antigo se torna proprietário. Conferir essa escolha
no ensaio antes de implantar. Os papéis e o estado ativo anteriores são
preservados nos vínculos, assim como o fuso e a configuração de lotes.

Uma origem legada com mais de uma fazenda, ou com fazenda e nenhum administrador
ativo, é recusada antes de qualquer mudança parcial. Isso exige classificar a
origem em um ensaio próprio; a migração não adivinha proprietários. Instalações
novas começam sem conta/fazenda e são preparadas pelo cadastro público.

O teste `test_tenant_migration.py` monta o schema anterior com o código do commit
`e6a21da`, importa a baseline completa e compara registros antes/depois: 401
animais, 152 medições, lotações, insumos, preços, dietas e auditoria. Confere
também equipe, proprietário, downgrade de uma operação única e recusa atômica
de uma origem ambígua. O teste usa banco descartável próprio.

Antes de atualizar a produção: verificar o backup, ensaiar numa cópia e
sincronizar as filas dos aparelhos na origem antiga. O downgrade para operação
global é recusado depois que houver vários produtores/fazendas.

## Offline e biblioteca

A fila usa IndexedDB e só confirma persistência quando a transação termina.
Substituir um lançamento guardado usa a mesma chave: falha de espaço/aborto
não apaga o valor anterior. Sem armazenamento persistente disponível, o app
informa que não conseguiu guardar, em vez de aceitar uma fila somente em memória.

Folhas e fila são separadas por identidade e fazenda. Cada envio novo conserva
a fazenda de origem; alternar a seleção não muda o destino. A origem de itens
antigos que não tinham fazenda explícita continua sujeita à validação do animal
no servidor; itens recusados permanecem para conferência, sem descarte silencioso.

Depois de uma preparação com sinal, a identidade local pode retomar a área de
trabalho por até sete dias sem token persistente. As folhas já carregadas ficam
no aparelho. Sair voluntariamente limpa essa identidade local; a fila permanece
vinculada ao autor. Ao reconectar, a autorização no servidor é obrigatória.
O envio ocorre com o aplicativo aberto/reaberto; não há promessa de execução
com o processo encerrado, nem de login inicial sem conexão.

O service worker só troca a página guardada depois de obter suas partes e
mantém também os arquivos da versão anterior. Fotos podem ser tiradas ou
escolhidas da biblioteca, com prévia quando o navegador suporta o formato.
JPEG, PNG e HEIC passam pelo decodificador e pela normalização de orientação.
Arquivos disponíveis apenas na nuvem do celular podem exigir conexão para
serem escolhidos. Ler a mídia por IA continua dependendo do servidor.

## Limites e operação

Novas contas têm, inicialmente, 1 GB de arquivos e 100 leituras por dia UTC,
compartilhados por suas fazendas. O consumo é visível ao responsável. Um
bloqueio transacional impede que envios simultâneos ultrapassem juntos o limite.
O armazenamento soma mídias e arquivos de coleta guardados no banco. Os limites
são configurações administrativas da conta produtora, não algo que
o cliente possa aumentar pelo navegador. Não foram implementados planos pagos.

O operador da plataforma administra a chave Gemini e a capacidade do serviço.
O contador controla leituras; não é faturamento por tokens nem preço em reais.
Dimensionamento comercial e capacidade de um piloto externo devem ser medidos
na próxima etapa com os volumes e a concorrência dos participantes.

Os backups completos já incluem as novas tabelas no dump PostgreSQL. Para
recuperação seletiva, restaurar primeiro o backup numa instalação isolada,
atualizar essa cópia até a mesma versão e configurar `RESTORE_SOURCE_POSTGRES_URL`
e `RESTORE_SOURCE_MINIO_URL`, `RESTORE_SOURCE_MINIO_ACCESS_KEY`,
`RESTORE_SOURCE_MINIO_SECRET_KEY` no ambiente de manutenção. O destino usa as
configurações normais da API. Rodar:

```bash
python -m app.core.recover_farm --farm-id UUID-DA-ORIGEM
python -m app.core.recover_farm --farm-id UUID-DA-ORIGEM --apply
```

O primeiro comando confere a origem e mostra contagens. O segundo cria outra
conta/fazenda, com novos IDs e arquivos conferidos por hash; não substitui
operações existentes. Identidades atuais de mesmo e-mail prevalecem, sem
alterar suas senhas ou privilégios globais. O mapa entre IDs antigos e novos
fica na auditoria. Conferir a cópia recuperada antes de decidir qualquer troca
operacional. A ferramenta exige memória suficiente para as mídias selecionadas;
uma falha depois de gravar mídias pode deixar arquivos órfãos no novo prefixo,
que devem ser conferidos pela manutenção, sem remover os arquivos de origem.

## Validação e próximos passos

Rodada local de 05/11/2026:

| Verificação | Resultado |
| --- | --- |
| Backend completo, PostgreSQL e Redis reais | 955 aprovados, 3 ignorados |
| Frontend | 281 aprovados em 26 arquivos |
| Tipos e build de produção | Aprovados |
| E2E Chromium, pilha Docker completa e SMTP Mailpit | 27 aprovados |
| Regressão após revisão final: produtores, migração e ferramentas | 43 aprovados |
| Scanner de credenciais | Zero ocorrências |
| Sintaxe do script de atualização e verificação de whitespace | Aprovadas |

Os três testes ignorados precisam de FFmpeg no processo Python local; a imagem
do worker contém FFmpeg, e a gravação/envio de áudio foi exercitada no E2E.
Os leitores de IA são falsos nessa pilha, para não enviar dados ou consumir
serviços externos. A qualidade de leitura real não foi medida nesta entrega.

Testes de integração usam dois produtores independentes, múltiplas fazendas,
vínculos diferentes, revogação, mídia, limites e recuperação. O Playwright
exercita cadastro pela interface, entrega de e-mail em SMTP de teste, confirmação,
configuração, importação e alternância de fazendas. Também há regressões de
persistência em IndexedDB, transação abortada e reabertura offline no navegador.

Essas verificações não substituem o teste no aparelho físico, o teste no curral
ou o piloto externo. Esses marcos permanecem depois da ampliação no plano.
