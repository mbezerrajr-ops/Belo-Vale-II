import { SendUpload, type SendUploadProps, type Variant } from "./SendUpload";

/**
 * Enviar a gravação da ordenha pela própria Revisão.
 *
 * No Android o campo abre o gravador do sistema. No iPhone, o Safari não
 * oferece gravação num campo de arquivo de áudio: a pessoa grava no app
 * Gravador e escolhe o arquivo aqui — a dica na tela diz isso. Gravar dentro
 * do próprio app ficou para uma fase seguinte, por decisão do titular.
 */

const GRAVACAO: Variant = {
  arquivo: "gravação",
  id: "gravacao-ordenha",
  abrir: "Enviar áudio",
  titulo: "Enviar gravação da ordenha",
  rotulo: "Gravação da ordenha",
  accept: "audio/*",
  capture: "user",
  comLote: false,
  trabalhando: "Ouvindo a gravação. As propostas aparecem aqui quando terminar.",
  repetido: "Esta gravação já foi enviada antes.",
  aindaTrabalhando: "Esta gravação ainda está sendo ouvida. Espere alguns segundos e tente de novo.",
  deNovo: "Ouvir de novo",
  dica: "No iPhone, grave no app Gravador e escolha o arquivo aqui.",
};

export function SendAudio(props: SendUploadProps): JSX.Element {
  return <SendUpload variant={GRAVACAO} {...props} />;
}
