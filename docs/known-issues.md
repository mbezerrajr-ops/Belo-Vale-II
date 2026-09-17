# Dívida técnica e lacunas conhecidas

Registradas explicitamente para não ficarem escondidas. As pendências do legado não
bloqueiam sua validação ou geração, mas devem ser resolvidas antes de declarar a migração
para PostgreSQL como reconciliada.

## Reconciliação da baseline legada

A baseline canônica validada possui 401 animais e 152 medições. O relatório operacional
completo está em
`belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais_ultimo_relatorio.txt`.
Permanecem pendentes de decisão humana:

- **141 animais legados** não aparecem no PDF mais recente. Todos foram preservados, sem
  alteração ou exclusão automática.
- **13 divergências de nome** entre PDF e base: 432 Carolina/KAROLINA; 434 FAISCA DO
  ABREU/FAÍSCA; 448 MEIAS BRANCAS/MEIAS BRANCA; 701 Pequena/PIQUENA; 733 Crauna/Pauna;
  779 GESSICA/GÉSSIKA; 967 MALHADA/Machada; 981 CONDESA/Condessa; 1008
  DENGOSA/CABELO DE FOGO; 1013 CODORNA/Boemia; B1-263 ESPERANÇA II ABREU/ESPERANÇA;
  B2-512 Asa Negra/AZA NEGRA; B2-523 BARONESA/BARONEZA. O nome da base foi mantido.
- **30 animais com brinco, situação “Em lactação” e DEL vazio**. São avisos de qualidade,
  não autorização para mudar situação, lote ou DEL automaticamente.
- **27 pares candidatos por nome normalizado** entre registros legados e registros com
  brinco do relatório. Eles não são equivalências confirmadas e não foram fundidos:

| Legado | Registro do relatório |
| --- | --- |
| 125 MARINGÁ | B2-687 Maringa |
| 205 REVISTA | 827 Revista |
| 604 CARINHOSA | 832 Carinhosa |
| 157 CIGANA | 821 Cigana |
| 474 SURUBIM | 846 Surubim |
| 440 ARIZONA | 1001 Arizona |
| 19 BOLINHA | 956 Bolinha |
| 626 BOLINHA | 956 Bolinha |
| 143 BURGUESA | B2-662 BURGUESA |
| 155 CARINA | B2-658 CARINA |
| 147 CARRAPETA | B2-664 CARRAPETA |
| 46 ESMERALDA | 812 Esmeralda |
| 78 ESPERANÇA | B1-263 ESPERANÇA |
| 009 VERMELHO FAÍSCA | 434 FAÍSCA |
| 220 JARDINEIRA | 1015 Jardineira |
| 702 MAÇA | B2-663 MAÇA |
| 686 MEDALHA | 879 Medalha |
| 635 NEBLINA | 767 NEBLINA |
| 96 PALOMA | B2-584 PALOMA |
| 10 TIETA | 964 Tieta |
| 498 Meias Branca | 448 MEIAS BRANCA |
| 682 Rainha | B2-680 RAINHA |
| 141 Fumaca | 441 FUMAÇA |
| 519 Branquinha | B2-549 BRANQUINHA |
| 133 Bruna | 433 BRUNA |
| 862 Saia Branca | 861 SAIA BRANCA |
| 508 Princesa | B2-548 PRINCESA |

O caso BOLINHA é explicitamente ambíguo: dois registros legados apontam pelo nome para o
mesmo registro 956. A decisão exige evidência externa. PONTA CURTA (497) e GIGANTE (633)
não fazem mais parte das pendências de produção: ambas têm leitura em `2026-07-22` no
estado canônico.

## npm audit — esbuild (dependência de desenvolvimento)

- **Dependência:** `esbuild` (via `vite`/`vitest`/`vite-node`/`@vitest/mocker`,
  todas dependências de desenvolvimento do frontend).
- **Advisory:** [GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99)
  — o servidor de desenvolvimento do esbuild aceita requisições de qualquer
  origem e devolve a resposta.
- **Escopo:** exclusivamente o servidor de desenvolvimento local (`vite dev`
  / `npm run dev`). Não afeta o bundle de produção gerado por `npm run
  build` nem a imagem Docker do serviço `web` (que só serve arquivos
  estáticos via nginx, sem o servidor de dev do Vite).
- **Impacto:** um site malicioso aberto no mesmo navegador enquanto alguém
  roda `npm run dev` localmente poderia, em teoria, ler respostas do
  servidor de dev. Não há exposição em produção nem em CI (que roda `npm
  run build`, não `npm run dev`).
- **Mitigação atual:** nenhuma ação além de não expor o servidor de dev em
  rede não confiável (comportamento padrão — ele só escuta em localhost).
- **Upgrade necessário para resolver:** `vite@8` (major, breaking change),
  que arrasta `vitest`/`@vitest/mocker`/`vite-node` juntos.
- **Prioridade:** baixa. Deliberadamente não aplicado nesta task para não
  trocar a stack de build/teste no meio de uma integração — ver instrução
  explícita da Task 8 de não fazer upgrade major só para zerar o audit.

## Duas seções "Fazenda" na tela principal

O formulário de upload (`UploadForm`) e o filtro do dashboard
(`OfficialMeasurements`) têm cada um seu próprio campo "Fazenda"
independente, em vez de compartilhar um único valor. Funciona, mas exige
digitar o mesmo ID duas vezes. Não corrigido nesta task por não ser um
redesenho justificado pelo escopo (Task 8 pede explicitamente para não
redesenhar a UI) — seria uma melhoria de UX pontual para uma task futura.

## `HttpVisionProvider` sem integração externa real comprovada

Ver `docs/vision-provider-status.md` para a classificação completa.
Estruturalmente revisado e testado (construção de requisição, ausência de
credenciais no frontend, timeout, parsing do formato esperado); nunca
executado contra um provedor de visão/OCR real, por não haver credencial
disponível ou autorizada neste ambiente.

## Sem CI configurado

Todos os comandos deste projeto (`pytest`, `vitest`, `tsc`, `npm run build`,
`docker compose`, `playwright`) foram rodados manualmente e estão
documentados e verificados em `docs/runbook-local.md`, mas não existe um
pipeline de CI (GitHub Actions ou equivalente) automatizando essas
verificações a cada push/PR. Fora do escopo desta task.

## Sem endpoint HTTP para cadastro de fazenda/animal

O "cadastro mestre" (fazendas, animais) só é populável via inserção direta
no banco (`INSERT` via `psql`), documentado no runbook. Não há tela nem
endpoint de API para isso na v1 — consistente com o spec original, que não
menciona esse CRUD como parte do escopo do pipeline de ingestão.
