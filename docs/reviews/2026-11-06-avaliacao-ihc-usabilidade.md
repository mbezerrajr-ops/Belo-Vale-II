# Avaliação de IHC e usabilidade — 6 de novembro de 2026

**Base avaliada:** `main`, commit `3af3a0f`. **Natureza:** avaliação heurística, navegação em navegador e inspeção do código. **Resultado:** a estrutura visual é utilizável, mas existem ambiguidades de linguagem, operações sujeitas a erro e caminhos incompletos para uma fazenda nova. A maior prioridade está na compreensão das tarefas e na confiabilidade das informações apresentadas.

Esta avaliação não altera a interface, o banco de produção ou a publicação do site. Mantém a definição do produto: cada usuário acessa uma única fazenda; outras pessoas podem trabalhar nessa mesma fazenda. Não recomenda retomar o seletor de fazendas ou uma barra administrativa superior.

## Método e limites

- Inspeção das áreas de acesso, criação de conta produtora, recuperação de senha, Painel, Produção, importação e exportação, Revisão de fotos e áudios, Animais, Insumos, Medições, Contas e Minha conta.
- Navegação na aplicação local com API e dados fictícios, usando a conta administradora de teste. As permissões de operador e revisor foram examinadas no código; não houve execução completa com cada perfil.
- Registro de 56 estados de interface: desktop de 1365 px, temas claro e escuro, e telas de celular de 390 e 320 px. Não são 56 funcionalidades independentes: incluem variações de tela, formulário e tema.
- 46 análises com axe, considerando regras automatizáveis marcadas para WCAG A/AA até 2.2, sem violações reportadas nessa amostra. Nos 47 estados do levantamento inicial, não apareceu transbordamento horizontal da página. Verificação adicional de foco e fechamento por Escape no menu de ações do animal.
- Reprodução de uma rejeição de formulário: a API retornou 422 para fuso horário inválido, e a tela exibiu uma mensagem de conexão. A configuração foi recusada; não foi salva.

Não foi realizada pesquisa com produtores, avaliação com leitor de tela, teste completo por teclado, teste físico no curral ou certificação WCAG. Os testes de leitura automática, envio offline e entrega de e-mails não foram repetidos integralmente nesta avaliação. Onde a evidência é de código ou o impacto é uma hipótese de uso, isso está indicado.

