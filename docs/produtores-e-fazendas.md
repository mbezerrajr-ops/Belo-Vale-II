# Produtores e fazendas

## Escopo confirmado pelo titular

A plataforma atende vários produtores, cada um com sua própria fazenda e seus
próprios dados. **Cada usuário acessa uma única fazenda.** Vários funcionários
podem trabalhar nessa mesma fazenda com seus papéis de operador, revisor ou
administrador, pela área Contas que já existia.

Ao entrar, a pessoa abre diretamente o Painel ou a Produção de sua fazenda.
Não há faixa superior, seletor, lista para alternar fazendas, criação de segunda
fazenda ou painel adicional de gestão de produtores. A importação de produção
já existente foi mantida; o cadastro CSV adicional introduzido na primeira
ampliação foi retirado. Os animais cadastrados continuam preservados.

O administrador pode ajustar nome, fuso e lotes em **Minha conta → Configuração
da minha fazenda**, em uma seção recolhida. As áreas habituais do aplicativo
continuam sendo usadas para animais, produção, revisão, insumos e equipe.

## Cadastro de um novo produtor

1. Na entrada, escolher **Sou produtor: criar conta**.
2. Informar e-mail, senha, nome do produtor e nome da fazenda.
3. Confirmar o e-mail recebido e entrar.
4. Usar a própria fazenda, inicialmente vazia, pelas mesmas telas da operação
   atual. Ajustar os lotes em Minha conta e cadastrar animais em Animais.

Um novo produtor não recebe cópias de rebanho, preços ou equipe de outro cliente.
Confirmação, recuperação e convites dependem do SMTP configurado na API:

```dotenv
PUBLIC_APP_URL=https://endereco-publico-do-aplicativo
SMTP_HOST=servidor-smtp
SMTP_PORT=587
SMTP_FROM=contas@dominio-do-produto
SMTP_USER=
SMTP_PASSWORD=
SMTP_STARTTLS=true
```

Usar o endereço HTTPS real em PUBLIC_APP_URL. Sem SMTP, o aplicativo informa
indisponibilidade nos fluxos que precisam enviar mensagens; não há confirmação
fictícia nem token exposto pela resposta HTTP. Nos testes, um Mailpit da pilha
isolada recebe as mensagens e os leitores de IA são falsos.

## Isolamento e limite de uma fazenda

- O acesso exige vínculo ativo explícito em farm_memberships. O papel global
  antigo não concede acesso aos outros produtores. Um vínculo em conta produtora
  também não concede automaticamente acesso a outras fazendas.
- O contexto pode ser inferido pelo único vínculo da pessoa. X-Farm-ID, quando
  enviado, precisa corresponder a ele; mudar esse valor não muda a autorização.
- Criação de segunda fazenda/conta produtora e aceitação ou reativação de vínculo
  em outra fazenda são recusadas. O banco também impõe um índice único parcial
  por usuário para vínculos ativos.
- Fotos, áudios, medições, propostas, arquivos, relatórios e filas respeitam a
  fazenda e o autor. O worker verifica o acesso novamente antes da leitura.
- A fila offline preserva sua origem e só confirma persistência quando termina
  a transação IndexedDB. A retomada local depende de preparação online e vale
  até sete dias; sair voluntariamente encerra a identidade local.

## Migrações e dados existentes

A ampliação original usa 0017_producers_and_farms e 0018_farm_integrity. O ensaio
com o código anterior e a baseline completa conferiu os 401 animais e as 152
medições, além de lotações, equipe, insumos, dietas, preços e auditoria.

A correção usa **0019_single_farm_per_user**. Ela não apaga fazendas, usuários,
animais, medições ou vínculos históricos. Se encontrar uma pessoa com vários
vínculos ativos criados durante a primeira versão, a migração recusa a atualização
para que a fazenda correta seja definida explicitamente. Ela não escolhe nem
exclui dados por conta própria. O atualizador mantém a versão anterior se a
migração for recusada.

A recuperação seletiva continua disponível pela ferramenta administrativa
`python -m app.core.recover_farm --farm-id UUID` (simulação padrão) e com
`--apply` para criar uma cópia com novos IDs/prefixos. Quando uma identidade já
acessa outra fazenda no destino, seu vínculo na cópia recuperada fica inativo.
Isso preserva o limite de uma fazenda sem mudar senhas ou a operação existente.
A manutenção precisa definir o responsável e validar a cópia antes de usá-la.
A ferramenta exige memória para as mídias; falha na transação pode deixar
arquivos órfãos somente no novo prefixo, que devem ser conferidos pela manutenção.

## Produção real

Confirmada por SSH em 05/11/2026: servidor Ubuntu chamado belo-vale, usuário
belovale, projeto em ~/Belo-Vale-II e site https://belo-vale.taile2ed91.ts.net/.
O notebook Windows é usado para acessar o servidor. A atualização é feita no
terminal Linux, seguindo o [runbook de produção](runbook-producao.md).

O titular confirmou que a primeira implantação está saudável. Esta correção
precisa ser baixada e aplicada no mesmo servidor após integrar a main. O script
faz novo backup, compila, migra e troca os serviços. Não recriar o arquivo
infra/.env.production da instalação existente.

## Verificação

Os testes cobrem produtores independentes, um único vínculo por identidade,
acesso direto por identificador, bloqueio de segunda fazenda, convite para outra
operação, revogação e recuperação sem conceder segundo acesso. O E2E verifica
cadastro, confirmação por SMTP de teste e entrada direta na própria fazenda,
sem seletor ou importação adicional, mantendo a separação entre dois produtores.

A suíte também verifica os fluxos existentes de produção, importação de coleta,
revisão, fotos/áudios, impressão, navegação e persistência offline. Teste de campo,
piloto externo, Android e Google Play continuam como próximas etapas.