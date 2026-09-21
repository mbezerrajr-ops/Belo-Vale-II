import { ApiError } from "../../api/types";

/**
 * O que dizer quando o envio falha.
 *
 * "Confira a conexão" para um arquivo grande demais manda a pessoa olhar o
 * lugar errado — ela tentaria de novo no mesmo lugar, com o mesmo arquivo, e
 * falharia de novo. Cada motivo tem o seu texto, e cada texto diz o que
 * fazer.
 */
export function uploadErrorMessage(error: unknown, arquivo: "foto" | "gravação"): string {
  if (error instanceof ApiError) {
    if (error.code === "upload_too_large" || error.status === 413) {
      return arquivo === "foto"
        ? "A foto ficou pesada demais para enviar. Tire outra mais de perto da folha."
        : "A gravação ficou longa demais para enviar. Grave em pedaços menores.";
    }
    if (error.code === "invalid_image") {
      return arquivo === "foto"
        ? "Este arquivo não é uma foto. Envie a foto da folha."
        : "Este arquivo não é uma gravação de voz. Envie o áudio da ordenha.";
    }
  }
  return arquivo === "foto"
    ? "Não foi possível enviar a foto. Confira a conexão e tente de novo."
    : "Não foi possível enviar a gravação. Confira a conexão e tente de novo.";
}
