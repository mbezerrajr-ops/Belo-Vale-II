# Relatório mensal implementado

O fechamento solicitado foi implementado na área Relatórios, com atalho no Painel, preservando o acesso de cada usuário à própria fazenda.

Inclui comparação por mês, produção registrada e estimada, médias por coleta e por animal, receita, alimentação, saldo e margem estimados. Identifica meses positivos, negativos, equilibrados e sem base suficiente; o melhor e o pior mês consideram períodos encerrados. Exporta os mesmos números e avisos para Excel.

O histórico de preço do leite e de dietas passa a ter vigência. O preço de insumos já possuía histórico e agora também pode ter a vigência informada na interface. Correções antigas preservam as vigências mais recentes. A migração registra os valores existentes apenas no dia da atualização; meses anteriores não recebem valores retroativos inventados. Para esses meses existe uma opção explícita de simulação com valores atuais.

O método e as limitações estão em [Relatório mensal](../relatorio-mensal.md). O saldo continua limitado à receita do leite menos alimentação; outras despesas não estão incluídas. Coletas isoladas são amostras, não medição diária de todo o mês.

## Validação

- 968 testes da API aprovados e 3 ignorados pela configuração, usando PostgreSQL e Redis descartáveis.
- 290 testes do frontend aprovados, incluindo simulação explícita, bloqueio de exportação de consultas antigas e descarte de respostas atrasadas.
- Suíte completa de navegador: 28 cenários aprovados na pilha Docker real, com provedores de leitura próprios de teste.
- Migração: subida, descida e nova subida em banco descartável, com preservação dos valores existentes e verificação da data dos snapshots.
- Exportação: correspondência de valores, células vazias para dados insuficientes, restrição por perfil e tratamento de nomes como texto no Excel.
- Relatório no celular em 320/390 px, temas claro/escuro, sem transbordamento da página ou problemas graves nas verificações automatizadas de acessibilidade.

O teste físico de campo permanece no planejamento existente. A atualização do servidor precisa aplicar a migração `0020_monthly_report_history`; o procedimento padrão de implantação já executa as migrações.
