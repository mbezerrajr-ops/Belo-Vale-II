import { describe, expect, it } from "vitest";

import { formatRoute, parseRoute } from "./router";

const ID = "3f2b8c1e-9a4d-4e21-8b7a-0c5d6e7f8a9b";

describe("endereço de cada tela", () => {
  it("lê a área", () => {
    expect(parseRoute("/producao")).toEqual({ area: "producao", animalId: null });
    expect(parseRoute("/minha-conta/")).toEqual({ area: "minha-conta", animalId: null });
  });

  it("lê a ficha aberta dentro de Animais", () => {
    expect(parseRoute(`/animais/${ID}`)).toEqual({ area: "animais", animalId: ID });
  });

  it("raiz e endereço desconhecido não escolhem área", () => {
    expect(parseRoute("/")).toEqual({ area: null, animalId: null });
    expect(parseRoute("/fichas")).toEqual({ area: null, animalId: null });
    expect(parseRoute("/nada/aqui")).toEqual({ area: null, animalId: null });
  });

  it("identificador que não é de ficha não abre ficha", () => {
    // O endereço vem de fora do app: nada estranho vira pedido à API.
    expect(parseRoute("/animais/../contas")).toEqual({ area: "animais", animalId: null });
    expect(parseRoute("/animais/497")).toEqual({ area: "animais", animalId: null });
  });

  it("ida e volta dão o mesmo endereço", () => {
    for (const path of ["/", "/painel", "/revisao", `/animais/${ID}`, "/animais"]) {
      expect(formatRoute(parseRoute(path))).toBe(path);
    }
  });
});
