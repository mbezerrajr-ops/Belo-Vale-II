import { SendUpload, type SendUploadProps, type Variant } from "./SendUpload";

/**
 * Enviar a gravação da ordenha pela própria Revisão.
 *
 * Com conexão segura, o funcionário grava ali mesmo: aperta, fala, para,
 * ouve o que gravou e envia. Sem ela (ou em navegador sem gravador), fica o
 * campo de arquivo: no Android ele abre o gravador do sistema; no iPhone o
 * Safari não oferece gravação num campo de arquivo, e a dica manda gravar no
 * app Gravador e escolher o arquivo.
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
  gravador: true,
  trabalhando: "Ouvindo a gravação. As propostas aparecem aqui quando terminar.",
  repetido: "Esta gravação já foi enviada antes.",
  aindaTrabalhando: "Esta gravação ainda está sendo ouvida. Espere alguns segundos e tente de novo.",
  deNovo: "Ouvir de novo",
  daqui: "da gravação",
  vazio:
    "A gravação foi ouvida, mas nenhuma vaca foi entendida. Diga o brinco e os litros de cada vaca e grave de novo.",
  foraDoAr:
    "O transcritor está fora do ar agora. A gravação ficou guardada: tente ouvir de novo daqui a pouco.",
  ilegivel:
    "Não deu para entender fala nesta gravação. Grave de novo, com o celular perto da boca.",
  falhou: "Não foi possível ouvir a gravação. Ela ficou guardada: tente ouvir de novo.",
  dica: "No iPhone, grave no app Gravador e escolha o arquivo aqui.",
};

export function SendAudio(props: SendUploadProps): JSX.Element {
  return <SendUpload variant={GRAVACAO} {...props} />;
}