As recomendações se apoiam nas heurísticas de visibilidade, linguagem do usuário, consistência, controle e prevenção de erros de [Nielsen](https://www.nngroup.com/articles/ten-usability-heuristics/). Para formulários e interação por toque, foram consultadas as orientações do W3C sobre [rótulos e instruções](https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html) e [tamanho mínimo dos alvos](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). Uma ambiguidade de texto não foi classificada automaticamente como falha de conformidade.

## Prioridades

**P1 — alta:** pode impedir uma tarefa importante, induzir uma alteração diferente da pretendida ou levar a interpretar um indicador de forma errada. Resolver antes de ampliar o uso por outros produtores.

**P2 — média:** tarefa possível, mas exige descoberta, memorização ou interpretação desnecessária. Ajustar na revisão de usabilidade e validar no protótipo.

São prioridades de produto propostas nesta avaliação, não resultados de uma medição de frequência ou de incidentes em produção.

## Achados

### 01. Importar arquivo e ler uma foto não têm uma relação evidente — P1

**Caminhos:** Produção → Importar arquivo; Revisão → Enviar foto.

**Evidência:** os dois caminhos existem e cumprem funções diferentes. O primeiro recebe CSV/XLSX/PDF de produção; o segundo envia uma imagem para interpretação e posterior aprovação. A própria conversa com o produtor demonstrou dificuldade para encontrar o recurso. No envio da foto também coexistem o seletor nativo de arquivo e o botão “Escolher da biblioteca”, que acionam a mesma escolha.

**Consequência:** quem recebeu uma foto pode procurar “importar” em Produção e concluir que o sistema não aceita sua imagem. “Enviar” também descreve apenas a transferência, sem deixar claro o objetivo da leitura.

**Recomendação:** identificar o caminho existente como “Importar planilha/PDF”, usar “Ler foto da folha” para a imagem e oferecer em Produção um atalho contextual para o envio já existente. No formulário da foto, manter duas escolhas claras: “Tirar foto” e “Escolher foto”. Explicar: “O sistema lê a foto. Confira e aprove os dados antes de entrarem nos registros.” Não criar outra importação de animais ou outra área superior.

**Base:** [ProductionPage](../../apps/web/src/features/production/ProductionPage.tsx), [SendUpload](../../apps/web/src/features/review/SendUpload.tsx#L364), [ReviewInbox](../../apps/web/src/features/review/ReviewInbox.tsx).

### 02. Mudar de lote aceita texto que pode representar outra operação — P1

**Caminho:** Animais → ficha → Mudar de lote.

**Evidência:** observado no navegador: o destino é um campo de texto livre. No código, um nome desconhecido é classificado como grupo de manejo. Lote de ordenha e grupo de manejo possuem vigências separadas; mudar um não encerra o outro. A tela explica a distinção, mas não impede a escolha errada.

**Consequência inferida:** um erro de digitação no nome de um lote de ordenha pode registrar um grupo de manejo e manter o lote anterior. O usuário pode acreditar que concluiu a transferência pretendida. O cadastro de animal também recebe lote/grupo como texto livre.

**Recomendação:** selecionar entre destinos configurados, separados por “Lote de ordenha” e “Grupo de manejo”. Mostrar o destino atual e o novo antes da confirmação. Quando faltar o destino, indicar como cadastrá-lo, em vez de inferir sua categoria silenciosamente.

**Base:** [AnimalDetailPanel](../../apps/web/src/features/animals/AnimalDetailPanel.tsx#L460), [AnimalSearchPage](../../apps/web/src/features/animals/AnimalSearchPage.tsx), [classificação de lotes](../../apps/api/app/services/lot_kind.py#L61), [registro da mudança](../../apps/api/app/services/animal_registry.py#L345). O efeito sobre um animal não foi provocado nesta auditoria; decorre do fluxo de código.

### 03. A tela “Insumos e dieta” não oferece cadastro da dieta — P1

**Caminho:** Insumos.

**Evidência:** a interface permite cadastrar insumos, alterar preços e consultar dietas existentes. Não há controle para definir a quantidade diária de um insumo por lote. Existe função no cliente e endpoint de API para isso, sem ligação na tela atual.

**Consequência:** uma fazenda nova não consegue completar pelo navegador a configuração que alimenta seus custos. A presença de dietas herdadas da fazenda original pode esconder essa lacuna.

**Recomendação:** permitir cadastrar e editar a dieta no contexto do próprio insumo/lote, com quantidade, unidade e retorno do custo resultante. Escrever “kg por dia para o lote inteiro”, distinguindo de consumo por animal. Mostrar a próxima ação quando ainda não houver dieta.

**Base:** [SuppliesPage](../../apps/web/src/features/dashboard/SuppliesPage.tsx#L141), [setSupplyDiet](../../apps/web/src/api/client.ts#L459), [endpoint de dieta](../../apps/api/app/routers/dashboard.py#L200). Confirmado por inspeção da tela e busca dos usos da função no frontend.

### 04. “Lucro/dia” e “Custo/dia” sugerem um alcance maior que o cálculo — P1

**Caminho:** Painel.

**Evidência:** o custo usado é o dos insumos da dieta; o resultado é receita do leite menos esse custo. Não representa todos os gastos da propriedade. Além disso, a ausência de dieta de um lote assume custo zero no cálculo. Na fazenda de teste sem insumos, o cartão mostrava R$ 0,00.

**Consequência:** o produtor pode interpretar o número como lucro líquido da fazenda ou entender ausência de cadastro como ausência de despesa. O sistema já avisa quando falta preço do leite e quando a cobertura de leituras é parcial, o que deve ser preservado.

**Recomendação:** usar “Resultado após alimentação” e “Custo de alimentação/dia”, com explicação curta dos itens considerados. Diferenciar “Dieta não cadastrada” de custo zero confirmado. Quando faltar a base de custo, sinalizar resultado incompleto, evitando apresentá-lo com aparência de cálculo completo.

**Base:** [cartões do painel](../../apps/web/src/features/dashboard/HerdDashboard.tsx#L247), [custo ausente](../../apps/api/app/services/dashboard.py#L307), [resultado calculado](../../apps/api/app/services/dashboard.py#L364).

### 05. Erro de preenchimento é apresentado como problema de conexão — P1

**Caminho:** Minha conta → Configuração da minha fazenda → Fuso horário.

**Reprodução:** preencher “Recife” e salvar. A API responde 422 com “Fuso horário inválido.” A interface mostra “Não foi possível concluir. Confira a conexão e tente novamente.”

**Consequência:** tentar novamente ou conferir a internet não corrige o campo. O usuário recebe uma explicação falsa sobre a causa da recusa.

**Recomendação:** apresentar a mensagem de validação junto ao campo, preservar o preenchimento e levar o foco ao primeiro problema. Reservar a mensagem de conexão para falhas de rede. Aplicar o tratamento também aos formulários que compartilham esse tradutor de erros.

**Base:** [apiMessage](../../apps/web/src/auth/AccountEntry.tsx#L6), [FarmSettings](../../apps/web/src/features/workspace/FarmSettings.tsx).

### 06. Configurar a fazenda exige conhecer formatos técnicos — P2

**Evidência:** o fuso é um campo livre com identificador como `America/Recife`. Lotes são um texto com linhas no formato `ordenha: Nome` ou `manejo: Nome`.

**Consequência:** o produtor precisa aprender uma sintaxe para descrever sua propriedade. Excluir uma linha também funciona como tentativa de remoção de um lote, sem uma ação explícita de remoção. A API já protege lotes em uso, uma defesa importante.

**Recomendação:** lista de cidades/regiões para o fuso e linhas editáveis com “Nome” e “Tipo” para os lotes, incluindo ações explícitas de adicionar/remover. Manter a configuração discreta no local atual; não recolocar um gerenciador de múltiplas fazendas.

**Base:** [FarmSettings](../../apps/web/src/features/workspace/FarmSettings.tsx#L31), [proteção dos lotes em uso](../../apps/api/app/routers/tenancy.py#L380).

### 07. Fazenda nova recebe mensagens vazias sem um próximo passo suficiente — P2

**Evidência:** a criação de uma fazenda começa com lotes vazios. A busca de animais usa “Nenhum animal encontrado para essa busca”, inclusive quando ainda não há cadastro. No painel vazio, a indicação é enviar uma ficha, mas a preparação dos lotes e dos animais também precisa ser descoberta.

**Consequência provável:** o novo produtor pode entender que houve falha na busca ou tentar ler uma folha antes de preparar o cadastro necessário. Esse impacto precisa ser validado com pessoas que nunca usaram o sistema.

**Recomendação:** estados vazios específicos para primeiro uso, com três passos curtos e links para as telas existentes: configurar lotes, cadastrar animais e lançar/ler a primeira produção. A configuração de custos pode ser apresentada depois. Não exigir um assistente longo nem bloquear quem já sabe trabalhar.

**Base:** [criação da fazenda](../../apps/api/app/routers/tenancy.py#L188), [AnimalSearchPage](../../apps/web/src/features/animals/AnimalSearchPage.tsx), [painel vazio](../../apps/web/src/features/dashboard/HerdDashboard.tsx#L208).

### 08. Formulários da ficha do animal não oferecem saída explícita — P2

**Evidência:** verificado no navegador nos formulários de lote, brinco e edição de cadastro: não há “Cancelar” ou “Fechar”. Acionar o mesmo botão novamente mantém o formulário aberto. É possível trocar de ação ou voltar à busca, mas isso exige descobrir outro caminho. A correção de produção já possui Cancelar.

**Recomendação:** incluir “Cancelar” ao lado da confirmação, fechando o formulário e devolvendo o foco ao botão de origem. Quando houver alteração relevante ainda não salva, informar o descarte de forma proporcional. Não acrescentar confirmação em todo clique rotineiro.

**Base:** [abertura dos formulários](../../apps/web/src/features/animals/AnimalDetailPanel.tsx#L139), [formulário de brinco](../../apps/web/src/features/animals/AnimalDetailPanel.tsx#L395), [ProductionHistory](../../apps/web/src/features/animals/ProductionHistory.tsx).

### 09. “Contas” pode ser entendido como área financeira — P2

**Evidência:** o item abre usuários, permissões e senhas; a página inclui “Nova conta” e “Criar conta”. A explicação interna ajuda, mas só aparece depois de entrar.

**Risco de interpretação:** em um sistema de fazenda com receita e custo, “contas” também pode significar pagamentos e despesas. Não houve teste com participantes para medir essa associação.

**Recomendação:** “Equipe” na navegação e “Adicionar pessoa” na ação. Preservar “Minha conta” para senha e dados pessoais. Descrever cada permissão em termos de tarefas permitidas, aproveitando as explicações já existentes.

**Base:** [UsersPage](../../apps/web/src/features/users/UsersPage.tsx), [navegação](../../apps/web/src/App.tsx#L347).

### 10. “Medições” e “Total no período” deixam o alcance da consulta incerto — P2

**Evidência:** Produção serve ao lançamento; Revisão, à conferência; Medições, à consulta de registros oficiais. Essa diferença existe, mas não é evidente apenas pelos nomes. Em Medições, o cartão diz “Total no período” sem oferecer um período na tela: a consulta não envia datas. O histórico recente exibe somente os primeiros 30 registros após a ordenação, sem explicitar esse limite no título.

**Consequência:** o produtor pode confundir o acumulado de todos os registros retornados com o dia ou mês atual, ou supor que o histórico visível está completo.

**Recomendação:** testar “Histórico de produção” para a consulta; explicitar “Todo o histórico” ou oferecer intervalo de datas com início e fim visíveis. Identificar “30 registros mais recentes” e um caminho para consultar os demais. Uma eventual união de áreas exige protótipo e validação antes de alterar a navegação.

**Base:** [OfficialMeasurements](../../apps/web/src/features/dashboard/OfficialMeasurements.tsx#L64), [consulta de medições](../../apps/api/app/routers/measurements.py#L20).

### 11. A promessa do offline é mais ampla que as condições de funcionamento — P2

**Evidência:** mensagens dizem que “vai sozinho quando o sinal voltar”. O envio é acionado pela aplicação aberta/reaberta, pela volta da conexão e por tentativas periódicas na página. A leitura automática da imagem continua dependendo do servidor. A expressão “neste celular” também aparece no computador. Na fila, um item pode aparecer como “esperando sinal” enquanto o navegador já se considera online.

**Consequência provável:** esperar processamento com o aplicativo fechado, confundir armazenamento local com chegada ao servidor ou interpretar foto enviada como leitura já aprovada.

**Recomendação:** diferenciar os estados “Guardado neste aparelho”, “Enviado”, “Aguardando leitura” e “Aguardando conferência”. Explicar brevemente: “Ao recuperar a conexão, mantenha o aplicativo aberto ou abra novamente para enviar.” Indicar previamente a necessidade de primeiro acesso com conexão e de dados já carregados para as consultas disponíveis offline. Usar estado coerente para tentativa de envio e recusa.

O problema identificado aqui é de comunicação e alcance da promessa. Esta avaliação não conclui que o recurso offline deixou de funcionar.

**Base:** [OutboxStatus](../../apps/web/src/offline/OutboxStatus.tsx#L39), [ciclo de envio](../../apps/web/src/offline/OutboxContext.tsx#L113), [resultado do upload](../../apps/web/src/features/review/SendUpload.tsx#L506), [orientação de instalação](../../apps/web/src/ui/InstallHint.tsx).

### 12. O botão “Mais” muda de nome e esconde sua função de menu — P2

**Evidência:** ao abrir Insumos no celular, o último botão da barra passa a se chamar “Insumos”; em Minha conta, assume esse nome. Ele continua abrindo o menu de outras áreas. Reproduzido no navegador.

**Consequência provável:** o usuário pode perder a referência de onde procurar Medições, Equipe ou Minha conta.

**Recomendação:** manter “Mais” como rótulo estável, com indicação de seleção quando uma área secundária estiver ativa. O título da página informa qual área está aberta.

**Base:** [rótulo da navegação móvel](../../apps/web/src/App.tsx#L624).

### 13. Trocar brinco muda de vocabulário durante a tarefa — P2

**Evidência:** “Trocar brinco” abre um formulário “Vincular brinco” cuja confirmação é “Confirmar vínculo”. O campo de justificativa se chama “Evidência”. A necessidade de justificar uma mudança de identidade é pertinente, mas o vocabulário pode sugerir anexar uma prova ou fazer outro tipo de associação.

**Recomendação:** acompanhar a operação: “Trocar brinco” → “Novo número do brinco” → “Motivo da troca” → “Confirmar troca”. Para animal sem brinco, usar “Registrar brinco”. Manter visíveis o animal e o número anterior. Substituir exemplos com animais da fazenda original por exemplos neutros.

**Base:** [botão e formulário](../../apps/web/src/features/animals/AnimalDetailPanel.tsx#L353).

### 14. “Ler de novo” pode oferecer uma ação indisponível ao operador — P2

**Evidência de código:** no retorno de arquivo duplicado, o botão de reprocessar aparece sem distinguir o perfil. Se a leitura anterior terminou com sucesso, o servidor exige revisor; a explicação só aparece depois da tentativa. Retentar uma leitura que falhou é permitido ao operador e deve continuar disponível.

**Recomendação:** apresentar a ação conforme perfil e estado. Para leitura já concluída, priorizar “Ver leitura existente”; explicar quando a nova leitura depende de revisor. Evitar oferecer repetidamente um botão que será recusado.

**Base:** [retorno de arquivo duplicado](../../apps/web/src/features/review/SendUpload.tsx#L496), [tratamento da recusa](../../apps/web/src/features/review/SendUpload.tsx#L326), [regra do serviço](../../apps/api/app/services/ingestion.py#L152). Não foi provocado reprocessamento nesta avaliação.

## Aspectos que funcionam bem e devem ser preservados

- A fazenda fica identificada sem um seletor de múltiplas propriedades; o fluxo principal voltou a ter foco nas tarefas do produtor.
- A aplicação informa que leituras de fotos e áudios aguardam aprovação. A fonte original pode ser consultada durante a conferência.
- A importação de produção apresenta prévia, diferencia conflitos e oferece manter leituras existentes. Substituições exigem motivo e preservam histórico.
- A baixa explica a preservação da produção e oferece desfazer. A união de fichas possui prévia e alertas de consequência; descartar um item recusado da fila exige confirmação.
- O lançamento de produção apresenta retorno por linha e atalhos de teclado, sem depender de salvar uma folha inteira de uma vez.
- Os gráficos têm alternativas em tabela. Os formulários observados possuem rótulos e há indicações de carregamento, falha e sucesso em vários fluxos.
- O foco entra no formulário de alteração do animal. No teste do menu “Mais ações”, Escape fechou o menu e devolveu o foco ao botão de origem. A navegação adapta-se às larguras verificadas.

## Sequência recomendada para a próxima revisão do protótipo

1. **Confiabilidade das tarefas e dos números:** resolver os achados 02–05 em conjunto com a configuração inicial. Uma fazenda nova precisa conseguir chegar a um cálculo compreensível sem intervenção técnica.
2. **Encontrar e concluir ações:** revisar leitura de foto, linguagem de equipe/histórico, cancelamento e estabilidade do menu Mais (01 e 08–10, 12–14).
3. **Primeiro uso e conectividade:** simplificar configuração e orientar estados vazios e offline (06, 07 e 11).

As mudanças de organização e texto devem ser apresentadas no protótipo antes de publicar. Correções funcionais precisam de validação com a aplicação real: uma simulação visual de dieta ou envio não demonstra funcionamento de API, leitura automática ou persistência offline.

## Roteiro de validação com produtores e funcionários

Usar participantes que conheçam o manejo, incluindo pessoas que nunca viram a interface. Como rodada inicial prática, observar de 3 a 5 pessoas; isso ajuda a descobrir problemas, sem pretender representar estatisticamente todos os produtores. Dar objetivos, sem revelar o nome do botão nem o caminho:

| Tarefa | O que observar |
| --- | --- |
| Recebeu uma foto de uma folha e quer registrar a produção | Encontra a leitura? Entende a diferença entre enviar, ler e aprovar? |
| Vai começar a usar com uma fazenda vazia | Descobre como cadastrar lotes e animais sem conhecer a fazenda original? |
| Precisa mudar uma vaca de lote de ordenha | Escolhe o tipo certo e consegue verificar o destino? |
| Abriu uma troca de brinco por engano | Consegue cancelar sem salvar e sem abandonar a ficha? |
| Precisa incluir uma pessoa que lançará produção | Distingue conta pessoal, equipe e nova fazenda? Entende a permissão? |
| Quer saber o resultado econômico exibido | Explica corretamente quais despesas entram e quais faltam? |
| Quer saber a produção do mês passado | Identifica o período consultado e distingue acumulado de total diário? |
| Perdeu o sinal durante um lançamento | Sabe se ficou no aparelho ou chegou ao servidor? Confere o envio ao reabrir? |

Registrar conclusão sem ajuda, primeiro caminho escolhido, erros, dúvidas e compreensão do resultado. Priorizar problemas repetidos ou com consequência operacional, mesmo que o participante consiga terminar depois de ajuda.

No campo, complementar com Android e iPhone reais, sol, manuseio com uma mão, interrupções e rede instável. Para ações frequentes, buscar áreas de toque de 44–48 px como objetivo de conforto. A WCAG 2.2 AA estabelece 24 × 24 px ou condições de espaçamento/exceções no critério 2.5.8; tamanho inferior a 44 px, isoladamente, não prova uma falha AA.

## Evidência local da avaliação

Os levantamentos e capturas estão em `.venv/ux-audit/`, diretório local ignorado pelo Git: `inventory.json` contém os 47 estados iniciais e a resposta de validação; `extra.json` contém mais nove estados e verificações de interação. Os scripts usados foram `.venv/audit_ux.mjs` e `.venv/audit_ux_extra.mjs`. Esses arquivos usam dados fictícios e não constituem uma suíte permanente de regressão.

Este documento é o entregável da avaliação. Não houve implementação, commit, push ou implantação decorrente dela.
