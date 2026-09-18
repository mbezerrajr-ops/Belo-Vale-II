import { useState, type CSSProperties } from "react";

import { assignLot, linkBrinco, updateAnimal } from "../../api/client";
import type { Animal, AnimalDetail, AnimalUpdateInput } from "../../api/types";

/**
 * Ficha do animal.
 *
 * As duas ações do curral — vincular brinco e mudar de lote — ficam em
 * destaque. Editar cadastro existe, mas em segundo plano: é trabalho de
 * escritório.
 */

type LinkFn = (
  token: string,
  animalId: string,
  brinco: string,
  evidence: string,
) => Promise<Animal>;
type AssignFn = (
  token: string,
  animalId: string,
  lote: string,
  validFrom: string,
) => Promise<Animal>;
type UpdateFn = (
  token: string,
  animalId: string,
  changes: AnimalUpdateInput,
) => Promise<Animal>;

interface Props {
  token: string;
  animal: AnimalDetail;
  canEdit: boolean;
  onChanged: () => void;
  onLinkBrinco?: LinkFn;
  onAssignLot?: AssignFn;
  onUpdate?: UpdateFn;
}

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return body?.detail ?? "Não foi possível completar a ação. Tente novamente.";
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function br(iso: string | null): string {
  if (!iso) return "—";
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
}

