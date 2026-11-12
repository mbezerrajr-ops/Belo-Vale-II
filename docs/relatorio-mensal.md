# Relatório mensal de desempenho

O relatório fica em **Relatórios → Relatório mensal** (`/relatorios`) e também pode ser aberto pelo atalho no Painel. Cada consulta pertence exclusivamente à fazenda autorizada para a pessoa conectada.

## O que apresenta

- Litros efetivamente registrados, quantidade de leituras, dias com coleta e animais distintos.
- Média por dia de coleta e média por vaca por leitura.
- Produção estimada para os dias do mês, receita estimada, alimentação estimada, saldo após alimentação e margem.
- Resultado positivo, negativo, equilibrado ou dados insuficientes, com identificação de estimativa.
- Comparação entre meses, variação da produção estimada e diferença do saldo em relação ao mês anterior do intervalo.
- Melhor e pior saldo entre os meses encerrados com base financeira suficiente. O mês em andamento não participa desse ranking.
- Gráficos, alternativas em tabela e planilha Excel com uma aba de metodologia e avisos por mês.

O saldo é **receita estimada do leite menos alimentação cadastrada**. Funcionários, energia, medicamentos, manutenção, financiamento e outras despesas não estão incluídos. Portanto, não representa lucro líquido da fazenda.

## Método

Para cada mês, somam-se apenas as leituras oficiais ativas. Uma leitura corrigida ou anulada não é contada novamente. Leituras históricas de animais que tiveram baixa continuam participando do período em que ocorreram.

```text
média por dia de coleta = litros registrados / número de datas com coleta
média por vaca por leitura = litros registrados / número de leituras individuais
produção estimada = média por dia de coleta × dias do período
receita estimada = soma, por dia, da média de produção × preço vigente do leite
alimentação estimada = soma, por dia e insumo/lote, de kg vigentes × preço vigente/kg
saldo estimado = receita estimada − alimentação estimada
margem estimada = saldo estimado / receita estimada × 100
```

Exemplo fictício: duas coletas com totais de 10 e 20 litros resultam em média de 15 L/dia de coleta. Em um mês de 31 dias, a projeção é 465 L, enquanto o volume registrado permanece 30 L. O relatório mostra os dois valores separadamente.

A estimativa pressupõe que as coletas representam o mês. Não adiciona animais ausentes das leituras. Quantidades diferentes de animais entre coletas geram aviso; cada mês informa quantas observações sustentam o cálculo. Mês sem coleta não recebe uma produção extrapolada de outro mês.

O mês atual considera somente os dias até a data da fazenda. Fevereiro e anos bissextos usam o calendário real. A margem fica sem valor quando a receita é zero; um custo zero cadastrado continua válido. Campos financeiros sem base suficiente permanecem vazios, nunca são convertidos em zero.

## Histórico e simulação

Em **Insumos**, os formulários de preço do leite, preço do insumo e dieta permitem informar **a partir de qual data** o valor vale. Uma gravação antiga preserva as vigências mais recentes. Gravações na mesma data corrigem aquela vigência; as alterações ficam na auditoria.

A migração `0020_monthly_report_history` acrescenta históricos de leite e dieta. Os valores existentes recebem somente a data da atualização, no fuso da fazenda; a migração não inventa valores para meses passados. O histórico de preço dos insumos já existente é utilizado pelo cálculo.

Quando falta histórico, a consulta informa os dias sem base e não classifica um saldo como conhecido. A opção **Estimar meses sem histórico usando preços e dietas atuais** permite uma simulação explícita. Ela substitui apenas os valores ausentes, preserva os históricos disponíveis e informa quantos dias utilizaram essa suposição. A opção começa desmarcada.

Para um fechamento antigo mais fiel, informe os preços e as dietas que efetivamente vigoravam no período. Para interromper o consumo de um insumo em um lote, registre quantidade zero com sua data de vigência. Quantidade de dieta representa o consumo do **lote inteiro por dia**.

## Acesso e exportação

Operadores, revisores e administradores podem consultar o relatório, como já ocorre no painel. A exportação exige revisor ou administrador e gera um evento de auditoria. Alterar preços e dietas continua exigindo revisor ou administrador.

A planilha exporta a mesma seleção de meses e a mesma opção de simulação exibidas na tela. Inclui volume registrado, estimado, médias, receita, alimentação, saldo, margem, situação, cobertura e avisos. A aba Metodologia identifica a fazenda, o período e as suposições. Células vazias significam dados insuficientes.

## API

- `GET /api/reports/monthly?inicio=2026-01&fim=2026-10&simular_atuais=false`
- `GET /api/reports/monthly/export?inicio=2026-01&fim=2026-10&simular_atuais=false`

Os meses usam `AAAA-MM`; a consulta aceita de 1 a 24 meses, sem meses futuros. A fazenda vem da autorização da sessão, sem parâmetro para consultar outra propriedade.

Os endpoints existentes de preço do leite e dieta acrescentam o campo opcional `effective_on`. Sem ele, a vigência começa no dia atual da fazenda. Datas futuras nesses dois campos são recusadas.

## Atualização

O procedimento padrão de atualização do servidor aplica a nova migração. Não é necessário importar novamente os animais ou a produção. O teste cobre a subida, descida e nova subida da migração em banco descartável, sem alterar as tabelas anteriores.
