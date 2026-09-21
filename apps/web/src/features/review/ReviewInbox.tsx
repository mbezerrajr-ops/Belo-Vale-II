import { useEffect, useState } from "react";

import {
  approveProposal,
  listProposals,
  redateSource,
  rejectProposal,
  searchAnimals,
} from "../../api/client";
import {
  ApiError,
  EXIT_REASON_LABEL,
  type AnimalPage,
  type AnimalSearch,
  type AnimalSummary,
  type ApproveProposalInput,
  type EventType,
  type ExitReason,
  type Proposal,
  type ProposalStatus,
  type UploadResult,
} from "../../api/types";
import { SendPhoto } from "./SendPhoto";
import { SourceMedia } from "./SourceMedia";
import { brDate, liters } from "../../ui/dates";

/**
 * Caixa de revisão: cada evento lido de uma foto, áudio ou texto espera aqui
 * por uma pessoa.
 *
 * Quem revisa vê o que foi lido e de onde veio, confere o animal (achado só
 * pelo brinco; o nome lido vira sugestão), corrige o que precisar e decide.
 * A correção vai junto com a aprovação — o que foi lido continua guardado
 * como veio.
 */

type ListFn = (token: string, status: ProposalStatus) => Promise<Proposal[]>;
type ApproveFn = (
  token: string,
  proposalId: string,
  input: ApproveProposalInput,
) => Promise<unknown>;
type RejectFn = (
  token: string,
  proposalId: string,
  expectedVersion: number,
  reason: string,
) => Promise<void>;
type SearchFn = (token: string, search: AnimalSearch) => Promise<AnimalPage>;
type RedateFn = (
  token: string,
  sourceId: string,
  referenceDate: string,
) => Promise<{ updated: number; kept_decided: number }>;

interface Props {
  token: string;
  /** Resolvida no servidor; necessária para enviar foto. */
  farmId?: string;
  /** Revisor e administrador decidem; operador só vê. */
  canDecide: boolean;
  onList?: ListFn;
  onApprove?: ApproveFn;
  onReject?: RejectFn;
  onSearch?: SearchFn;
  onRedate?: RedateFn;
  onUpload?: UploadFn;
  onReprocess?: ReprocessFn;
  /** Busca o arquivo da leitura com o login; dublê nos testes. */
  onFetchMedia?: (url: string, token: string) => Promise<Blob>;
  /** Chamado depois de cada decisão, para atualizar contadores. */
  onChanged?: () => void;
}

type UploadFn = (
  input: { farmId: string; file: File; declaredLot?: string },
  token: string,
) => Promise<UploadResult>;
type ReprocessFn = (importId: string, token: string) => Promise<UploadResult>;

const EVENT_LABEL: Record<EventType, string> = {
  production: "Produção",
  calving: "Parto",
  dry_off: "Secagem",
  exit: "Baixa",
  lot_change: "Mudança de lote",
  note: "Observação",
};

const SOURCE_LABEL: Record<string, string> = {
  photo: "Foto",
  audio: "Áudio",
  text: "Texto",
};

const TABS: { status: ProposalStatus; label: string }[] = [
  { status: "pending", label: "Pendentes" },
  { status: "approved", label: "Aprovadas" },
  { status: "rejected", label: "Rejeitadas" },
];

/** Abaixo disto, a leitura merece atenção redobrada. */
const LOW_CONFIDENCE = 0.6;

interface FieldSpec {
  key: string;
  label: string;
  kind: "date" | "liters" | "text" | "textarea" | "reason";
}

const FIELDS: Record<EventType, FieldSpec[]> = {
  production: [
    { key: "measured_on", label: "Data da coleta", kind: "date" },
    { key: "producao", label: "Litros", kind: "liters" },
  ],
  calving: [{ key: "calved_on", label: "Data do parto", kind: "date" }],
  dry_off: [{ key: "dried_on", label: "Data da secagem", kind: "date" }],
  exit: [
    { key: "exited_on", label: "Data da baixa", kind: "date" },
    { key: "reason", label: "Motivo da baixa", kind: "reason" },
    { key: "notes", label: "Observação", kind: "text" },
  ],
  lot_change: [
    { key: "lote", label: "Lote ou área", kind: "text" },
    { key: "valid_from", label: "A partir de", kind: "date" },
  ],
  note: [{ key: "text", label: "Observação", kind: "textarea" }],
};

function toInput(spec: FieldSpec, value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (spec.kind === "liters" && typeof value === "number") return liters(value);
  return String(value);
}

