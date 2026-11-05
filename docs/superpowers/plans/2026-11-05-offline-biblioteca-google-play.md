# Plano: offline, biblioteca, ampliação para produtores e Google Play

Data: 05/11/2026. Base analisada: `main`, commit `e6a21da`.
Status: implementação técnica concluída até a ampliação para produtores e
fazendas, validada em ambiente local isolado. Campo, piloto, implantação real,
Android e publicação permanecem como próximas etapas.

Entrega e instruções: [Produtores e fazendas](../../produtores-e-fazendas.md).

Objetivo: comprovar o uso no curral sem conexão, permitir escolher uma foto já
existente no celular, ampliar o produto para vários produtores administrarem
suas fazendas e preparar uma versão Android distribuída pela Google Play.

## Premissas e sequência

- Manter o aplicativo web atual como base do produto.
- A Belo Vale II é a primeira fazenda atendida. A visão do produto é permitir
  que outros produtores criem suas contas e administrem suas próprias fazendas.
- Planejar distribuição pública na loja, com cadastro de produtores e acesso
  aos dados restrito aos vínculos e permissões de cada fazenda.
- Iniciar o levantamento da conta Play Console desde o começo, pois a verificação
  e os testes exigidos pelo Google podem determinar o prazo total.
- Executar: diagnóstico offline → biblioteca → ampliação para produtores e
  fazendas → validação integrada no campo → piloto com produtores independentes →
  pacote Android → testes pela loja → solicitação de publicação.
- Uma prova pequena de TWA pode antecipar a identificação de limitações Android;
  a preparação da versão para lançamento depende do aceite da ampliação.
- Projetar a persistência offline e o envio da biblioteca considerando desde já
  a conta produtora, a fazenda e o autor, evitando refazer essas entregas depois.

## Diagnóstico inicial da base `e6a21da` (antes desta implementação)

| Parte | Evidência | Consequência para o trabalho |
| --- | --- | --- |
| Fila persistente | `apps/web/src/offline/outbox.ts`, IndexedDB | Já existe base para produção, fotos e áudios sem sinal |
| Retentativas | `apps/web/src/offline/OutboxContext.tsx` | Envia ao abrir, voltar a conexão e periodicamente com o app em execução |
| Cache do aplicativo | `apps/web/public/sw.js`, registro em `src/main.tsx` | Precisa ser testado no build de produção, não apenas no Vite de desenvolvimento |
| Sessão local | `apps/web/src/auth/session.ts`, `sessionStorage` | Recarregar e encerrar completamente o processo são cenários diferentes |
| Folhas de produção | `ProductionPage.tsx`, `sessionStorage`, chave por data/lote | Conferir persistência, preparação de todos os lotes e isolamento entre contas |
| Teste E2E offline | `apps/web/e2e/offline.spec.ts` | Cobre lançamento, recarga e sincronização; não comprova encerramento real do app |
| Upload de foto | `SendPhoto.tsx`, `SendUpload.tsx`, `capture="environment"` | O seletor pode priorizar a câmera; falta uma escolha explícita da biblioteca |
| Formatos de imagem | `media_sniffing.py`, `image_preprocessing.py` | HEIC é reconhecido; ainda é preciso comprovar a decodificação e a leitura completas |
| Aplicativo instalável | `public/manifest.json`, ícones e service worker | Existe PWA; não há projeto Android versionado |
| Resolução de fazenda | `apps/api/app/routers/registry.py`, `resolve_current_farm` | Exige exatamente uma fazenda na instalação; precisa ser substituída por contexto autorizado |
| Permissões atuais | `User.role`, `app/core/security.py`, `routers/users.py` | Papel e gestão de contas são globais; precisam respeitar os vínculos de cada produtor/fazenda |
| Lotes atuais | `app/services/lot_kind.py` | Nomes da Belo Vale estão fixados no domínio; novos produtores precisam configurar seus lotes |

A tabela acima preserva o diagnóstico inicial. A implementação e os testes
automatizados posteriores estão descritos abaixo e no documento da entrega.
Não houve teste em aparelho físico, avaliação da conta Play Console ou publicação.

## Frente 1 — comprovar e corrigir o offline

Contrato inicial: depois de uma preparação com sinal, a pessoa consegue usar a
folha disponível, lançar produção e guardar fotos/áudios no aparelho. A leitura
por IA e a aprovação no servidor dependem de conexão. O envio é retomado com o
app aberto ou reaberto; execução com o processo encerrado não será prometida.

