import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FarmWorkspace } from "./FarmWorkspace";
import { ApiError } from "../../api/types";
import * as client from "../../api/client";

vi.mock("../../api/client");
const api = vi.mocked(client);
const user = { id: "unique-user", email: "ana@example.org", role: "admin" as const, must_change_password: false };
const farm = { id: "farm-a", name: "Fazenda Ana", code: null, role: "admin" as const };
const key = `belo-vale.workspaces:${user.id}`;
function open() {
  render(<FarmWorkspace user={user} token="token" onLogout={vi.fn()}>{(_, __, current) => <main id="conteudo"><h1>{current.name}</h1></main>}</FarmWorkspace>);
}
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); });
afterEach(cleanup);

it("abre a própria fazenda sem faixa, seletor ou gerenciamento de outras fazendas", async () => {
  api.listFarms.mockResolvedValue([farm]); open();
  expect(await screen.findByRole("heading", { name: farm.name })).toBeVisible();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByText("Fazendas e equipe")).toBeNull();
  expect(api.setActiveFarmId).toHaveBeenLastCalledWith(farm.id);
});
it("não escolhe uma fazenda se o servidor devolver mais de um vínculo", async () => {
  localStorage.setItem(key, JSON.stringify([farm]));
  api.listFarms.mockResolvedValue([farm, { ...farm, id: "farm-b" }]); open();
  expect(await screen.findByRole("alert")).toHaveTextContent("única fazenda");
  expect(screen.queryByRole("heading")).toBeNull();
  expect(api.setActiveFarmId).toHaveBeenLastCalledWith(null);
});
it("retoma a única fazenda sem rede, mas não usa cache para acesso recusado", async () => {
  localStorage.setItem(key, JSON.stringify([farm]));
  api.listFarms.mockRejectedValue(new TypeError("Failed to fetch")); open();
  expect(await screen.findByRole("heading", { name: farm.name })).toBeVisible();
  cleanup(); api.listFarms.mockRejectedValue(new ApiError(401, { code: "unauthorized", detail: "Sessão encerrada" })); open();
  expect(await screen.findByRole("alert")).toHaveTextContent("Sessão encerrada");
  expect(screen.queryByRole("heading")).toBeNull();
});
