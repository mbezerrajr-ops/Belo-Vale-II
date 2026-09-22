import { SendUpload, type SendUploadProps, type Variant } from "./SendUpload";

/** Enviar a foto da folha pela própria Revisão. */

const FOTO: Variant = {
  arquivo: "foto",
  id: "foto-folha",
  abrir: "Enviar foto",
  titulo: "Enviar foto da folha",
  rotulo: "Foto da folha",
  accept: "image/*",
  capture: "environment",
  comLote: true,
  gravador: false,
  trabalhando: "Lendo a folha. As propostas aparecem aqui quando terminar.",
  repetido: "Esta foto já foi enviada antes.",
  aindaTrabalhando: "Esta foto ainda está sendo lida. Espere alguns segundos e tente de novo.",
  deNovo: "Ler de novo",
  daqui: "da folha",
  vazio:
    "A folha foi lida, mas nenhuma linha foi entendida. Confira se a foto pega a folha inteira, com luz, e envie outra.",
  foraDoAr:
    "O leitor de folhas está fora do ar agora. A foto ficou guardada: tente ler de novo daqui a pouco.",
  ilegivel: "Não deu para ler esta folha. Tire outra foto, mais de perto e com boa luz.",
  falhou: "Não foi possível ler a foto. Ela ficou guardada: tente ler de novo.",
};

export function SendPhoto(props: SendUploadProps): JSX.Element {
  return <SendUpload variant={FOTO} {...props} />;
}
