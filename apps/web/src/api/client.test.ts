/**
 * O que chega do servidor nem sempre é nossa API.
 *
 * Um envio grande demais morre no proxy, que responde HTML. Lendo isso como
 * JSON, o app estourava um erro de sintaxe e a tela dizia "confira a
 * conexão" — para um problema que não é de conexão, e que a pessoa resolve
 * de outro jeito.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { uploadImport } from "./client";
import { ApiError } from "./types";

const TOKEN = "token-de-teste";

function respostaDoProxy(status: number, corpo: string): Response {
  return new Response(corpo, {
    status,
    headers: { "Content-Type": "text/html" },
  });
}

function envio() {
  return {
    farmId: "f-1",
    file: new File(["conteudo"], "folha.jpg", { type: "image/jpeg" }),
  };
}

afterEach(() => vi.restoreAllMocks());

describe("Resposta que não é da nossa API", () => {
  it("arquivo grande demais vira um erro que a tela sabe explicar", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      respostaDoProxy(413, "<html><head><title>413 Request Entity Too Large</title></head></html>"),
    );

    const erro = await uploadImport(envio(), TOKEN).catch((caught: unknown) => caught);

    expect(erro).toBeInstanceOf(ApiError);
    expect((erro as ApiError).status).toBe(413);
    expect((erro as ApiError).code).toBe("upload_too_large");
  });

  it("qualquer outra página de erro do proxy não vira erro de sintaxe", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(respostaDoProxy(502, "<html>502</html>"));

    const erro = await uploadImport(envio(), TOKEN).catch((caught: unknown) => caught);

    expect(erro).toBeInstanceOf(ApiError);
    expect((erro as ApiError).code).toBe("server_error");
  });
});
