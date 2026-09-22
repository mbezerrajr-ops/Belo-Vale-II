import { useState } from "react";

import { mergeAnimals, previewMerge, searchAnimals } from "../../api/client";
import type { Animal, AnimalPage, AnimalSearch, MergePreview } from "../../api/types";
import { brDate, liters } from "../../ui/dates";

/**
 * Juntar a ficha duplicada à ficha certa.
 *
 * Para a vaca que tem duas fichas — uma com o brinco, outra sem, cada uma
 * com parte da produção. A ficha com brinco é a que fica; a outra é
 * arquivada, e as produções dela passam para a que fica. Nada é apagado, e
 * nada é decidido em silêncio: antes de juntar, a tela mostra tudo o que vai
 * acontecer, e o que impede.
 */

type SearchFn = (token: string, search: AnimalSearch) => Promise<AnimalPage>;
type PreviewFn = (token: string, animalId: string, otherId: string) => Promise<MergePreview>;
type MergeFn = (token: string, animalId: string, otherId: string, reason: string) => Promise<Animal>;

interface Props {
  token: string;
  animal: Animal;
  onSearch?: SearchFn;
  onPreview?: PreviewFn;
  onMerge?: MergeFn;
  /** A junção terminou: abre a ficha que ficou. */
  onMerged: (keepId: string) => void;
  onCancel: () => void;
}

const FILL_LABEL: Record<string, string> = {
  name: "nome",
  nascimento: "nascimento",
  ultimo_parto: "último parto",
  peso: "peso",
  situacao: "situação",
  observacoes: "observações",
  numero_legado: "número legado",
};

const DATE_FIELDS = new Set(["nascimento", "ultimo_parto"]);

function who(animal: Animal): string {
  return `${animal.brinco ?? "sem brinco"} · ${animal.name ?? "sem nome"}`;
}

function fillText(field: string, value: string | number | null): string {
  if (value === null) return "—";
  if (DATE_FIELDS.has(field)) return brDate(String(value));
  return String(value);
}

function detailOf(error: unknown): string {
  const detail = (error as { body?: { detail?: unknown } })?.body?.detail;
  return typeof detail === "string" ? detail : "Não foi possível completar a ação. Tente novamente.";
}

export function MergeFichas({
  token,
  animal,
  onSearch = searchAnimals,
  onPreview = previewMerge,
  onMerge = mergeAnimals,
  onMerged,
  onCancel,
}: Props): JSX.Element {
  const [term, setTerm] = useState("");
  const [found, setFound] = useState<Animal[] | null>(null);
  const [preview, setPreview] = useState<MergePreview | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(): Promise<void> {
    const text = term.trim();
    if (!text) return;
    setError(null);
    setPreview(null);
    try {
      // Número é brinco; o resto é nome — como na busca de animais.
      const query: AnimalSearch = /^\d/.test(text) ? { brinco: text } : { name: text };
      const page = await onSearch(token, { ...query, rebanho: "todos" });
      setFound(page.items.filter((item) => item.id !== animal.id));
    } catch (caught) {
      setError(detailOf(caught));
    }
  }

  async function choose(other: Animal): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      setPreview(await onPreview(token, animal.id, other.id));
    } catch (caught) {
      setError(detailOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function merge(): Promise<void> {
    if (preview === null) return;
    setBusy(true);
    setError(null);
    try {
      // A outra ficha é sempre a que não é esta, fique quem ficar.
      const otherId = preview.keep.id === animal.id ? preview.drop.id : preview.keep.id;
      const kept = await onMerge(token, animal.id, otherId, reason.trim());
      onMerged(kept.id);
    } catch (caught) {
      setError(detailOf(caught));
      setBusy(false);
    }
  }

  const blocked = preview !== null && preview.blockers.length > 0;
  const fills = preview ? Object.entries(preview.fills) : [];

  return (
    <form
      className="merge-fichas"
      onSubmit={(event) => {
        event.preventDefault();
        void merge();
      }}
    >
      <h3>Juntar com outra ficha</h3>
      <p className="hint">
        Para a vaca que tem duas fichas — uma com o brinco, outra sem, cada uma com parte da
        produção. A ficha com brinco fica; a outra é arquivada, e as produções dela passam para a
        que fica. Nada é apagado.
      </p>

      <label htmlFor="merge-busca">Brinco ou nome da outra ficha</label>
      <div className="proposal-search">
        <input
          id="merge-busca"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void search();
            }
          }}
          autoComplete="off"
        />
        <button type="button" className="btn-ghost" onClick={() => void search()}>
          Buscar
        </button>
      </div>

      {found !== null && found.length === 0 && (
        <p className="hint">Nenhuma outra ficha com esse brinco ou nome.</p>
      )}
      {found !== null && preview === null && found.length > 0 && (
        <div className="merge-choices">
          {found.map((other) => (
            <button
              key={other.id}
              type="button"
              className="btn-ghost"
              disabled={busy}
              onClick={() => void choose(other)}
            >
              É esta: {who(other)}
              {other.lote_atual ? ` · ${other.lote_atual}` : ""}
            </button>
          ))}
        </div>
      )}

      {preview !== null && (
        <div className="merge-preview">
          <div className="merge-sides">
            <div className="merge-side keep">
              <small>Fica</small>
              <strong>{who(preview.keep)}</strong>
            </div>
            <span className="merge-arrow" aria-hidden="true">
              ←
            </span>
            <div className="merge-side drop">
              <small>É arquivada</small>
              <strong>{who(preview.drop)}</strong>
            </div>
          </div>

          <ul className="merge-effects" aria-label="O que a junção faz">
            <li>
              {preview.moves.length === 0
                ? "A ficha arquivada não tem produção a passar."
                : `${preview.moves.length} ${preview.moves.length === 1 ? "produção passa" : "produções passam"} para a ficha que fica: ${preview.moves
                    .map((move) => `${brDate(move.measured_on)} — ${move.producao === null ? "—" : `${liters(move.producao)} L`}`)
                    .join("; ")}.`}
            </li>
            {fills.length > 0 && (
              <li>
                Preenche o que falta na ficha que fica:{" "}
                {fills.map(([field, value]) => `${FILL_LABEL[field] ?? field} ${fillText(field, value)}`).join("; ")}.
              </li>
            )}
            {preview.lots.length > 0 && (
              <li>Entra em {preview.lots.join(" e ")} a partir de hoje.</li>
            )}
            {preview.pending_proposals > 0 && (
              <li>
                {preview.pending_proposals}{" "}
                {preview.pending_proposals === 1 ? "proposta pendente passa" : "propostas pendentes passam"}{" "}
                a apontar para a ficha que fica.
              </li>
            )}
          </ul>

          {preview.blockers.map((blocker) => (
            <p key={blocker} role="alert">
              {blocker}
            </p>
          ))}

          {!blocked && (
            <>
              <label htmlFor="merge-motivo">Por que são o mesmo animal?</label>
              <input
                id="merge-motivo"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Ex.: conferido no curral: a mesma vaca, ficha repetida"
                autoComplete="off"
              />
            </>
          )}
        </div>
      )}

      {error && <p role="alert">{error}</p>}

      <div className="actions">
        {preview !== null && !blocked && (
          <button type="submit" disabled={busy || reason.trim().length < 3}>
            Juntar fichas
          </button>
        )}
        {preview !== null && (
          <button type="button" className="secondary" onClick={() => setPreview(null)}>
            Escolher outra
          </button>
        )}
        <button type="button" className="secondary" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