function toPayloadValue(spec: FieldSpec, text: string): string | number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (spec.kind === "liters") {
    const value = Number(trimmed.replace(",", "."));
    return Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
  }
  return trimmed;
}

/** Valor como a pessoa lê: data dd/mm/aaaa, litros com vírgula, motivo por extenso. */
function display(spec: FieldSpec, value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (spec.kind === "date") return brDate(String(value));
  if (spec.kind === "liters" && typeof value === "number") return `${liters(value)} L`;
  if (spec.kind === "reason") return EXIT_REASON_LABEL[value as ExitReason] ?? String(value);
  return String(value);
}

function detailOf(error: unknown): unknown {
  return error instanceof ApiError ? (error.body as { detail?: unknown }).detail : undefined;
}

function errorMessage(error: unknown): string {
  const detail = detailOf(error);
  if (typeof detail === "string") return detail;
  if (error instanceof TypeError) return "Sem conexão. Tente de novo quando o sinal voltar.";
  return "Não foi possível completar a decisão.";
}

interface Existing {
  producao: number | null;
  entered_by: string | null;
}

function isExisting(detail: unknown): detail is { message: string; existing: Existing } {
  return typeof detail === "object" && detail !== null && "existing" in detail;
}

function AnimalLine({ animal }: { animal: AnimalSummary }): JSX.Element {
  return (
    <span className="proposal-animal">
      <span className={animal.brinco ? "tag" : "tag none"}>{animal.brinco ?? "sem brinco"}</span>
      <strong>{animal.name ?? "sem nome"}</strong>
      <small>
        {animal.exited_on
          ? `baixa em ${brDate(animal.exited_on)}`
          : (animal.lote_atual ?? (animal.grupo_manejo ? `em ${animal.grupo_manejo}` : "sem lote"))}
      </small>
    </span>
  );
}