export function AnimalDetailPanel({
  token,
  animal,
  canEdit,
  onChanged,
  onLinkBrinco = linkBrinco,
  onAssignLot = assignLot,
  onUpdate = updateAnimal,
}: Props): JSX.Element {
  const [panel, setPanel] = useState<"none" | "brinco" | "lote" | "cadastro">("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [brinco, setBrinco] = useState("");
  const [evidence, setEvidence] = useState("");
  const [lote, setLote] = useState("");
  const [validFrom, setValidFrom] = useState(today());
  const [name, setName] = useState(animal.name ?? "");
  const [situacao, setSituacao] = useState(animal.situacao ?? "");
  const [ultimoParto, setUltimoParto] = useState(animal.ultimo_parto ?? "");

  async function guard(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
      setPanel("none");
      onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function submitBrinco(): void {
    if (!brinco.trim()) {
      setError("Informe o número do brinco.");
      return;
    }
    if (!evidence.trim()) {
      // Vincular brinco muda a identidade do animal: sem justificativa, não vai.
      setError("Informe a evidência que sustenta o vínculo.");
      return;
    }
    void guard(() => onLinkBrinco(token, animal.id, brinco.trim(), evidence.trim()));
  }

  function submitLot(): void {
    if (!lote.trim()) {
      setError("Informe o lote.");
      return;
    }
    void guard(() => onAssignLot(token, animal.id, lote.trim(), validFrom));
  }

  function submitCadastro(): void {
    const changes: AnimalUpdateInput = {
      name: name.trim() || null,
      situacao: situacao.trim() || null,
      ultimo_parto: ultimoParto || null,
    };
    void guard(() => onUpdate(token, animal.id, changes));
  }

  return (
    <section className="animal-detail">
      <header className="detail-head">
        <div>
          <h2>{animal.name ?? "Animal sem nome"}</h2>
          <p className="brinco">
            {animal.brinco ? (
              <>
                Brinco <strong>{animal.brinco}</strong>
              </>
            ) : (
              <>
                <strong>Sem brinco</strong>
                {animal.brinco_origem && (
                  <> — leitura ilegível registrada: {animal.brinco_origem}</>
                )}
              </>
            )}
          </p>
        </div>
        {animal.brinco && <span className="tag">{animal.brinco}</span>}
      </header>

      <dl className="animal-fields">
        <div>
          <dt>Lote de ordenha</dt>
          <dd>{animal.lote_atual ?? "—"}</dd>
        </div>
        <div>
          <dt>Grupo de manejo</dt>
          <dd>{animal.grupo_manejo ?? "—"}</dd>
        </div>
        <div>
          <dt>Situação</dt>
          <dd>{animal.situacao ?? "—"}</dd>
        </div>
        <div>
          <dt>Último parto</dt>
          <dd>{br(animal.ultimo_parto)}</dd>
        </div>
        <div>
          <dt>Número legado</dt>
          <dd>{animal.numero_legado ?? "—"}</dd>
        </div>
      </dl>

      {!animal.brinco && (
        <p className="warning">
          Este animal não recebe medição automática enquanto não tiver brinco.
        </p>
      )}

      {canEdit && (
        <div className="actions">
          <button type="button" onClick={() => setPanel("brinco")}>
            {animal.brinco ? "Trocar brinco" : "Vincular brinco"}
          </button>
          <button type="button" onClick={() => setPanel("lote")}>
            Mudar de lote
          </button>
          <button type="button" className="secondary" onClick={() => setPanel("cadastro")}>
            Editar cadastro
          </button>
        </div>
      )}

      {error && <p role="alert">{error}</p>}

      {panel === "brinco" && canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitBrinco();
          }}
        >
          <h3>Vincular brinco</h3>
          <label htmlFor="novo-brinco">Novo brinco</label>
          <input
            id="novo-brinco"
            value={brinco}
            onChange={(event) => setBrinco(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="evidencia">Evidência</label>
          <input
            id="evidencia"
            value={evidence}
            onChange={(event) => setEvidence(event.target.value)}
            placeholder="Ex.: brinco aplicado no curral hoje"
            autoComplete="off"
          />
          <p className="hint">
            Isso muda a identidade do animal e fica registrado com seu nome.
          </p>
          <button type="submit" disabled={busy}>
            Confirmar vínculo
          </button>
        </form>
      )}

      {panel === "lote" && canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitLot();
          }}
        >
          <h3>Mudar de lote ou grupo</h3>
          <label htmlFor="novo-lote">Novo lote ou grupo</label>
          <input
            id="novo-lote"
            value={lote}
            onChange={(event) => setLote(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="valid-from">A partir de</label>
          <input
            id="valid-from"
            type="date"
            value={validFrom}
            onChange={(event) => setValidFrom(event.target.value)}
          />
          <p className="hint">
            "LOTE 1", "LOTE 2" e "LOTE 3" são lotes de ordenha, com dieta e
            custo. Outros nomes — ENGORDA, BEZERREIRO, PIQUETES — são áreas da
            fazenda, e não substituem o lote de ordenha. O registro anterior do
            mesmo tipo fica no histórico, com a data em que terminou.
          </p>
          <button type="submit" disabled={busy}>
            Confirmar lote
          </button>
        </form>
      )}

      {panel === "cadastro" && canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitCadastro();
          }}
        >
          <h3>Editar cadastro</h3>
          <label htmlFor="edit-name">Nome</label>
          <input
            id="edit-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="edit-situacao">Situação</label>
          <select
            id="edit-situacao"
            value={situacao}
            onChange={(event) => setSituacao(event.target.value)}
          >
            <option value="">—</option>
            <option value="Em lactação">Em lactação</option>
            <option value="Seca">Seca</option>
          </select>
          <label htmlFor="edit-parto">Último parto</label>
          <input
            id="edit-parto"
            type="date"
            value={ultimoParto}
            onChange={(event) => setUltimoParto(event.target.value)}
          />
          <p className="hint">
            Registrar o último parto é o que permite calcular os dias em lactação.
          </p>
          <button type="submit" disabled={busy}>
            Salvar cadastro
          </button>
        </form>
      )}

      <h3>Histórico de lotes e grupos</h3>
      {animal.historico_lotes.length === 0 ? (
        <p className="chart-empty">Sem registro de lotação.</p>
      ) : (
        <ul className="lot-history">
          {animal.historico_lotes.map((entry, index) => (
            <li
              key={`${entry.lote}-${entry.valid_from}`}
              style={{ "--i": index } as CSSProperties}
            >
              <span
                className={`timeline-dot${entry.valid_to ? " past" : ""}`}
                aria-hidden="true"
              />
              <strong>{entry.lote}</strong>
              <span className="role-pill">
                {entry.kind === "diet" ? "ordenha" : "manejo"}
              </span>
              <span>
                {br(entry.valid_from)} — {entry.valid_to ? br(entry.valid_to) : "atual"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
