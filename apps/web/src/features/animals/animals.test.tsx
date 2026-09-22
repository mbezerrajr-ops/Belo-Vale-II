/**
 * Telas do cadastro de animais.
 *
 * Quem usa isto está no curral, no celular, com o brinco na mão. Os testes
 * cobrem o caminho principal — achar a vaca, vincular brinco, mudar de lote —
 * e as proteções que impedem um erro caro: evidência obrigatória ao vincular
 * brinco, e nenhum campo de fazenda para o usuário preencher.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnimalDetailPanel } from "./AnimalDetailPanel";
import { AnimalSearchPage } from "./AnimalSearchPage";
import type { AnimalDetail, AnimalPage } from "../../api/types";

// A ficha carrega o histórico de produção sozinha. Estes testes tratam de
// outras partes da ficha: o histórico fica "carregando" e não atualiza a
// tela depois que o teste termina.
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  getAnimalProduction: () => new Promise(() => {}),
}));

const TOKEN = "token-de-teste";

function animal(overrides: Partial<AnimalDetail> = {}): AnimalDetail {
  return {
    id: "a-1",
    farm_id: "f-1",
    brinco: "389",
    brinco_origem: "389",
    legacy_id: "v389",
    numero_legado: "389",
    name: "ÁGATA",
    situacao: "Em lactação",
    status: "Ativo",
    ultimo_parto: "2026-01-20",
    nascimento: null,
    peso: null,
    observacoes: null,
    lote_atual: "LOTE 3",
    grupo_manejo: null,
    historico_lotes: [
      {
        lote: "LOTE 3",
        kind: "diet",
        valid_from: "2026-08-25",
        valid_to: null,
        source: "legacy_baseline",
        reviewed_by: "titular",
      },
    ],
    ...overrides,
  };
}

function page(items: AnimalDetail[]): AnimalPage {
  return { items, total: items.length, limit: 25, offset: 0 };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AnimalSearchPage", () => {
  it("busca pelo brinco digitado", async () => {
    const search = vi.fn().mockResolvedValue(page([animal()]));

    render(
      <AnimalSearchPage token={TOKEN} canEdit onSearch={search} onOpen={vi.fn()} />,
    );

    fireEvent.change(screen.getByLabelText(/brinco ou nome/i), {
      target: { value: "389" },
    });
    fireEvent.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1]).toMatchObject({ brinco: "389" });
    expect(await screen.findByText("ÁGATA")).toBeInTheDocument();
  });

  it("procura por nome quando o termo não parece um brinco", async () => {
    const search = vi.fn().mockResolvedValue(page([animal()]));

    render(
      <AnimalSearchPage token={TOKEN} canEdit onSearch={search} onOpen={vi.fn()} />,
    );

    fireEvent.change(screen.getByLabelText(/brinco ou nome/i), {
      target: { value: "agata" },
    });
    fireEvent.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1]).toMatchObject({ name: "agata" });
  });

  it("oferece o filtro dos animais sem brinco", async () => {
    const search = vi.fn().mockResolvedValue(page([]));

    render(
      <AnimalSearchPage token={TOKEN} canEdit onSearch={search} onOpen={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /sem brinco/i }));

    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1]).toMatchObject({ semBrinco: true });
  });

  it("mostra quando a busca não encontra nada, sem parecer erro", async () => {
    render(
      <AnimalSearchPage
        token={TOKEN}
        canEdit
        onSearch={vi.fn().mockResolvedValue(page([]))}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(/brinco ou nome/i), {
      target: { value: "9999" },
    });
    fireEvent.click(screen.getByRole("button", { name: /buscar/i }));

    expect(await screen.findByText(/nenhum animal/i)).toBeInTheDocument();
  });

  it("não pede fazenda ao usuário", () => {
    render(
      <AnimalSearchPage
        token={TOKEN}
        canEdit
        onSearch={vi.fn().mockResolvedValue(page([]))}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText(/fazenda/i)).not.toBeInTheDocument();
  });

  it("esconde o cadastro de animal de quem não pode editar", () => {
    render(
      <AnimalSearchPage
        token={TOKEN}
        canEdit={false}
        onSearch={vi.fn().mockResolvedValue(page([]))}
        onOpen={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /cadastrar animal/i }),
    ).not.toBeInTheDocument();
  });
});

describe("AnimalDetailPanel — vincular brinco", () => {
  it("destaca a ação para quem ainda não tem brinco", () => {
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null, brinco_origem: "B2-XXX" })}
        canEdit
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /vincular brinco/i })).toBeInTheDocument();
    expect(screen.getByText(/sem brinco/i)).toBeInTheDocument();
  });

  it("exige evidência antes de enviar", async () => {
    const link = vi.fn();

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null })}
        canEdit
        onChanged={vi.fn()}
        onLinkBrinco={link}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /vincular brinco/i }));
    fireEvent.change(screen.getByLabelText(/novo brinco/i), {
      target: { value: "B1-900" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar v[íi]nculo/i }));

    expect(await screen.findByText(/informe a evid[êe]ncia/i)).toBeInTheDocument();
    expect(link).not.toHaveBeenCalled();
  });

  it("tira o brinco da vaca errada, com evidência", async () => {
    const unlink = vi.fn().mockResolvedValue(animal({ brinco: null }));
    const onChanged = vi.fn();

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: "B2-649", name: "REDONDA" })}
        canEdit
        onChanged={onChanged}
        onUnlinkBrinco={unlink}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /tirar o brinco/i }));
    fireEvent.change(screen.getByLabelText(/evid[êe]ncia/i), {
      target: { value: "O 649 é da BRANQUINHA (folha de 25/08)" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /confirmar e tirar o brinco/i }));
    });

    expect(unlink).toHaveBeenCalledWith(TOKEN, "a-1", "O 649 é da BRANQUINHA (folha de 25/08)");
    expect(onChanged).toHaveBeenCalled();
  });

  it("não tira o brinco sem evidência", async () => {
    const unlink = vi.fn();

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: "B2-649" })}
        canEdit
        onChanged={vi.fn()}
        onUnlinkBrinco={unlink}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /tirar o brinco/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirmar e tirar o brinco/i }));

    expect(await screen.findByText(/informe a evid[êe]ncia/i)).toBeInTheDocument();
    expect(unlink).not.toHaveBeenCalled();
  });

  it("vaca sem brinco não oferece tirar o brinco", () => {
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null })}
        canEdit
        onChanged={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /tirar o brinco/i })).not.toBeInTheDocument();
  });

  it("envia brinco e evidência quando ambos estão preenchidos", async () => {
    const link = vi.fn().mockResolvedValue(animal({ brinco: "B1-900" }));
    const onChanged = vi.fn();

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null })}
        canEdit
        onChanged={onChanged}
        onLinkBrinco={link}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /vincular brinco/i }));
    fireEvent.change(screen.getByLabelText(/novo brinco/i), {
      target: { value: "B1-900" },
    });
    fireEvent.change(screen.getByLabelText(/evid[êe]ncia/i), {
      target: { value: "Brinco aplicado no curral" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar v[íi]nculo/i }));

    await waitFor(() =>
      expect(link).toHaveBeenCalledWith(
        TOKEN,
        "a-1",
        "B1-900",
        "Brinco aplicado no curral",
      ),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("mostra o motivo quando o brinco já pertence a outro animal", async () => {
    const link = vi
      .fn()
      .mockRejectedValue(
        Object.assign(new Error("conflito"), {
          status: 409,
          body: { detail: "O brinco '444' já pertence a outro animal (DONO)." },
        }),
      );

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null })}
        canEdit
        onChanged={vi.fn()}
        onLinkBrinco={link}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /vincular brinco/i }));
    fireEvent.change(screen.getByLabelText(/novo brinco/i), {
      target: { value: "444" },
    });
    fireEvent.change(screen.getByLabelText(/evid[êe]ncia/i), {
      target: { value: "conferido" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar v[íi]nculo/i }));

    expect(await screen.findByText(/j[áa] pertence a outro animal/i)).toBeInTheDocument();
  });

  it("não oferece a ação a quem não pode editar", () => {
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ brinco: null })}
        canEdit={false}
        onChanged={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /vincular brinco/i }),
    ).not.toBeInTheDocument();
  });
});

describe("AnimalDetailPanel — mudar de lote", () => {
  it("mostra o lote atual e o histórico", () => {
    render(
      <AnimalDetailPanel token={TOKEN} animal={animal()} canEdit onChanged={vi.fn()} />,
    );

    // Aparece duas vezes de propósito: como lote atual e na linha do histórico.
    expect(screen.getAllByText("LOTE 3")).toHaveLength(2);
    expect(screen.getByText(/hist[óo]rico de lote/i)).toBeInTheDocument();
  });

  it("envia a mudança com a data informada", async () => {
    const assign = vi.fn().mockResolvedValue(animal({ lote_atual: "LOTE 5" }));

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal()}
        canEdit
        onChanged={vi.fn()}
        onAssignLot={assign}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mudar de lote/i }));
    fireEvent.change(screen.getByLabelText(/novo lote/i), {
      target: { value: "LOTE 5" },
    });
    fireEvent.change(screen.getByLabelText(/a partir de/i), {
      target: { value: "2026-09-18" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar lote/i }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(TOKEN, "a-1", "LOTE 5", "2026-09-18"),
    );
  });

  it("explica o que é lote de ordenha e o que é área da fazenda", () => {
    render(
      <AnimalDetailPanel token={TOKEN} animal={animal()} canEdit onChanged={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mudar de lote/i }));

    expect(
      screen.getByText(/s[ãa]o lotes de ordenha, com dieta e custo/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/registro anterior do mesmo tipo fica no hist[óo]rico/i),
    ).toBeInTheDocument();
  });
});

describe("AnimalDetailPanel — lote de ordenha × grupo de manejo", () => {
  it("não chama grupo de manejo de lote", () => {
    // O caso que motivou isto: "ENGORDA" aparecia como se fosse o lote.
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({
          lote_atual: null,
          grupo_manejo: "ENGORDA",
          historico_lotes: [
            {
              lote: "ENGORDA",
              kind: "management",
              valid_from: "2026-08-25",
              valid_to: null,
              source: "legacy_baseline",
              reviewed_by: "titular",
            },
          ],
        })}
        canEdit
        onChanged={vi.fn()}
      />,
    );

    const ordenha = screen.getByText("Lote de ordenha").closest("div")!;
    expect(within(ordenha).getByText("—")).toBeInTheDocument();

    const manejo = screen.getByText("Grupo de manejo").closest("div")!;
    expect(within(manejo).getByText("ENGORDA")).toBeInTheDocument();
  });

  it("mostra os dois quando o animal está em lote e em área", () => {
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({ lote_atual: "LOTE 1", grupo_manejo: "PIQUETES / REPASSE" })}
        canEdit
        onChanged={vi.fn()}
      />,
    );

    const ordenha = screen.getByText("Lote de ordenha").closest("div")!;
    expect(within(ordenha).getByText("LOTE 1")).toBeInTheDocument();
    const manejo = screen.getByText("Grupo de manejo").closest("div")!;
    expect(within(manejo).getByText("PIQUETES / REPASSE")).toBeInTheDocument();
  });

  it("rotula cada registro do histórico com seu tipo", () => {
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({
          historico_lotes: [
            {
              lote: "LOTE 3",
              kind: "diet",
              valid_from: "2026-08-25",
              valid_to: null,
              source: "legacy_baseline",
              reviewed_by: "titular",
            },
            {
              lote: "ENGENHO",
              kind: "management",
              valid_from: "2026-09-01",
              valid_to: null,
              source: "manual",
              reviewed_by: "revisor",
            },
          ],
        })}
        canEdit
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByText("ordenha")).toBeInTheDocument();
    expect(screen.getByText("manejo")).toBeInTheDocument();
  });
});

describe("AnimalDetailPanel — juntar fichas", () => {
  // A vaca com duas fichas: uma com o brinco, outra sem, cada uma com parte
  // da produção. Antes, a correção era anular e relançar, uma por vez.
  const certa = animal({ id: "a-861", brinco: "861", name: "SAIA BRANCA", lote_atual: null });
  const duplicada = animal({
    id: "a-dup",
    brinco: null,
    brinco_origem: null,
    name: "SAIA BRANCA",
    lote_atual: "LOTE 1",
  });

  function previa(extra = {}) {
    return {
      keep: certa,
      drop: duplicada,
      moves: [{ measured_on: "2026-07-22", producao: 21.5 }],
      conflicts: [],
      fills: { nascimento: "2019-03-10" },
      lots: ["LOTE 1"],
      pending_proposals: 1,
      blockers: [],
      ...extra,
    };
  }

  function montar(props = {}) {
    const onSearch = vi.fn().mockResolvedValue(page([duplicada, certa]));
    const onPreviewMerge = vi.fn().mockResolvedValue(previa());
    const onMerge = vi.fn().mockResolvedValue(certa);
    const onOpenAnimal = vi.fn();
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={duplicada}
        canEdit
        onChanged={vi.fn()}
        onSearch={onSearch}
        onPreviewMerge={onPreviewMerge}
        onMerge={onMerge}
        onOpenAnimal={onOpenAnimal}
        {...props}
      />,
    );
    return { onSearch, onPreviewMerge, onMerge, onOpenAnimal };
  }

  async function escolherACerta(): Promise<void> {
    fireEvent.click(screen.getByRole("button", { name: /juntar com outra ficha/i }));
    fireEvent.change(screen.getByLabelText(/brinco ou nome da outra ficha/i), {
      target: { value: "861" },
    });
    const buscar = screen.getAllByRole("button", { name: /^buscar$/i });
    await act(async () => {
      fireEvent.click(buscar[buscar.length - 1]);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /é esta: 861/i }));
    });
  }

  it("mostra o que vai acontecer antes de juntar", async () => {
    const { onSearch, onPreviewMerge } = montar();

    await escolherACerta();

    expect(onSearch.mock.calls[0][1]).toMatchObject({ brinco: "861", rebanho: "todos" });
    expect(onPreviewMerge).toHaveBeenCalledWith(TOKEN, "a-dup", "a-861");
    // A própria ficha não aparece como opção.
    expect(screen.queryByRole("button", { name: /é esta: sem brinco/i })).not.toBeInTheDocument();
    const efeitos = screen.getByRole("list", { name: /o que a junção faz/i });
    expect(efeitos).toHaveTextContent(/1 produção passa para a ficha que fica: 22\/07\/2026 — 21,5 L/);
    expect(efeitos).toHaveTextContent(/nascimento 10\/03\/2019/);
    expect(efeitos).toHaveTextContent(/entra em lote 1/i);
    expect(efeitos).toHaveTextContent(/1 proposta pendente/);
  });

  it("junta com o motivo e abre a ficha que ficou", async () => {
    const { onMerge, onOpenAnimal } = montar();
    await escolherACerta();

    const juntar = screen.getByRole("button", { name: /^juntar fichas$/i });
    expect(juntar).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/por que são o mesmo animal/i), {
      target: { value: "conferido no curral" },
    });
    await act(async () => {
      fireEvent.click(juntar);
    });

    expect(onMerge).toHaveBeenCalledWith(TOKEN, "a-dup", "a-861", "conferido no curral");
    expect(onOpenAnimal).toHaveBeenCalledWith("a-861");
  });

  it("o que impede juntar aparece, e não há botão para forçar", async () => {
    montar({
      onPreviewMerge: vi.fn().mockResolvedValue(
        previa({ blockers: ["As duas fichas têm produção no mesmo dia: 22/07/2026."] }),
      ),
    });

    await escolherACerta();

    expect(screen.getByRole("alert")).toHaveTextContent(/mesmo dia: 22\/07\/2026/);
    expect(screen.queryByRole("button", { name: /^juntar fichas$/i })).not.toBeInTheDocument();
  });

  it("a ficha arquivada avisa, leva à que ficou e não oferece mais nada", () => {
    const onOpenAnimal = vi.fn();
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={{ ...duplicada, merged_into_id: "a-861", merged_at: "2026-09-22T12:00:00Z" }}
        canEdit
        onChanged={vi.fn()}
        onOpenAnimal={onOpenAnimal}
      />,
    );

    expect(screen.getByText(/ficha juntada a outra em 22\/09\/2026/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /abrir a ficha que ficou/i }));
    expect(onOpenAnimal).toHaveBeenCalledWith("a-861");
    expect(screen.queryByRole("button", { name: /vincular brinco|mudar de lote|dar baixa|juntar/i })).not.toBeInTheDocument();
  });

  it("a ficha que ficou lista as fichas juntadas a ela", () => {
    const onOpenAnimal = vi.fn();
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={{
          ...certa,
          fichas_juntadas: [
            { id: "a-dup", name: "SAIA BRANCA", numero_legado: "862", merged_at: "2026-09-22T12:00:00Z" },
          ],
        }}
        canEdit
        onChanged={vi.fn()}
        onOpenAnimal={onOpenAnimal}
      />,
    );

    expect(screen.getByText(/nº antigo 862/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /ver a ficha arquivada/i }));
    expect(onOpenAnimal).toHaveBeenCalledWith("a-dup");
  });

  it("quem não pode editar não junta", () => {
    render(<AnimalDetailPanel token={TOKEN} animal={duplicada} canEdit={false} onChanged={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /juntar com outra ficha/i })).not.toBeInTheDocument();
  });
});
