# Dívida técnica e lacunas conhecidas

Registradas explicitamente para não ficarem escondidas. Nenhuma delas
bloqueia o fluxo ponta a ponta comprovado na Task 8.

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
