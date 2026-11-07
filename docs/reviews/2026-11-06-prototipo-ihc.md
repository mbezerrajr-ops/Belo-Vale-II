# Protótipo da revisão de IHC

Após autorização do produtor, as recomendações da [avaliação](2026-11-06-avaliacao-ihc-usabilidade.md) foram aplicadas à prévia navegável, preservando um usuário vinculado a uma única fazenda.

**Endereço:** https://belo-vale-prototipo-caiol-20261105.muddypuppy513.chatgpt.site

## Alterações para revisar

| Área | Comportamento proposto |
| --- | --- |
| Produção e Revisão | Importar planilha/PDF e ler foto da folha com finalidades explícitas; atalho entre os caminhos e escolha de câmera/biblioteca sem duplicação. |
| Animais | Seleção de lotes/grupos cadastrados, prévia do destino, cancelamento explícito e linguagem consistente na troca de brinco. |
| Insumos | Definição de dieta por insumo e lote, quantidade para o lote inteiro, prévia de custo e confirmação de gravação. |
| Painel | Resultado após alimentação com alcance explicado; ausência de dieta diferenciada de custo zero cadastrado. |
| Minha conta | Lotes em campos separados, região/fuso em lista, validação de nomes e proteção de destinos em uso. |
| Navegação | Equipe, Histórico e rótulo Mais estável no celular. |
| Histórico | Período explícito, filtros de datas e acesso aos registros seguintes. |
| Primeiro uso | Orientação curta para configurar lotes, cadastrar animais e registrar produção. |
| Offline e leitura | Distinção entre guardado no aparelho, enviado, lido e aguardando conferência; orientação para abrir o aplicativo ao recuperar conexão. |
| Permissões e mensagens | Reprocessamento compatível com o perfil e mensagens de validação preservadas. |

## O que foi validado

Build TypeScript/Vite e fluxos no navegador com dados fictícios: cadastro de produtor e fazenda independente, primeiro animal, mudança de lote, cancelamento e retorno do foco, dieta com persistência após recarregar, filtros/paginação do histórico, foto aguardando conferência, duplicidade por perfil e fila offline com envio após reconexão simulada.

Verificações automatizadas de acessibilidade e transbordamento foram executadas em desktop e em 320/390 px, nos temas claro e escuro. Um problema de rótulo ARIA encontrado no estado guardado foi corrigido e os estados afetados foram verificados novamente. Isso não constitui certificação WCAG ou teste físico de campo.

## Limites e próxima etapa

Esta versão atualiza somente o protótipo. Os dados, login, e-mail e leitura automática são simulados; não há conexão com o sistema real. O código da aplicação em produção permanece no commit `3af3a0f` nesta máquina, sem push ou implantação dessas alterações no GitHub do produto.

O protótipo possui repositório próprio do Sites. O checkout local está em `.venv/sites/belo-vale-prototipo-20261105`, com registro técnico em `REVISAO-IHC.md`. Evidências de navegação e acessibilidade estão em `.venv/ux-prototype/`.

Publicação confirmada pelo Sites em 06/11/2026, a partir do commit `9acc4bdf70fc76ac1f4cfa1992613ab1384acc88`, com implantação `appgdep_6aede4267d0c8191abbd2a8121f70baa` concluída com sucesso. O público de acesso do protótipo foi preservado.

Depois da revisão visual e das tarefas pelo produtor, a transferência para o aplicativo real precisa incluir os contratos de cobertura da dieta, a integração das validações e os testes com a API. Aprovar o protótipo não equivale a validar OCR, entrega de e-mail ou sincronização em aparelhos físicos.
