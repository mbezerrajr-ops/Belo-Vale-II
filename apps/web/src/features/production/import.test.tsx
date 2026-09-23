/**
 * Importação da coleta por arquivo.
 *
 * O caminho é sempre prévia → confirmação. A prévia mostra o que cada linha
 * vai virar antes de qualquer gravação; substituir leituras já lançadas é de
 * revisor, com motivo; a vaca fora do arquivo mantém a leitura dela.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportPanel } from "./ImportPanel";
import { ApiError, type ImportPreview, type ImportRecord } from "../../api/types";

const TOKEN = "token-de-teste";
const DAY = "2026-08-25";

function preview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    file_format: "csv",
    filename: "coleta.csv",
    sha256: "abc",
    measured_on: DAY,
    counts: {
      new: 1,
      same: 1,
      complete: 0,
      different: 1,
      not_found: 1,
      no_brinco: 0,
      invalid: 0,
      exited: 0,
      duplicate: 0,
    },
    rows: [
      row({ brinco_lido: "389", status: "new", producao: 21.5, animal_nome: "ÁGATA" }),
      row({ brinco_lido: "027", status: "same", producao: 35, existing_producao: 35 }),
      row({
        brinco_lido: "B2-647",
        status: "different",
        producao: 30,
        existing_producao: 34,
        animal_nome: "NEGUINHA",
      }),
      row({
        brinco_lido: "999",
        status: "not_found",
        producao: 20,
        animal_id: null,
        animal_nome: null,
      }),
    ],
    problems: [{ location: "linha 6", text: " | SEM BRINCO | 18", reason: "sem brinco" }],
    kept: [{ animal_id: "a-700", brinco: "700", nome: "AUSENTE", producao: 12 }],
    ...overrides,
  };
}

function row(overrides: Partial<ImportPreview["rows"][number]>): ImportPreview["rows"][number] {
  return {
    location: "linha 2",
    brinco_lido: "389",
    brinco: overrides.brinco_lido ?? "389",
    nome_arquivo: null,
    producao: 21.5,
    status: "new",
    animal_id: "a-1",
    animal_nome: "ÁGATA",
    existing_measurement_id: null,
    existing_producao: null,
    existing_provenance: null,
    notes: [],
    ...overrides,
  };
}

function record(overrides: Partial<ImportRecord> = {}): ImportRecord {
  return {
    id: "imp-1",
    measured_on: DAY,
    filename: "coleta.csv",
    file_format: "csv",
    mode: "new_only",
    reason: null,
    imported_by: "joao@belovale",
    created_at: "2026-09-18T10:00:00Z",
    summary: {
      created: 1,
      replaced: 0,
      skipped_same: 1,
      skipped_different: 1,
      not_found: 1,
      no_brinco: 0,
      invalid: 0,
      exited: 0,
      duplicate: 0,
      unreadable_lines: 1,
      kept: 1,
    },
    already_imported: false,
    ...overrides,
  };
}

const FILE = new File(["Número;Nome;Produção\n389;ÁGATA;21,5\n"], "coleta.csv", {
  type: "text/csv",
});

function setup(props: Partial<Parameters<typeof ImportPanel>[0]> = {}) {
  const onPreview = vi.fn().mockResolvedValue(preview());
  const onCommit = vi.fn().mockResolvedValue(record());
  // Histórico "carregando": só o teste do histórico o faz responder.
  const onList = vi.fn(() => new Promise<never>(() => {}));
  const onImported = vi.fn();
  render(
    <ImportPanel
      token={TOKEN}
      canReplace={false}
      today="2026-09-18"
      onPreview={onPreview}
      onCommit={onCommit}
      onList={onList}
      onImported={onImported}
      {...props}
    />,
  );
  return { onPreview, onCommit, onList, onImported };
}

async function choose(): Promise<void> {
  fireEvent.change(screen.getByLabelText(/data da coleta/i), { target: { value: DAY } });
  fireEvent.change(screen.getByLabelText(/arquivo/i), { target: { files: [FILE] } });
  // A prévia responde de forma assíncrona: o act espera a tela assentar.
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /ver prévia/i }));
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ImportPanel", () => {
  it("mostra a prévia linha a linha antes de gravar", async () => {
    const { onPreview, onCommit } = setup();

    await choose();

    await waitFor(() => expect(onPreview).toHaveBeenCalledWith(TOKEN, FILE, DAY));
    const table = await screen.findByRole("table", { name: /prévia/i });
    expect(within(table).getByText("Nova")).toBeInTheDocument();
    expect(within(table).getByText(/já lançada/i)).toBeInTheDocument();
    expect(within(table).getByText(/diferente/i)).toBeInTheDocument();
    expect(within(table).getByText(/brinco não encontrado/i)).toBeInTheDocument();
    expect(screen.getByText(/linhas não lidas \(1\)/i)).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("operador importa só as novas e vê o que ficou de fora", async () => {
    const { onCommit, onImported } = setup({ canReplace: false });

    await choose();
    await screen.findByRole("table", { name: /prévia/i });

    expect(screen.queryByLabelText(/substituir/i)).not.toBeInTheDocument();
    expect(screen.getByText(/peça a um revisor/i)).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /importar 1 leitura/i }));
    });

    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(TOKEN, FILE, DAY, "new_only", null),
    );
    expect(await screen.findByText(/importação concluída/i)).toBeInTheDocument();
    expect(onImported).toHaveBeenCalled();
  });

  it("revisor substitui as diferentes com motivo, e a vaca fora do arquivo é mantida", async () => {
    const onCommit = vi
      .fn()
      .mockResolvedValue(record({ mode: "replace", summary: { ...record().summary, replaced: 1 } }));
    setup({ canReplace: true, onCommit });

    await choose();
    await screen.findByRole("table", { name: /prévia/i });

    fireEvent.click(screen.getByLabelText(/substituir as diferentes/i));
    expect(screen.getByText(/mantêm a leitura atual/i)).toBeInTheDocument();
    expect(screen.getByText(/AUSENTE/)).toBeInTheDocument();

    const confirm = screen.getByRole("button", { name: /importar 1 e substituir 1/i });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/motivo/i), {
      target: { value: "dados de 25/08 normalizados" },
    });
    await act(async () => {
      fireEvent.click(confirm);
    });

    await waitFor(() =>
      expect(onCommit).toHaveBeenCalledWith(
        TOKEN,
        FILE,
        DAY,
        "replace",
        "dados de 25/08 normalizados",
      ),
    );
  });

  it("avisa quando o arquivo já tinha sido importado", async () => {
    setup({ onCommit: vi.fn().mockResolvedValue(record({ already_imported: true })) });

    await choose();
    await screen.findByRole("table", { name: /prévia/i });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /importar 1 leitura/i }));
    });

    expect(await screen.findByText(/já tinha sido importado/i)).toBeInTheDocument();
  });

  it("explica por que o arquivo foi recusado", async () => {
    const refused = new ApiError(422, {
      code: "unprocessable",
      detail: "Arquivo .xls antigo. Abra no Excel e salve como .xlsx ou .csv.",
    });
    setup({ onPreview: vi.fn().mockRejectedValue(refused) });

    await choose();

    expect(await screen.findByRole("alert")).toHaveTextContent(/salve como \.xlsx/i);
  });

  it("sem nada novo, não oferece importar", async () => {
    setup({
      onPreview: vi.fn().mockResolvedValue(
        preview({
          counts: { ...preview().counts, new: 0, different: 0 },
          rows: [row({ status: "same", existing_producao: 21.5 })],
          kept: [],
        }),
      ),
    });

    await choose();
    await screen.findByRole("table", { name: /prévia/i });

    expect(screen.getByText(/nada a importar/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^importar/i })).not.toBeInTheDocument();
  });

  it("trocar o arquivo descarta a prévia anterior", async () => {
    setup();

    await choose();
    await screen.findByRole("table", { name: /prévia/i });
    fireEvent.change(screen.getByLabelText(/arquivo/i), { target: { files: [FILE] } });

    expect(screen.queryByRole("table", { name: /prévia/i })).not.toBeInTheDocument();
  });

  it("lista as últimas importações", async () => {
    setup({
      onList: vi
        .fn()
        .mockResolvedValue([record({ filename: "julho.csv", imported_by: "maria@belovale" })]),
    });

    expect(await screen.findByText("julho.csv")).toBeInTheDocument();
    expect(screen.getByText(/maria@belovale/)).toBeInTheDocument();
  });
});
