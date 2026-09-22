import { useEffect, useState, type CSSProperties } from "react";

import { createAnimal, searchAnimals } from "../../api/client";
import { EXIT_REASON_LABEL, type Animal, type AnimalPage, type AnimalSearch } from "../../api/types";
import { Icons } from "../../ui/Brand";
import { brDate, farmToday } from "../../ui/dates";
import { PageHeader } from "../../ui/PageHeader";

/**
 * Busca de animais.
 *
 * Um campo só, porque no curral ninguém quer escolher entre "buscar por
 * brinco" e "buscar por nome" — o termo é classificado aqui. A fazenda nunca
 * é pedida: vem do servidor.
 */

type SearchFn = (token: string, search: AnimalSearch) => Promise<AnimalPage>;
type CreateFn = (
  token: string,
  input: { brinco?: string | null; name?: string | null; lote?: string | null },
) => Promise<Animal>;

interface Props {
  token: string;
  canEdit: boolean;
  onOpen: (animalId: string) => void;
  onSearch?: SearchFn;
  onCreate?: CreateFn;
}

/** Um termo só de dígitos ou no formato `B1-123` é brinco; o resto é nome. */
function looksLikeBrinco(term: string): boolean {
  return /^[bB]?\d*[-\s]?\d+[a-zA-Z]*$/.test(term.trim()) && /\d/.test(term);
}

/** O limite de página da API. A impressão percorre todas. */
const PRINT_PAGE = 200;

function describeSearch(search: AnimalSearch): string {
  if (search.brinco) return `Brinco ${search.brinco}`;
  if (search.name) return `Nome contendo "${search.name}"`;
  if (search.semBrinco) return "Animais sem brinco";
  if (search.rebanho === "baixados") return "Animais que saíram do rebanho";
  return "Todos os animais do rebanho";
}

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return body?.detail ?? "Não foi possível completar a ação. Tente novamente.";
}

