# Teste de campo no iPhone

Um dia de ordenha acompanhada, com o iPhone de quem vai usar o app no curral.
O objetivo é ver o app nas condições de verdade: sinal que cai, sol, mão
ocupada, pressa. Executar depois da ampliação para produtores e fazendas.
A validação automatizada desta entrega usou Chromium; Safari e os seletores
nativos precisam desta conferência no aparelho real.

**Quem:** você e o funcionário que vai lançar a produção. Ele usa o iPhone;
você observa e anota. Não ajude antes de ele travar: o ponto onde ele trava é
justamente o que precisamos achar.

**Leve:** este roteiro impresso (ou no computador), uma caneta e a folha de
produção do dia.

## Antes do dia

- [ ] O endereço HTTPS da versão a homologar abre no celular; anote endereço,
      versão, modelo do aparelho e versão do iOS.
- [ ] Entre na fazenda correta e prepare o funcionário em **Fazendas e equipe**
      por convite, ou em **Contas** com senha provisória (função **Operador**).
- [ ] No iPhone dele: iOS atualizado (Ajustes → Geral → Atualização de
      Software).
- [ ] Anote a configuração dele de **Ajustes → Tela e Brilho → Bloqueio
      Automático** (normalmente 30 segundos). Não mude antes do teste: queremos
      ver o que acontece com a configuração que ele usa.

## Roteiro

Para cada item, marque ✓ (funcionou como descrito) ou ✗ (não funcionou), e
anote o que aconteceu. Tire um print quando algo der errado: botão lateral +
volume para cima.

### A. Entrar e instalar

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 1 | Abrir o endereço no **Safari** | Tela verde com a vaca e "Entrar". Nenhum aviso de "site não seguro". | |
| 2 | Entrar com o e-mail e a senha provisória | Pede uma senha nova. Ele escolhe uma só dele. | |
| 3 | Tocar no círculo com as iniciais (topo) → **Usar como aplicativo** → seguir os passos | Ícone da vaca na tela inicial do iPhone. | |
| 4 | Abrir pelo ícone | Abre em tela cheia, sem a barra do Safari. Pode pedir para entrar de novo: o app instalado tem sessão separada do Safari, e isso é normal. | |

### B. Lançar a produção, com sinal

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 5 | **Produção** → escolher o lote → digitar os litros de 5 vacas, usando a tecla de avançar do teclado | Aparece o teclado de números; cada vaca ganha ✓ verde; o total sobe. | |
| 6 | Observar | A tela deu zoom sozinha ao tocar num campo? Dá para ler no sol? Ele achou a vaca certa sem hesitar? | |

### C. Sem sinal — o mais importante

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 7 | Ligar o **Modo Avião** e lançar mais 3 vacas | Faixa "Sem sinal" no topo; cada linha fica amarela com "guardado neste celular"; aparece "3 guardados" perto das iniciais. | |
| 8 | Ainda no Modo Avião: ir para outro app (WhatsApp, por exemplo) e voltar | O app continua na mesma tela, com os 3 guardados. | |
| 9 | Ainda no Modo Avião: **fechar o app de vez** (deslizar de baixo para cima e jogar o app para fora) e abrir pelo ícone | Retoma a identidade e a fazenda preparadas, com os valores guardados e aviso de falta de sinal. A retomada local vale até sete dias após acesso online; saída voluntária a encerra. Anote o resultado real. | |
| 10 | Desligar o Modo Avião (entrar de novo, se o app pedir) | Em até 30 segundos o "3 guardados" some e aparece "enviado". | |
| 11 | No computador: **Painel** ou **Medições** | Os 3 valores estão lá, com o e-mail do funcionário. | |

### D. Foto da folha

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 12 | **Revisão** → **Enviar foto** → **Tirar foto** → fotografar → **Enviar**. Depois repetir por **Escolher da biblioteca** com JPEG e HEIC. | Cada botão abre o seletor esperado; a foto escolhida aparece na prévia quando o navegador a suporta e chega corretamente à Revisão. | |
| 13 | Repetir com o **Modo Avião** ligado | "a foto ficou guardada neste celular". Ao desligar o Modo Avião, ela sobe sozinha. | |

### E. Gravação da ordenha

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 14 | **Revisão** → **Enviar áudio** → **Gravar** | O iPhone pede o microfone → **Permitir**. | |
| 15 | Falar, por exemplo: "a quatrocentos e noventa e sete deu dezoito litros de manhã e quinze à tarde" → **Parar** → ouvir → **Enviar** | Toca o que foi gravado; depois de enviado, a leitura aparece na Revisão. | |
| 16 | Gravar **2 minutos sem tocar na tela** | **Importante:** a tela apagou sozinha? A gravação continuou ou parou? Anote o tempo que aparecia quando parou. | |
| 17 | Gravar com o **Modo Avião** ligado e enviar | "a gravação ficou guardada neste celular"; sobe sozinha quando o sinal volta. | |

### F. O resto

| # | O que fazer | O que deve acontecer | ✓/✗ e observação |
| --- | --- | --- | --- |
| 18 | **Animais** → buscar uma vaca → abrir a ficha → deslizar da borda esquerda para a direita | Volta para a busca, com o que tinha sido digitado. | |
| 19 | Observar o dia todo | Onde ele parou sem saber o que fazer? Que palavra ele não entendeu? O que ele esperava que acontecesse e não aconteceu? | |
| 20 | Com dois produtores de teste, guardar lançamento e foto sem sinal com o primeiro; sair e entrar com o segundo quando houver conexão | Cada usuário abre apenas sua fazenda. O segundo não acessa nem envia a fila do primeiro; os dados pendentes seguem vinculados ao autor e à origem. | |
| 21 | Repetir com outro usuário e com acesso revogado | Outra identidade não acessa a fila do autor; envio recusado fica guardado para conferência e oferece nova tentativa após corrigir o acesso. | |

## Depois

- No computador, em **Revisão**, aprove ou rejeite o que veio das fotos e das
  gravações, conferindo com a folha do dia.
- Me mande: os números dos itens com ✗, as observações e os prints. Com isso,
  corrijo o que o aparelho de verdade mostrou.

## O que já se sabe (não é defeito)

- **O primeiro acesso precisa de sinal.** A retomada local permite usar folhas
  previamente carregadas por até sete dias. A leitura por IA e a sincronização
  precisam de conexão e de autorização válida no servidor. O app envia ao ser
  aberto/retomado; não promete execução com o processo encerrado.
- O app instalado na tela inicial e o Safari têm sessões separadas: entrar em
  um não entra no outro.