- [x] Executar testes unitários, integração e E2E com frontend compilado e
  PostgreSQL, Redis, S3 e worker reais em pilha descartável.
- [x] Conferir lançamento sem rede, recarga, troca de tela, fechamento da página,
  retomada local e sincronização no navegador Chromium.
- [x] Conferir foto da biblioteca sem rede: bytes preservados em IndexedDB após
  fechar/reabrir a página, seguidos do envio ao servidor na reconexão.
- [x] Separar folhas e fila por identidade/fazenda; conservar a origem de cada
  envio mesmo ao alternar fazendas; autorização sempre revalidada no servidor.
- [x] Confirmar gravação apenas no término da transação IndexedDB; testar
  aborto de substituição sem apagar o valor anterior e recusar armazenamento
  somente em memória quando IndexedDB está indisponível.
- [x] Preservar arquivos da versão anterior e só substituir a página em cache
  após obter os arquivos da nova versão.
- [x] Distinguir guardado, enviado e recusado, com nova tentativa explícita.

Contrato implementado: retomada local por até sete dias após acesso online,
com folhas previamente carregadas. Saída voluntária limpa a identidade local;
a fila conserva seu autor. Senha e token de servidor não são persistidos em
localStorage. O servidor continua validando toda sincronização. Não há envio
prometido com o processo encerrado nem primeiro login sem conexão.

Aceite técnico: testes automatizados aprovados. Encerramento do processo real,
reinício do aparelho, bloqueio de tela, limites de armazenamento e atualização
instalada nas plataformas físicas integram o teste de campo após a ampliação.

Arquivos principais: `src/offline/*`, `src/auth/session.ts`, `src/App.tsx`,
`features/production/ProductionPage.tsx`, `public/sw.js`, testes correspondentes
e `docs/teste-de-campo-iphone.md`.

## Frente 2 — escolher foto da biblioteca

Fluxo proposto: Revisão → Enviar foto → **Tirar foto** ou **Escolher da
biblioteca** → conferir a imagem → informar lote opcional → Enviar.

- [x] Dois seletores: câmera com `capture="environment"` e biblioteca sem
  `capture`, reutilizando upload, validações e fila existentes.
- [x] Prévia, substituição/cancelamento e confirmação antes de enviar uma foto.
- [x] JPEG, PNG, orientação e arquivo inválido cobertos pelos testes existentes;
  decodificador HEIC instalado e verificado com arquivo HEIC codificado em teste.
- [x] Regressões do seletor, persistência e envio offline no navegador.

Aceite técnico: seleção explícita e cadeia de persistência/envio validadas.
Abrir a interface nativa da câmera/biblioteca e fotografar HEIC no iPhone real
serão conferidos no campo. Arquivo disponível apenas na nuvem pode exigir rede.

Arquivos principais: `features/review/SendPhoto.tsx`, `SendUpload.tsx`, testes de
foto e offline, estilos e, se a medição exigir, decodificação de imagem na API.

## Frente 3 — Ampliação para produtores e fazendas

Resultado de produto: um produtor cria sua conta, cadastra sua fazenda, monta a
equipe e começa a trabalhar. Outro produtor faz o mesmo na mesma plataforma,
com seus próprios dados e configurações. Um produtor pode administrar mais de
uma fazenda; uma pessoa pode ter permissões diferentes em fazendas distintas.

A implementação substitui a resolução global anterior por contexto autorizado
e vínculos por conta/fazenda, com migração do legado e configuração por fazenda.

### Modelo de contas, fazendas e equipe

- [x] Modelar a conta produtora (pessoa ou organização responsável), suas fazendas,
  a identidade de cada usuário e os vínculos que concedem acesso.
- [x] Definir proprietário, administrador, revisor e operador por vínculo, com
  regras para convidar, aceitar convite, remover acesso e transferir propriedade.
- [x] Separar administração da plataforma de administração de uma fazenda.
  O administrador de um produtor não pode gerenciar contas de outros produtores.
- [x] Planejar migrações que criem a conta produtora da Belo Vale II e vinculem
  fazenda e equipe existentes, preservando dados, permissões e auditoria.

### Entrada de novos produtores e experiência do aplicativo