export function AnimalSearchPage({
  token,
  canEdit,
  onOpen,
  onSearch = searchAnimals,
  onCreate = createAnimal,
}: Props): JSX.Element {
  const [term, setTerm] = useState("");
  const [result, setResult] = useState<AnimalPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newBrinco, setNewBrinco] = useState("");
  const [newName, setNewName] = useState("");
  const [newLote, setNewLote] = useState("");
  const [lastSearch, setLastSearch] = useState<AnimalSearch>({});
  const [printItems, setPrintItems] = useState<Animal[] | null>(null);

  // Imprime depois que a lista completa entrou na página, e a tira de novo
  // quando a impressão termina.
  useEffect(() => {
    if (printItems === null) return;
    const done = (): void => setPrintItems(null);
    window.addEventListener("afterprint", done);
    window.print();
    return () => window.removeEventListener("afterprint", done);
  }, [printItems]);

  async function printAll(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const collected: Animal[] = [];
      let total = Infinity;
      for (let offset = 0; offset < total; offset += PRINT_PAGE) {
        const page = await onSearch(token, { ...lastSearch, limit: PRINT_PAGE, offset });
        total = page.total;
        collected.push(...page.items);
        if (page.items.length === 0) break;
      }
      setPrintItems(collected);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function run(search: AnimalSearch): Promise<void> {
    setLastSearch(search);
    setPrintItems(null);
    setBusy(true);
    setError(null);
    try {
      setResult(await onSearch(token, search));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  // Abre com o rebanho na tela: a busca refina, não é pré-requisito.
  useEffect(() => {
    void run({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function more(): Promise<void> {
    if (result === null) return;
    setBusy(true);
    setError(null);
    try {
      const next = await onSearch(token, { ...lastSearch, offset: result.items.length });
      setResult({ ...next, items: [...result.items, ...next.items] });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function handleSearch(): void {
    const trimmed = term.trim();
    if (!trimmed) {
      void run({});
      return;
    }
    void run(looksLikeBrinco(trimmed) ? { brinco: trimmed } : { name: trimmed });
  }

  async function handleCreate(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const created = await onCreate(token, {
        brinco: newBrinco.trim() || null,
        name: newName.trim() || null,
        lote: newLote.trim() || null,
      });
      setCreating(false);
      setNewBrinco("");
      setNewName("");
      setNewLote("");
      onOpen(created.id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="animals">
      <PageHeader title="Animais">Digite o brinco ou o nome e abra a ficha.</PageHeader>

      <div className="search-row">
        <label htmlFor="animal-term">Brinco ou nome</label>
        <input
          id="animal-term"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") handleSearch();
          }}
          placeholder="Ex.: 389 ou Ágata"
          inputMode="search"
          autoComplete="off"
        />
        <button type="button" onClick={handleSearch} disabled={busy}>
          <Icons.search /> Buscar
        </button>
      </div>

      <div className="search-shortcuts">
        <button type="button" onClick={() => void run({ semBrinco: true })} disabled={busy}>
          Sem brinco
        </button>
        <button type="button" onClick={() => void run({})} disabled={busy}>
          Todos
        </button>
        <button
          type="button"
          onClick={() => void run({ rebanho: "baixados" })}
          disabled={busy}
        >
          Baixados
        </button>
        {canEdit && (
          <button type="button" onClick={() => setCreating((open) => !open)}>
            Cadastrar animal
          </button>
        )}
      </div>

      {creating && canEdit && (
        <form
          className="create-animal"
          onSubmit={(event) => {
            event.preventDefault();
            void handleCreate();
          }}
        >
          <h3>Cadastrar animal</h3>
          <label htmlFor="new-brinco">Brinco (opcional)</label>
          <input
            id="new-brinco"
            value={newBrinco}
            onChange={(event) => setNewBrinco(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="new-name">Nome</label>
          <input
            id="new-name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="new-lote">Lote ou grupo (opcional)</label>
          <input
            id="new-lote"
            value={newLote}
            onChange={(event) => setNewLote(event.target.value)}
            autoComplete="off"
          />
          <p className="hint">
            O animal pode ser cadastrado sem brinco e receber um depois.
          </p>
          <button type="submit" disabled={busy}>
            Salvar animal
          </button>
        </form>
      )}

      {error && <p role="alert">{error}</p>}
      {busy && result === null && (
        <>
          <div className="skeleton" style={{ height: 64, margin: "12px 0" }} />
          <div className="skeleton" style={{ height: 64 }} />
        </>
      )}

      {result && (
        <>
          {result.items.length === 0 ? (
            <p className="chart-empty">Nenhum animal encontrado para essa busca.</p>
          ) : (
            <ul className="animal-list">
              {result.items.map((item, index) => (
                <li key={item.id} style={{ "--i": index } as CSSProperties}>
                  <button type="button" onClick={() => onOpen(item.id)}>
                    <span className={item.brinco ? "tag" : "tag none"}>
                      {item.brinco ?? "sem brinco"}
                    </span>
                    <span className="name">
                      {item.name ?? "sem nome"}
                      <small>
                        {/* Lote de ordenha e grupo de manejo são coisas
                            diferentes: dizer "lote ENGORDA" seria falso. */}
                        {item.exited_on
                          ? `baixa · ${
                              item.exit_reason
                                ? EXIT_REASON_LABEL[item.exit_reason].toLowerCase()
                                : "sem motivo"
                            }`
                          : (item.lote_atual ??
                            (item.grupo_manejo ? `em ${item.grupo_manejo}` : "sem lote"))}
                        {item.situacao && !item.exited_on ? ` · ${item.situacao}` : ""}
                      </small>
                    </span>
                    <span className="chev" aria-hidden="true">
                      <Icons.chevron />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {result.items.length < result.total && (
            <button type="button" className="secondary show-more" disabled={busy} onClick={() => void more()}>
              Mostrar mais ({result.total - result.items.length})
            </button>
          )}
          <p className="count">
            {result.total} {result.total === 1 ? "animal" : "animais"}
            {result.total > 0 && (
              <button
                type="button"
                className="link-btn"
                onClick={() => void printAll()}
                disabled={busy}
              >
                Imprimir lista
              </button>
            )}
          </p>
        </>
      )}

      {printItems !== null && (
        <div className="print-area" aria-hidden="true">
          <h1>Lista de animais</h1>
          <p>
            {describeSearch(lastSearch)} · {printItems.length}{" "}
            {printItems.length === 1 ? "animal" : "animais"} · impresso em{" "}
            {brDate(farmToday())}
          </p>
          <table>
            <thead>
              <tr>
                <th>Brinco</th>
                <th>Nome</th>
                <th>Lote ou área</th>
                <th>Situação</th>
                <th>Último parto</th>
              </tr>
            </thead>
            <tbody>
              {printItems.map((item) => (
                <tr key={item.id}>
                  <td>{item.brinco ?? "sem brinco"}</td>
                  <td>{item.name ?? "sem nome"}</td>
                  <td>{item.lote_atual ?? item.grupo_manejo ?? "—"}</td>
                  <td>{item.exited_on ? "baixa" : (item.situacao ?? "—")}</td>
                  <td>{brDate(item.ultimo_parto)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
