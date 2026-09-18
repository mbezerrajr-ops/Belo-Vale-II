import { useState } from "react";

import { createAnimal, searchAnimals } from "../../api/client";
import type { Animal, AnimalPage, AnimalSearch } from "../../api/types";

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

  async function run(search: AnimalSearch): Promise<void> {
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
      <h2>Animais</h2>

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
          Buscar
        </button>
      </div>

      <div className="search-shortcuts">
        <button type="button" onClick={() => void run({ semBrinco: true })} disabled={busy}>
          Sem brinco
        </button>
        <button type="button" onClick={() => void run({})} disabled={busy}>
          Todos
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
          <label htmlFor="new-lote">Lote (opcional)</label>
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
      {busy && <p>Buscando…</p>}

      {result && !busy && (
        <>
          {result.items.length === 0 ? (
            <p>Nenhum animal encontrado para essa busca.</p>
          ) : (
            <ul className="animal-list">
              {result.items.map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => onOpen(item.id)}>
                    <strong>{item.brinco ?? "sem brinco"}</strong>
                    <span>{item.name ?? "sem nome"}</span>
                    <small>{item.lote_atual ?? "sem lote"}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="count">
            {result.total} {result.total === 1 ? "animal" : "animais"}
          </p>
        </>
      )}
    </section>
  );
}
