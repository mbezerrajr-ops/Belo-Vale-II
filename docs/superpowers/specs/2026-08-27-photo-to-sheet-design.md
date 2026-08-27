# Visão computacional para fichas de controle leiteiro

## Objetivo

Transformar fotos de fichas manuscritas de controle leiteiro em propostas estruturadas de medições. Toda proposta passa por conferência humana antes de gravar dados oficiais na primeira versão.

## Escopo da primeira versão

- Upload ou captura de uma foto de ficha.
- Identificação informada de fazenda, lote e período, com pré-visualização.
- Armazenamento da imagem original e prevenção de uploads duplicados por hash.
- Processamento assíncrono de pré-processamento, visão/OCR, normalização e validação.
- Revisão humana por linha, com imagem, recorte de origem, valores extraídos, sugestões, alertas e confiança.
- Criação ou substituição auditável de medições oficiais aprovadas.
- Alimentação do dashboard e histórico apenas por medições oficiais ativas.

Não faz parte da primeira versão: publicação automática de medições, treinamento de um modelo próprio ou remoção do histórico de versões.

## Arquitetura

```text
Usuário
  -> frontend de conferência
  -> API de ingestão
  -> fila de processamento
  -> pré-processamento de imagem
  -> serviço de visão/OCR
  -> extração bruta
  -> normalizador
  -> validador de domínio
  -> motor de decisão
  -> revisão humana
  -> serviço de aprovação
  -> banco operacional
  -> dashboard, histórico e relatórios
```

O ambiente de desenvolvimento e homologação será composto por containers Docker:

| Serviço | Responsabilidade |
| --- | --- |
| `web` | Frontend React e TypeScript para upload e revisão. |
| `api` | API FastAPI; autenticação, regras de negócio e gravação oficial. |
| `worker` | Processamento assíncrono de imagens e extração. |
| `db` | PostgreSQL: dados operacionais, estados, validações e auditoria. |
| `redis` | Transporte de tarefas assíncronas; não é fonte de verdade. |
| `minio` | Armazenamento de imagens originais, versões pré-processadas e recortes. |
| `vision` | Adaptador para serviço de visão/OCR pré-treinado, substituível. |

A API será a única camada autorizada a gravar medições oficiais. A aplicação HTML/Artifact existente será preservada como referência visual e de domínio durante a migração, mas não será fonte de verdade.

## Pipeline de ingestão

1. O frontend recebe a foto e os metadados de contexto.
2. A API valida tipo, tamanho e integridade do arquivo, calcula o hash e identifica duplicidade.
3. A API salva a imagem e cria uma importação com uma tarefa assíncrona.
4. O worker corrige rotação/perspectiva, ajusta contraste, recorta e normaliza a imagem.
5. O adaptador de visão/OCR retorna cabeçalho, lote, data, linhas, número da vaca, manhã, tarde, total, observações, regiões da imagem e confiança por campo.
6. O normalizador converte datas, decimais, números, unidades e texto para o formato do domínio.
7. O validador concilia a leitura com o cadastro mestre e cria alertas.
8. A revisão humana aprova, corrige ou rejeita cada linha.
9. O serviço de aprovação cria medições oficiais e eventos de auditoria de maneira idempotente.

## Dados e integridade

Entidades principais:

```text
Fazenda -> Animal -> Medição oficial
Importação -> Imagem -> Tarefa -> Extração bruta -> Extração normalizada
          -> Validações -> Revisão humana -> Auditoria -> Medição oficial
```

Cada linha extraída deve registrar o valor bruto, valor normalizado, confiança, caixa/recorte da imagem e correspondência candidata com o animal.

Invariantes:

- O hash da imagem impede reprocessamento acidental da mesma foto por fazenda.
- A mesma aprovação não pode gerar duas medições oficiais.
- A duplicidade de animal e data gera alerta, nunca sobrescrita silenciosa.
- Dados OCR brutos nunca são apagados após correções humanas.
- Correções e aprovações registram usuário, data, motivo e versão.
- Imagens e seus recortes continuam vinculados ao dado aprovado.

## Substituição de medição

Quando já houver uma medição oficial ativa para o mesmo animal e data, a interface deve avisar explicitamente que a aprovação substituirá o dado exibido em dashboard e relatórios.

- A nova medição torna-se a versão ativa.
- A anterior é preservada como `substituída`.
- A substituição requer motivo obrigatório.
- O dashboard consulta apenas a versão ativa.
- Controle de concorrência impede duas aprovações concorrentes para a mesma medição.

## Confiança, validação e revisão

Na v1, todas as linhas são revisadas por humanos. A confiança serve para priorizar a fila e destacar campos, não para autorizar publicação automática.

Alertas são criados para:

- animal não identificado ou ambíguo;
- divergência de lote ou data;
- diferença acima da tolerância entre manhã + tarde e total;
- medição repetida;
- valor improvável frente ao histórico do animal;
- número, valor obrigatório ou cabeçalho ilegível/ausente;
- observações laterais relevantes.

A confiança final precisa ser explicável por: leitura OCR, correspondência com o cadastro, cálculo aritmético, coerência de lote/data e histórico. O sistema não deve decidir automaticamente apenas com um score agregado.

## Segurança

- Autenticação real no backend; nenhum perfil ou segredo no navegador.
- Perfis iniciais: operador/revisor e administrador.
- Senhas protegidas no servidor; sessões seguras e autorização em cada mutação.
- Nenhuma chave de provedor de visão/OCR no frontend.
- Acesso às imagens restrito por fazenda e papel.
- Validação de upload, limites de tamanho e tipos permitidos.
- Auditoria imutável de importação, revisão, aprovação e substituição.

## Critérios de aceite

- Uma foto válida cria importação rastreável sem modificar medição oficial.
- Upload duplicado é identificado antes de uma nova importação, com confirmação explícita para reprocessar.
- Cada linha proposta apresenta imagem/recorte, OCR, valor normalizado, confiança e alertas.
- Aprovação cria uma medição oficial auditável.
- Correção humana preserva o conteúdo OCR original.
- Substituição mostra aviso, exige motivo e preserva a versão anterior.
- Dashboard, histórico e relatórios usam apenas medições oficiais ativas.
- Falhas de OCR/processamento preservam imagem e estado da importação, sem criar dados parciais.

## Estratégia de IA

O conjunto atual de fotos e planilhas revisadas é adequado para validar o pipeline, mas insuficiente para treinar um modelo próprio de escrita manual com generalização confiável. A primeira versão usa visão/OCR pré-treinada por meio de adaptador substituível. Cada correção humana será armazenada como dado rotulado para avaliação futura de fine-tuning, após acumular volume e variedade representativos.