- [x] Criar cadastro do produtor, confirmação de contato, recuperação de acesso
  e configuração inicial da primeira fazenda, sem depender de scripts manuais.
- [x] Oferecer seleção de fazenda e indicar claramente a fazenda ativa nas telas
  de produção, revisão, cadastro, importação, impressão e exportação.
- [x] Permitir convidar funcionários e gerenciar permissões no contexto correto.
- [x] Permitir configurar nome, fuso da operação, lotes, grupos de manejo,
  insumos, dietas e preço do leite por fazenda. Preservar os valores atuais da
  Belo Vale na migração, incluindo as regras do dia de trabalho e datas.
- [x] Remover dependências de nomes de lotes, marca, contatos, arquivos de origem
  e dados de demonstração específicos da Belo Vale na entrada de novos clientes.
- [x] Dar ao novo produtor caminhos para cadastrar ou importar seus animais;
  criar uma fazenda vazia, sem copiar o rebanho ou preços de outro cliente.

### Separação de dados e contexto autorizado

- [x] Substituir `resolve_current_farm` por resolução explícita de fazenda com
  validação do vínculo e da permissão no servidor em cada operação.
- [x] Revisar consultas, alterações, buscas, histórico, mídias, propostas,
  importações, exportações, contas e auditoria para aplicar esse contexto.
- [x] Garantir integridade dos relacionamentos no banco: um registro não pode
  apontar para animal, origem ou outro recurso pertencente a outra fazenda.
- [x] Levar conta produtora, fazenda e autor às tarefas em segundo plano e
  validar o contexto ao processar; trocar de fazenda não redireciona a tarefa.
- [x] Separar cache, folhas e fila offline por conta produtora/fazenda/usuário.
  Itens pendentes continuam vinculados à origem mesmo após alternar a fazenda.
- [x] Recusar a sincronização se o autor perdeu acesso, preservando o item e
  explicando o motivo; a fila não concede autorização por conta própria.
- [x] Manter a identidade operacional do animal e a detecção de arquivos
  repetidos no contexto da fazenda: o mesmo brinco em fazendas distintas é válido.

### Operação técnica para vários clientes

- [x] Limites compartilhados pelas fazendas da conta: inicialmente 1 GB de
  arquivos e 100 leituras por dia UTC, com consumo visível e reserva transacional.
- [x] Recuperação seletiva de fazenda de backup restaurado, criando novos IDs e
  prefixos sem sobrescrever outros clientes; simulação padrão antes de aplicar.
- [x] Migração ensaiada com código anterior e baseline canônica completa,
  conferindo animais, medições, lotações, equipe, insumos, preços e auditoria.
  Origem ambígua é recusada sem alterações parciais.
- [x] Integração com dois produtores, múltiplas fazendas, permissões diferentes,
  acesso direto por ID, convites, revogação, mídias, limites e recuperação.
- [x] E2E de cadastro público, SMTP de teste, confirmação de contato,
  configuração, importação de animais e alternância de fazenda.
- [x] Documentar SMTP, migração, ensaio de backup, limites, scripts de
  manutenção e condições da implantação real.

Aceite:

- [x] Um novo produtor inicia sua operação sem intervenção no banco ou scripts.
- [x] Dois produtores usam o sistema simultaneamente sem consultar, alterar ou
  misturar dados, arquivos, equipes ou filas um do outro.
- [x] Um produtor alterna entre suas fazendas, mantendo configurações e dados
  separados; permissões são respeitadas por fazenda.
- [x] Offline, biblioteca, leitura, revisão, impressão e exportação passam nas
  suítes técnicas; os testes de isolamento cobrem produtores/fazendas distintos.
- [x] Dados e histórico da Belo Vale são preservados e conferidos na migração.
- [x] Ampliação tecnicamente validada para iniciar o teste de campo. A preparação
  da versão Android para lançamento depende também do aceite do campo e do piloto.

Áreas principais: modelos e migrações; autenticação e permissões; resolução da
fazenda em todas as rotas; contas e convites; configurações de lotes e datas;
serviços, armazenamento e workers; seleção de fazenda, cache e fila no frontend;
testes de integração/E2E; operação, importação inicial e documentação.

## Etapa seguinte — teste de campo após a ampliação e piloto

Fora do ponto de parada autorizado para esta implementação:

