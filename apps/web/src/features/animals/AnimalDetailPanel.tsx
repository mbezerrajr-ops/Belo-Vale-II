import { useEffect, useRef, useState, type CSSProperties } from "react";

import {
  assignLot,
  linkBrinco,
  registerExit,
  undoExit,
  unlinkBrinco,
  updateAnimal,
} from "../../api/client";
import {
  EXIT_REASON_LABEL,
  type Animal,
  type AnimalDetail,
  type AnimalPage,
  type AnimalSearch,
  type AnimalUpdateInput,
  type ExitReason,
  type MergePreview,
} from "../../api/types";
import { Icons } from "../../ui/Brand";
import { usePanelFocus } from "../../ui/usePanelFocus";
import { brDate, farmToday } from "../../ui/dates";
import { MergeFichas } from "./MergeFichas";
import { ProductionHistory } from "./ProductionHistory";
import type { ProductionHistoryEntry, Reading } from "../../api/types";

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
type UnlinkFn = (token: string, animalId: string, evidence: string) => Promise<Animal>;
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

type ExitFn = (
  token: string,
  animalId: string,
  exitedOn: string,
  reason: ExitReason,
  notes: string | null,
) => Promise<Animal>;
type UndoExitFn = (token: string, animalId: string, reason: string) => Promise<Animal>;

interface Props {
  token: string;
  animal: AnimalDetail;
  canEdit: boolean;
  onChanged: () => void;
  onLinkBrinco?: LinkFn;
  onUnlinkBrinco?: UnlinkFn;
  onAssignLot?: AssignFn;
  onUpdate?: UpdateFn;
  onExit?: ExitFn;
  onUndoExit?: UndoExitFn;
  today?: string;
  /** Injetáveis para teste; por padrão, o cliente da API. */
  onLoadProduction?: (token: string, animalId: string) => Promise<ProductionHistoryEntry[]>;
  onCorrect?: (
    token: string,
    measurementId: string,
    producao: number,
    reason: string,
  ) => Promise<Reading>;
  onVoid?: (token: string, measurementId: string, reason: string) => Promise<void>;
  /** Abre outra ficha: a que ficou, depois de juntar, ou uma juntada a esta. */
  onOpenAnimal?: (animalId: string) => void;
  /** Injetáveis para teste da junção de fichas. */
  onSearch?: (token: string, search: AnimalSearch) => Promise<AnimalPage>;
  onPreviewMerge?: (token: string, animalId: string, otherId: string) => Promise<MergePreview>;
  onMerge?: (token: string, animalId: string, otherId: string, reason: string) => Promise<Animal>;
}

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return body?.detail ?? "Não foi possível completar a ação. Tente novamente.";
}

const br = brDate;

/** Dias em lactação: do último parto até hoje, no dia da fazenda. */
function daysInMilk(lastCalving: string | null, today: string): number | null {
  if (!lastCalving) return null;
  const days = Math.round((Date.parse(today) - Date.parse(lastCalving)) / 86_400_000);
  return Number.isFinite(days) && days >= 0 ? days : null;
}

