# Integração da revisão de usabilidade aprovada

O produtor aprovou a prévia de 06/11 e pediu o envio ao Git em 07/11. Esta integração transfere a interface aprovada ao aplicativo, com sua API e persistência reais. O simulador, as contas fictícias e as ferramentas do Sites não fazem parte do produto.

## Comportamento

- Produção distingue importação de planilha/PDF da leitura de foto, com um atalho para o envio existente em Revisão.
- A ficha do animal seleciona destinos cadastrados, informa o efeito sobre lote de ordenha ou grupo de manejo, permite cancelar e mantém os termos da troca de brinco consistentes.
- Insumos permite definir a quantidade diária para o lote inteiro e informa o custo antes de salvar a dieta.
- O painel descreve o resultado após alimentação. A API informa lotes sem dieta e deixa o resultado incompleto como nulo. Uma dieta explicitamente cadastrada com quantidade zero continua sendo um custo conhecido.
- A configuração de lotes utiliza campos de nome e tipo; região/fuso é escolhida em lista. Erros de validação preservam a mensagem do servidor.
- Equipe, Histórico e o botão Mais mantêm nomes ligados às tarefas. O histórico permite filtrar datas e consultar além dos 30 registros iniciais.
- O primeiro uso indica como preparar lotes, animais e produção. Mensagens offline distinguem armazenamento local, envio e conferência.

## Integração com a API

`GET /api/dashboard` acrescenta `missing_diet_lots`. O resultado de um lote sem dieta e o resultado agregado incompleto são nulos. Os valores parciais de custo continuam disponíveis no contrato, acompanhados dos nomes dos lotes ausentes.

As operações manuais de cadastro/mudança de lote e de edição de dieta validam o destino na configuração da fazenda. Nomes são resolvidos para sua grafia cadastrada; destinos desconhecidos, tipos incompatíveis e grupos de manejo usados como dieta retornam 422. Os serviços internos de leitura/importação e manutenção mantêm seus fluxos existentes.

Não há nova migration nem alteração da regra de um usuário por fazenda. Não existe seletor de outras propriedades.

## Validação e publicação

Os testes cobrem autenticação e PostgreSQL reais, ausência de efeito após destino inválido, custo ausente versus zero, atualização da dieta e cálculo resultante. A navegação E2E utiliza a pilha Docker completa; a leitura de mídia usa os provedores falsos próprios dos testes.

Validação local: 959 testes do backend aprovados e 3 ignorados pela configuração; 285 testes do frontend; build TypeScript/Vite; varredura de credenciais sem achados. A suíte E2E também verifica temas claro/escuro, teclado, alvos de toque e produção/foto offline com fechamento e reabertura da página.

Fazer push no GitHub não executa a implantação no notebook servidor. Após integrar em `main`, a atualização continua sendo feita no Ubuntu, dentro da pasta do repositório:

```bash
cd ~/Belo-Vale-II
git pull --ff-only
tools/servidor/producao.sh atualizar
tools/servidor/producao.sh estado
```

O script de atualização inclui o procedimento de backup do projeto. O teste físico no campo continua pendente, conforme o planejamento existente.