- [ ] Ensaiar atualização em cópia do backup real, conferir o proprietário
  escolhido, configurar SMTP e implantar na operação real em janela combinada.
- [ ] Registrar matriz por versão/aparelho: Android/Chrome/PWA e iPhone/Safari/PWA.
  Conferir primeira abertura, modo avião, bloqueio, encerramento do processo,
  reinício, mudança de dia, atualização e espaço indisponível.
- [ ] Conferir totais, observações, vários lotes, JPEG/PNG/HEIC do aparelho,
  câmera/biblioteca, áudio real e sincronização sem duplicação ou perda.
- [ ] Repetir troca de produtor/fazenda, saída, revogação, conflito e sinal
  instável nos aparelhos, comparando os registros com o servidor.
- [ ] Executar piloto acompanhado com produtores independentes, primeiro com
  dados fictícios e depois com operação autorizada. Medir volume, concorrência,
  duração das tarefas e capacidade antes da abertura ampla.
- [ ] Definir suporte, responsabilidade/custo de IA, retenção, privacidade,
  exportação e encerramento de contas antes de disponibilizar o serviço público.
- [ ] Definir marca pública e o papel do nome Belo Vale II, domínio e identidade
  de loja. Cobrança permanece em escopo comercial próprio.

Roteiro: [teste de campo](../../teste-de-campo-iphone.md). Após aceite do campo
e do piloto, iniciar a preparação Android abaixo.

## Frente 4 — preparar o aplicativo Android e a Google Play

Recomendação inicial de arquitetura: **Trusted Web Activity (TWA), gerada com
Bubblewrap**, aproveitando o PWA e o navegador Android. Validar câmera,
biblioteca, microfone, sessão, encerramento e offline em uma prova antes de
adotar definitivamente. Se uma limitação reproduzível impedir os requisitos,
avaliar Capacitor, incluindo armazenamento, permissões e manutenção adicionais.

### Preparação que pode começar junto da frente 1

- [ ] Identificar titular, existência e tipo da conta Play Console. Preferir
  propriedade do responsável pelo produto/plataforma; conta de organização
  depende da documentação aplicável.
- [ ] Definir distribuição, nome público, contato de suporte e identificador
  definitivo do pacote, antes da primeira publicação.
- [ ] Confirmar um endereço HTTPS estável e controlado pelo produto. O endereço
  atual pode ser avaliado; domínio próprio é recomendação, não requisito inventado.
- [ ] Se houver mudança de origem, esvaziar/conferir as filas no endereço antigo
  e planejar a transição: IndexedDB e sessões não migram automaticamente.

### Pacote e identidade do aplicativo

- [ ] Criar projeto Android reproduzível, com ferramentas e versões registradas.
- [ ] Conferir manifesto PWA, identificador estável, ícones e apresentação inicial.
- [ ] Gerar Android App Bundle (`.aab`), configurar Play App Signing e guardar
  com o titular o material de upload/recuperação que lhe cabe.
- [ ] Servir `/.well-known/assetlinks.json` como JSON, com pacote e certificado
  corretos; validar também a assinatura da versão instalada pela Play.
- [ ] Configurar o nível de API exigido na submissão. Consulta de 05/11/2026:
  novos apps de celular devem segmentar Android 16/API 36 ou superior [3].
- [ ] Testar a versão entregue pela loja, não apenas APK instalado manualmente.

### Conteúdo da loja e acesso de revisão

- [ ] Preparar descrição, categoria, classificação, ícones, imagens e capturas
  com dados fictícios, além do contato de suporte.
- [ ] Disponibilizar política de privacidade no app e em URL pública e preencher
  Segurança dos dados com base no fluxo real: contas, fotos, áudios, servidor,
  backups e processamento Gemini, inclusive retenção e uso de fornecedores [6].
- [ ] Incluir os caminhos de solicitação de exclusão dentro e fora do aplicativo
  para o cadastro público planejado, considerando propriedade de fazendas,
  vínculos de equipe e retenção justificada da trilha operacional [7].
- [ ] Fornecer acesso e instruções suficientes para a revisão do Google [8].
  Preparar demonstração explícita, com dados fictícios e banco isolado, acessível
  no mesmo aplicativo submetido. Aproveitar os vínculos e a separação de dados
  da frente 3 para a experiência da conta de revisão, conferindo também o
  isolamento do ambiente demonstrativo em relação à operação real.
