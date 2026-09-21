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
  trabalhando: "Lendo a folha. As propostas aparecem aqui quando terminar.",
  repetido: "Esta foto já foi enviada antes.",
  aindaTrabalhando: "Esta foto ainda está sendo lida. Espere alguns segundos e tente de novo.",
  deNovo: "Ler de novo",
};

export function SendPhoto(props: SendUploadProps): JSX.Element {
  return <SendUpload variant={FOTO} {...props} />;
}