function ProposalCard({
  proposal,
  token,
  canDecide,
  onApprove,
  onReject,
  onSearch,
  onDone,
}: {
  proposal: Proposal;
  token: string;
  canDecide: boolean;
  onApprove: ApproveFn;
  onReject: RejectFn;
  onSearch: SearchFn;
  onDone: () => void;
}): JSX.Element {
  const specs = FIELDS[proposal.event_type];
  const [animal, setAnimal] = useState<AnimalSummary | null>(proposal.candidate);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(specs.map((spec) => [spec.key, toInput(spec, proposal.payload[spec.key])])),
  );
  const [mode, setMode] = useState<"idle" | "rejecting" | "replacing">("idle");
  const [rejectReason, setRejectReason] = useState("");
  const [replaceReason, setReplaceReason] = useState("");
  const [existing, setExisting] = useState<Existing | null>(null);
  const [term, setTerm] = useState("");
  const [found, setFound] = useState<AnimalSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lowConfidence = Object.values(proposal.confidence).some((c) => c < LOW_CONFIDENCE);
  const idPrefix = `proposal-${proposal.id}`;

  async function search(): Promise<void> {
    if (!term.trim()) return;
    setError(null);
    try {
      const page = await onSearch(token, { brinco: term.trim() });
      setFound(
        page.items.map((item) => ({
          id: item.id,
          brinco: item.brinco,
          name: item.name,
          situacao: item.situacao,
          lote_atual: item.lote_atual,
          grupo_manejo: item.grupo_manejo,
          exited_on: item.exited_on ?? null,
        })),
      );
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function approve(): Promise<void> {
    if (animal === null) return;
    setBusy(true);
    setError(null);
    try {
      await onApprove(token, proposal.id, {
        expected_version: proposal.version,
        animal_id: animal.id,
        payload: Object.fromEntries(
          specs.map((spec) => [spec.key, toPayloadValue(spec, values[spec.key] ?? "")]),
        ),
        replace_reason: mode === "replacing" ? replaceReason.trim() : null,
      });
      onDone();
    } catch (caught) {
      const detail = detailOf(caught);
      if (isExisting(detail)) {
        setExisting(detail.existing);
        setMode("replacing");
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  async function reject(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onReject(token, proposal.id, proposal.version, rejectReason.trim());
      onDone();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const readText = [
    proposal.brinco_lido ? `brinco ${proposal.brinco_lido}` : null,
    proposal.nome_lido ? `nome ${proposal.nome_lido}` : null,
    // Folha de pesagem: manhã + tarde, para conferir o total lido.
    proposal.raw_fields.parcelas ? `ordenhas ${proposal.raw_fields.parcelas}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <article
      className="proposal-card"
      aria-label={`${EVENT_LABEL[proposal.event_type]} — ${proposal.brinco_lido ?? proposal.nome_lido ?? "sem identificação"}`}
    >
      <header className="proposal-head">
        <span className="pill">{EVENT_LABEL[proposal.event_type]}</span>
        {lowConfidence && <span className="pill tone-warn">confiança baixa</span>}
      </header>

      {proposal.evidence.text && (
        <blockquote className="proposal-evidence">
          <small>Lido</small>
          <span>{proposal.evidence.text}</span>
        </blockquote>
      )}
      {readText && <p className="hint">{readText}</p>}

      <div className="proposal-animal-box">
        {animal !== null ? (
          <>
            <AnimalLine animal={animal} />
            {canDecide && (
              <button type="button" className="link-btn" onClick={() => setAnimal(null)}>
                Trocar animal
              </button>
            )}
            {/* Brinco de uma vaca, nome de outra: o brinco pode ter vindo da
                linha vizinha. As vacas do nome lido ficam a um toque. */}
            {canDecide &&
              proposal.name_suggestions
                .filter((option) => option.id !== animal.id)
                .map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="secondary suggestion"
                    onClick={() => setAnimal(option)}
                  >
                    Ou é esta: {option.brinco ?? "sem brinco"} · {option.name ?? "sem nome"}
                  </button>
                ))}
          </>
        ) : (
          <>
            <p className="proposal-missing">Animal não definido. A associação é só pelo brinco.</p>
            {[...proposal.name_suggestions, ...(found ?? [])].map((option) => (
              <button
                key={option.id}
                type="button"
                className="secondary suggestion"
                disabled={!canDecide}
                onClick={() => setAnimal(option)}
              >
                É esta: {option.brinco ?? "sem brinco"} · {option.name ?? "sem nome"}
              </button>
            ))}
            {found !== null && found.length === 0 && (
              <p className="hint">Nenhum animal com esse brinco.</p>
            )}
            {canDecide && (
              <div className="proposal-search">
                <label htmlFor={`${idPrefix}-search`}>Buscar pelo brinco</label>
                <input
                  id={`${idPrefix}-search`}
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
                <button type="button" className="secondary" onClick={() => void search()}>
                  Buscar
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <div className="proposal-fields">
        {specs.map((spec) => {
          const id = `${idPrefix}-${spec.key}`;
          const common = {
            id,
            value: values[spec.key] ?? "",
            disabled: !canDecide,
            onChange: (
              event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
            ) => setValues((current) => ({ ...current, [spec.key]: event.target.value })),
          };
          return (
            <div key={spec.key}>
              <label htmlFor={id}>{spec.label}</label>
              {spec.kind === "reason" ? (
                <select {...common}>
                  <option value="">—</option>
                  {(Object.keys(EXIT_REASON_LABEL) as ExitReason[]).map((reason) => (
                    <option key={reason} value={reason}>
                      {EXIT_REASON_LABEL[reason]}
                    </option>
                  ))}
                </select>
              ) : spec.kind === "textarea" ? (
                <textarea rows={2} {...common} />
              ) : (
                <input
                  type={spec.kind === "date" ? "date" : "text"}
                  inputMode={spec.kind === "liters" ? "decimal" : undefined}
                  autoComplete="off"
                  {...common}
                />
              )}
            </div>
          );
        })}
      </div>

      {proposal.alerts.length > 0 && (
        <ul className="proposal-alerts">
          {proposal.alerts.map((alert, index) => (
            <li key={`${alert.code}-${index}`}>{alert.message}</li>
          ))}
        </ul>
      )}

      {error && <p role="alert">{error}</p>}

      {canDecide && mode === "replacing" && existing && (
        <div className="row-fix">
          <p>
            Já lançado: {existing.producao === null ? "—" : liters(existing.producao)} L
            {existing.entered_by ? ` por ${existing.entered_by}` : ""}.
          </p>
          <label htmlFor={`${idPrefix}-replace`}>Motivo para substituir</label>
          <input
            id={`${idPrefix}-replace`}
            value={replaceReason}
            onChange={(event) => setReplaceReason(event.target.value)}
            placeholder="Ex.: o caderno confere com o tanque"
            autoComplete="off"
          />
        </div>
      )}

      {canDecide && mode === "rejecting" && (
        <div className="row-fix">
          <label htmlFor={`${idPrefix}-reject`}>Motivo da rejeição</label>
          <input
            id={`${idPrefix}-reject`}
            value={rejectReason}
            onChange={(event) => setRejectReason(event.target.value)}
            placeholder="Ex.: leitura de um rabisco"
            autoComplete="off"
          />
        </div>
      )}

      {canDecide && (
        <div className="row-fix-actions">
          {mode === "rejecting" ? (
            <>
              <button
                type="button"
                className="danger"
                disabled={busy || rejectReason.trim().length < 3}
                onClick={() => void reject()}
              >
                Confirmar rejeição
              </button>
              <button type="button" className="secondary" onClick={() => setMode("idle")}>
                Cancelar
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                disabled={
                  busy ||
                  animal === null ||
                  (mode === "replacing" && replaceReason.trim().length < 3)
                }
                onClick={() => void approve()}
              >
                {mode === "replacing" ? "Substituir e aprovar" : "Aprovar"}
              </button>
              <button type="button" className="secondary" onClick={() => setMode("rejecting")}>
                Rejeitar
              </button>
            </>
          )}
        </div>
      )}
    </article>
  );
}

function DecidedItem({ proposal }: { proposal: Proposal }): JSX.Element {
  const when = proposal.decided_at
    ? new Date(proposal.decided_at).toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
  const shown = proposal.applied_payload ?? proposal.payload;
  return (
    <li className="decided-item">
      <span className="pill">{EVENT_LABEL[proposal.event_type]}</span>
      <span>
        {proposal.candidate?.brinco ?? proposal.brinco_lido ?? "—"} ·{" "}
        {proposal.candidate?.name ?? proposal.nome_lido ?? "—"}
      </span>
      <small>
        {FIELDS[proposal.event_type]
          .filter((spec) => shown[spec.key] !== null && shown[spec.key] !== undefined && shown[spec.key] !== "")
          .map((spec) => `${spec.label}: ${display(spec, shown[spec.key])}`)
          .join(" · ")}
      </small>
      <small>
        {proposal.status === "approved" ? "Aprovada" : "Rejeitada"} por {proposal.decided_by ?? "—"}{" "}
        em {when}
        {proposal.decision_reason ? ` — ${proposal.decision_reason}` : ""}
      </small>
    </li>
  );
}

/**
 * Data do arquivo: a que vale para as propostas sem data própria. O leitor
 * erra o cabeçalho (25/08/2026 lido como 2024); trocar aqui vale para todas
 * as pendentes do arquivo de uma vez. A data lida continua registrada.
 */
function SourceDate({
  source,
  pending,
  token,
  canDecide,
  onRedate,
  onDone,
}: {
  source: Proposal["source"];
  pending: number;
  token: string;
  canDecide: boolean;
  onRedate: RedateFn;
  onDone: () => void;
}): JSX.Element | null {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(source.reference_date ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const corrected =
    source.corrected_by !== null && source.reference_date_read !== source.reference_date;
  const inputId = `source-date-${source.id}`;

  async function apply(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onRedate(token, source.id, value);
      setEditing(false);
      onDone();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!corrected && !canDecide) return null;
  return (
    <div className="source-date">
      {corrected && (
        <p className="hint">
          Data corrigida — lida como{" "}
          {source.reference_date_read ? brDate(source.reference_date_read) : "ilegível"}, corrigida
          por {source.corrected_by}.
        </p>
      )}
      {canDecide && !editing && (
        <button type="button" className="link-btn" onClick={() => setEditing(true)}>
          Trocar data do arquivo
        </button>
      )}
      {canDecide && editing && (
        <div className="source-date-form">
          <label htmlFor={inputId}>Nova data do arquivo</label>
          <input
            id={inputId}
            type="date"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <button type="button" disabled={!value || busy} onClick={() => void apply()}>
            Aplicar às {pending} {pending === 1 ? "pendente" : "pendentes"}
          </button>
          <button type="button" className="link-btn" onClick={() => setEditing(false)}>
            Cancelar
          </button>
          <small>Aprovadas e rejeitadas não mudam. Data escrita na própria linha também não.</small>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}

export function ReviewInbox({
  token,
  canDecide,
  onList = listProposals,
  onApprove = approveProposal,
  onReject = rejectProposal,
  onSearch = searchAnimals,
  onRedate = redateSource,
  onUpload,
  onReprocess,
  onFetchMedia,
  farmId,
  onChanged,
}: Props): JSX.Element {
  const [tab, setTab] = useState<ProposalStatus>("pending");
  // Filtro por arquivo: null = todos.
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [items, setItems] = useState<Proposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload(status: ProposalStatus = tab): Promise<void> {
    setError(null);
    try {
      setItems(await onList(token, status));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  useEffect(() => {
    setItems(null);
    void reload(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, tab]);

  // Um botão por arquivo, na ordem em que aparecem, com quantas propostas têm.
  const files: { id: string; label: string; count: number }[] = [];
  for (const item of items ?? []) {
    const file = files.find((entry) => entry.id === item.source.id);
    if (file) file.count += 1;
    else files.push({ id: item.source.id, label: item.source.label, count: 1 });
  }
  const selected = sourceId !== null && files.some((file) => file.id === sourceId) ? sourceId : null;
  const visible = (items ?? []).filter((item) => selected === null || item.source.id === selected);

  const groups: { source: Proposal["source"]; items: Proposal[] }[] = [];
  for (const item of visible) {
    const last = groups[groups.length - 1];
    if (last && last.source.id === item.source.id) last.items.push(item);
    else groups.push({ source: item.source, items: [item] });
  }

  const afterChange = (): void => {
    void reload("pending");
    onChanged?.();
  };

  return (
    <section className="review-inbox">
      <h2>Revisão</h2>
      <p className="muted">
        Cada evento lido de uma foto, áudio ou texto espera aqui. Nada entra no rebanho sem
        aprovação.
      </p>

      <div className="search-shortcuts" role="group" aria-label="Situação">
        {TABS.map((option) => (
          <button
            key={option.status}
            type="button"
            aria-pressed={tab === option.status}
            onClick={() => setTab(option.status)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* A leitura da foto termina em segundo plano: sem isto, quem enviou fica
          olhando uma tela parada, porque clicar na aba já escolhida não
          recarrega nada. */}
      <button type="button" className="link-btn refresh-inbox" onClick={() => void reload(tab)}>
        Atualizar
      </button>

      {farmId && (
        <SendPhoto
          token={token}
          farmId={farmId}
          onUpload={onUpload}
          onReprocess={onReprocess}
          onSent={() => void reload("pending")}
        />
      )}

      {files.length > 0 && (
        <div className="search-shortcuts file-filter" role="group" aria-label="Arquivos">
          <button type="button" aria-pressed={selected === null} onClick={() => setSourceId(null)}>
            Todos <span className="count">{items?.length ?? 0}</span>
          </button>
          {files.map((file) => (
            <button
              key={file.id}
              type="button"
              aria-pressed={selected === file.id}
              onClick={() => setSourceId(file.id)}
            >
              {file.label} <span className="count">{file.count}</span>
            </button>
          ))}
        </div>
      )}

      {!canDecide && tab === "pending" && (
        <p className="hint">Um revisor aprova estas propostas.</p>
      )}
      {error && <p role="alert">{error}</p>}
      {items === null && !error && <div className="skeleton" style={{ height: 160 }} />}

      {items !== null && items.length === 0 && (
        <p className="chart-empty">
          {tab === "pending"
            ? "Nada esperando revisão. Quando as leituras de fotos e áudios estiverem ligadas, cada evento lido aparece aqui."
            : "Nenhuma proposta nesta situação."}
        </p>
      )}

      {tab === "pending" &&
        groups.map((group) => (
          <div key={group.source.id} className="proposal-group">
            <h3>
              {group.source.label}
              <small>
                {SOURCE_LABEL[group.source.kind] ?? group.source.kind}
                {group.source.reference_date ? ` · ${brDate(group.source.reference_date)}` : ""} ·{" "}
                {group.items.length} {group.items.length === 1 ? "evento" : "eventos"}
              </small>
              {group.source.media_url && (
                <SourceMedia
                  url={group.source.media_url}
                  kind={group.source.kind}
                  token={token}
                  onFetch={onFetchMedia}
                />
              )}
            </h3>
            <SourceDate
              source={group.source}
              pending={group.items.length}
              token={token}
              canDecide={canDecide}
              onRedate={onRedate}
              onDone={afterChange}
            />
            {group.items.map((item) => (
              <ProposalCard
                key={`${item.id}-${item.version}`}
                proposal={item}
                token={token}
                canDecide={canDecide}
                onApprove={onApprove}
                onReject={onReject}
                onSearch={onSearch}
                onDone={afterChange}
              />
            ))}
          </div>
        ))}

      {tab !== "pending" && items !== null && items.length > 0 && (
        <ul className="decided-list">
          {visible.map((item) => (
            <DecidedItem key={item.id} proposal={item} />
          ))}
        </ul>
      )}
    </section>
  );
}