- [ ] Usar seleção pontual de imagens e conferir o manifesto Android gerado,
  evitando acesso amplo à biblioteca sem necessidade funcional [5].

### Teste e publicação

- [ ] Distribuir por teste interno e repetir a matriz offline, biblioteca,
  gravação, cadastro, seleção de fazenda, permissões, login, atualização e
  retomada no pacote instalado pela loja.
- [ ] Se a conta estiver sujeita à exigência de novas contas pessoais, organizar
  teste fechado: no mínimo 12 testadores inscritos continuamente por 14 dias,
  seguido da solicitação de acesso à produção [4].
- [ ] Corrigir o que o teste e os relatórios da Play demonstrarem e registrar
  versão, evidências e instruções operacionais.
- [ ] Preparar a submissão final e a estratégia de acompanhamento da primeira
  versão; a liberação depende da análise do Google.

Aceite: AAB aceito no canal de testes, associação de domínio válida, funções
principais aprovadas no app instalado pela Play, formulários completos e acesso
de revisão funcional. Estar preparado para enviar e estar publicado são marcos
diferentes.

## Entregas e estimativa inicial

| Marco | Entrega verificável |
| --- | --- |
| 1 | Relatório offline com matriz executada, problemas reproduzidos e correções |
| 2 | Câmera e biblioteca funcionando e testadas com a fila offline |
| 3 | Modelo de contas/produtores/fazendas e plano de migração definidos |
| 4 | Ampliação implementada, migração conferida e testes técnicos aprovados |
| 5 | Dia de campo após a ampliação, com Android e iPhone, registros e comparação com o servidor |
| 6 | Piloto com produtores independentes aprovado |
| 7 | Prova TWA aprovada e pacote Android reproduzível em teste interno |
| 8 | Material da loja, demonstração, formulários e teste fechado quando exigido |
| 9 | Submissão e acompanhamento até a decisão da loja |

A estimativa anterior de **7 a 12 dias úteis** correspondia ao escopo sem a
ampliação para vários produtores e **não representa o prazo deste plano**.
Reestimar por frente após especificar contas/vínculos, migração, cadastro e
capacidade do piloto. A ampliação é uma entrega estrutural, com validação própria,
que antecede a preparação Android para lançamento.

Somar disponibilidade dos aparelhos/pessoas para o campo e prazos externos:
verificação da conta, eventual D-U-N-S e teste fechado/análise da Play. A taxa
de cadastro informada pelo Google é única, de US$ 25 [9]; câmbio e custos de
domínio/ambiente dependem das escolhas do titular.

Na execução, separar as mudanças em PRs revisáveis: diagnóstico/correções
offline; biblioteca; modelo e migração de produtores/fazendas; contexto e
permissões; cadastro, convites e configuração; adaptação offline e workers;
validação no campo; piloto; empacotamento Android e associação; preparação da
loja e demonstração.
Usar ambientes isolados e reexecutar os checks pertinentes.

## Fontes oficiais consultadas em 05/11/2026

1. [TWA: visão geral](https://developer.android.com/develop/ui/views/layout/webapps/trusted-web-activities).
2. [Bubblewrap e associação do site](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start).
3. [Nível de API exigido](https://support.google.com/googleplay/android-developer/answer/11926878?hl=pt-BR).
4. [Teste de novas contas pessoais](https://support.google.com/googleplay/android-developer/answer/14151465?hl=pt-BR).
5. [Permissões de fotos e vídeos](https://support.google.com/googleplay/android-developer/answer/16558241?hl=en).
6. [Dados do usuário e privacidade](https://support.google.com/googleplay/android-developer/answer/10144311?hl=en).
7. [Exclusão de conta](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en).
8. [Preparação para revisão](https://support.google.com/googleplay/android-developer/answer/9859455?hl=en).
9. [Cadastro e taxa do Play Console](https://support.google.com/googleplay/android-developer/answer/6112435?hl=en).
10. [Informações da conta e D-U-N-S](https://support.google.com/googleplay/android-developer/answer/13628312?hl=en).
11. [Digital Asset Links e Play App Signing](https://developer.android.com/training/app-links/configure-assetlinks).

Reconfirmar requisitos no Play Console e nas fontes oficiais quando a submissão
for preparada, pois as regras podem mudar.