export function AnimalDetailPanel({
  token,
  animal,
  canEdit,
  onChanged,
  onLinkBrinco = linkBrinco,
  onUnlinkBrinco = unlinkBrinco,
  onAssignLot = assignLot,
  onUpdate = updateAnimal,
  onExit = registerExit,
  onUndoExit = undoExit,
  today = farmToday(),
  onLoadProduction,
  onCorrect,
  onVoid,
  onOpenAnimal,
  onSearch,
  onPreviewMerge,
  onMerge,
}: Props): JSX.Element {
  const [panel, setPanel] = useState<
    "none" | "brinco" | "tirar-brinco" | "lote" | "cadastro" | "baixa" | "desfazer" | "juntar"
  >("none");
  // As ações raras (tirar brinco, juntar, baixa) ficam atrás de "Mais ações".
  const [moreActions, setMoreActions] = useState(false);
  const moreToggle = useRef<HTMLButtonElement>(null);
  const moreGroup = useRef<HTMLDivElement>(null);
  usePanelFocus(moreActions, moreGroup, moreToggle, () => setMoreActions(false));
  const open = (next: typeof panel): void => {
    setPanel(next);
    setMoreActions(false);
  };

  // O formulário abre abaixo dos botões: no celular, fora da tela. Leva a
  // tela até ele e põe o cursor no primeiro campo, para ninguém tocar num
  // botão e achar que nada aconteceu.
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    if (panel === "none") return;
    const form = Array.from(section.current?.querySelectorAll("form") ?? []).find(
      (candidate) => !candidate.closest(".production-history"),
    );
    if (!form) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    form.scrollIntoView?.({ behavior: still ? "auto" : "smooth", block: "nearest" });
    form.querySelector<HTMLElement>("input:not([type=hidden]), select, textarea")?.focus({ preventScroll: true });
  }, [panel]);
  const merged = Boolean(animal.merged_into_id);
  const del = daysInMilk(animal.ultimo_parto, today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [brinco, setBrinco] = useState("");
  const [evidence, setEvidence] = useState("");
  const [lote, setLote] = useState("");
  const [validFrom, setValidFrom] = useState(today);
  const [exitedOn, setExitedOn] = useState(today);
  const [exitReason, setExitReason] = useState<ExitReason>("venda");
  const [exitNotes, setExitNotes] = useState("");
  const [undoReason, setUndoReason] = useState("");
  const exited = Boolean(animal.exited_on);
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

  function submitUnlinkBrinco(): void {
    if (!evidence.trim()) {
      // Tirar o brinco muda a identidade do animal, como vincular.
      setError("Informe a evidência que sustenta tirar o brinco.");
      return;
    }
    void guard(() => onUnlinkBrinco(token, animal.id, evidence.trim()));
  }

  function submitLot(): void {
    if (!lote.trim()) {
      setError("Informe o lote.");
      return;
    }
    void guard(() => onAssignLot(token, animal.id, lote.trim(), validFrom));
  }

  function submitExit(): void {
    void guard(() =>
      onExit(token, animal.id, exitedOn, exitReason, exitNotes.trim() || null),
    );
  }

  function submitUndo(): void {
    if (undoReason.trim().length < 3) {
      setError("Explique em poucas palavras por que desfazer a baixa.");
      return;
    }
    void guard(() => onUndoExit(token, animal.id, undoReason.trim()));
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
    <section className="animal-detail" ref={section}>
      {/* O brinco uma vez só, no selo ao lado do nome — é como a vaca aparece
          em todas as listas. Embaixo, só o que o selo não diz. */}
      <header className="detail-head">
        <span className={animal.brinco ? "tag tag-lg" : "tag tag-lg none"}>
          {animal.brinco ? (
            <>
              <span className="sr-only">Brinco </span>
              {animal.brinco}
            </>
          ) : (
            "sem brinco"
          )}
        </span>
        <div>
          <h2>{animal.name ?? "Animal sem nome"}</h2>
          {(() => {
            // O número antigo só diz algo quando é outro.
            const legado =
              animal.numero_legado && animal.numero_legado !== animal.brinco
                ? `nº antigo ${animal.numero_legado}`
                : null;
            const ilegivel =
              !animal.brinco && animal.brinco_origem
                ? `leitura ilegível registrada: ${animal.brinco_origem}`
                : null;
            const extra = [ilegivel, legado].filter(Boolean).join(" · ");
            return extra ? <p className="brinco">{extra}</p> : null;
          })()}
        </div>
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
          <dd>
            {br(animal.ultimo_parto)}
            {animal.situacao === "Em lactação" && del !== null && (
              <small>{del} dias em lactação</small>
            )}
          </dd>
        </div>
      </dl>

      {merged && (
        <div className="exit-banner merged-banner">
          <strong>Ficha juntada a outra em {br(animal.merged_at?.slice(0, 10) ?? null)}</strong>
          <span>
            As produções dela foram relançadas na ficha que ficou. Esta fica arquivada, só para
            consulta.
          </span>
          {onOpenAnimal && animal.merged_into_id && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => onOpenAnimal(animal.merged_into_id as string)}
            >
              Abrir a ficha que ficou
            </button>
          )}
        </div>
      )}

      {exited && !merged && (
        <div className="exit-banner">
          <strong>
            Baixa em {br(animal.exited_on ?? null)} —{" "}
            {animal.exit_reason ? EXIT_REASON_LABEL[animal.exit_reason] : "motivo não informado"}
          </strong>
          {animal.exit_notes && <span>{animal.exit_notes}</span>}
          <small>Fora do rebanho: não entra no painel nem recebe produção.</small>
        </div>
      )}

      {!animal.brinco && !exited && !merged && (
        <p className="warning">
          Este animal não recebe medição automática enquanto não tiver brinco.
        </p>
      )}

      {canEdit && exited && !merged && (
        <div className="actions">
          <button type="button" className="secondary" onClick={() => open("desfazer")}>
            Desfazer baixa
          </button>
          <button type="button" className="secondary" onClick={() => open("juntar")}>
            <Icons.juntar /> Juntar com outra ficha
          </button>
        </div>
      )}

      {canEdit && !exited && !merged && (
        <>
          {/* À vista, o que se faz toda semana; em "Mais ações", o que é raro
              ou não tem volta fácil. Nenhuma em verde cheio: o verde é do
              "Salvar" do formulário que cada uma abre. */}
          <div className="actions">
            <button type="button" className="secondary" onClick={() => open("lote")}>
              <Icons.lote /> Mudar de lote
            </button>
            <button type="button" className="secondary" onClick={() => open("brinco")}>
              <Icons.brinco /> {animal.brinco ? "Trocar brinco" : "Vincular brinco"}
            </button>
            <button type="button" className="secondary" onClick={() => open("cadastro")}>
              <Icons.editar /> Editar cadastro
            </button>
            <button
              type="button"
              className="secondary actions-toggle"
              ref={moreToggle}
              aria-expanded={moreActions}
              aria-controls="ficha-mais-acoes"
              onClick={() => setMoreActions((current) => !current)}
            >
              <Icons.menu /> Mais ações
            </button>
          </div>
          {moreActions && (
            <div
              className="actions actions-more"
              id="ficha-mais-acoes"
              role="group"
              aria-label="Mais ações"
              ref={moreGroup}
            >
              {animal.brinco && (
                <button type="button" className="secondary" onClick={() => open("tirar-brinco")}>
                  Tirar o brinco
                </button>
              )}
              <button type="button" className="secondary" onClick={() => open("juntar")}>
                <Icons.juntar /> Juntar com outra ficha
              </button>
              <button type="button" className="secondary danger" onClick={() => open("baixa")}>
                Dar baixa
              </button>
            </div>
          )}
        </>
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

      {panel === "tirar-brinco" && canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitUnlinkBrinco();
          }}
        >
          <h3>Tirar o brinco</h3>
          <p className="hint">
            Para brinco que caiu da orelha ou que estava na vaca errada. O número {animal.brinco}{" "}
            fica livre, e esta vaca deixa de receber leitura automática até ganhar outro.
          </p>
          <label htmlFor="evidencia-tirar">Evidência</label>
          <input
            id="evidencia-tirar"
            value={evidence}
            onChange={(event) => setEvidence(event.target.value)}
            placeholder="Ex.: o 649 é da BRANQUINHA; esta será conferida no curral"
            autoComplete="off"
          />
          <button type="submit" className="danger" disabled={busy}>
            Confirmar e tirar o brinco
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

      {panel === "baixa" && canEdit && !exited && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitExit();
          }}
        >
          <h3>Dar baixa</h3>
          <label htmlFor="exit-reason">Motivo da baixa</label>
          <select
            id="exit-reason"
            value={exitReason}
            onChange={(event) => setExitReason(event.target.value as ExitReason)}
          >
            {(Object.keys(EXIT_REASON_LABEL) as ExitReason[]).map((reason) => (
              <option key={reason} value={reason}>
                {EXIT_REASON_LABEL[reason]}
              </option>
            ))}
          </select>
          <label htmlFor="exit-date">Data</label>
          <input
            id="exit-date"
            type="date"
            value={exitedOn}
            max={today}
            onChange={(event) => setExitedOn(event.target.value)}
          />
          <label htmlFor="exit-notes">Observação (opcional)</label>
          <input
            id="exit-notes"
            value={exitNotes}
            onChange={(event) => setExitNotes(event.target.value)}
            placeholder="Ex.: vendida para a fazenda vizinha"
            autoComplete="off"
          />
          <p className="hint">
            O animal sai do lote e do painel nesta data. A produção já lançada fica
            guardada, e a baixa pode ser desfeita se foi engano.
          </p>
          <button type="submit" disabled={busy}>
            Confirmar baixa
          </button>
        </form>
      )}

      {panel === "desfazer" && canEdit && exited && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitUndo();
          }}
        >
          <h3>Desfazer baixa</h3>
          <label htmlFor="undo-reason">Por que desfazer?</label>
          <input
            id="undo-reason"
            value={undoReason}
            onChange={(event) => setUndoReason(event.target.value)}
            placeholder="Ex.: baixa lançada na vaca errada"
            autoComplete="off"
          />
          <p className="hint">
            O animal volta ao rebanho sem lote: coloque-o no lote certo em seguida.
          </p>
          <button type="submit" disabled={busy}>
            Confirmar e trazer de volta
          </button>
        </form>
      )}

      {panel === "juntar" && canEdit && !merged && (
        <MergeFichas
          token={token}
          animal={animal}
          onSearch={onSearch}
          onPreview={onPreviewMerge}
          onMerge={onMerge}
          onCancel={() => setPanel("none")}
          onMerged={(keepId) => {
            setPanel("none");
            if (onOpenAnimal) onOpenAnimal(keepId);
            else onChanged();
          }}
        />
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

      <ProductionHistory
        token={token}
        animalId={animal.id}
        canEdit={canEdit}
        onLoad={onLoadProduction}
        onCorrect={onCorrect}
        onVoid={onVoid}
      />

      {(animal.fichas_juntadas ?? []).length > 0 && (
        <>
          <h3>Fichas juntadas a esta</h3>
          <ul className="merged-list">
            {(animal.fichas_juntadas ?? []).map((ficha) => (
              <li key={ficha.id}>
                <span>
                  {ficha.name ?? "sem nome"}
                  {ficha.numero_legado ? ` · nº antigo ${ficha.numero_legado}` : ""}
                </span>
                <small>juntada em {br(ficha.merged_at?.slice(0, 10) ?? null)}</small>
                {onOpenAnimal && (
                  <button type="button" className="link-btn" onClick={() => onOpenAnimal(ficha.id)}>
                    Ver a ficha arquivada
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
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
