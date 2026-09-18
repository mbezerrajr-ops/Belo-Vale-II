import { useState } from "react";

import { decideLine as decideLineRequest } from "../../api/client";
import type {
  DecisionResult,
  ImportReview,
  ReviewAlert,
  ReviewLine,
} from "../../api/types";
import { ReplacementWarning } from "./ReplacementWarning";

export type DecideFn = (
  lineId: string,
  action: "approve" | "reject",
  correctedValues: Record<string, unknown> | null,
  reason: string,
  expectedVersion: number,
) => Promise<DecisionResult>;

interface ReviewWorkspaceProps {
  review: ImportReview;
  token?: string;
  decide?: DecideFn;
  onDecided?: (lineId: string, result: DecisionResult) => void;
}

function defaultDecide(token: string): DecideFn {
  return (lineId, action, correctedValues, reason, expectedVersion) =>
    decideLineRequest(
      lineId,
      {
        action,
        corrected_values: correctedValues,
        reason: reason || null,
        expected_version: expectedVersion,
      },
      token,
    );
}

const FIELD_LABEL: Record<string, string> = {
  animal_brinco: "Brinco",
  animal_number: "Número",
  animal_name: "Nome lido",
  morning: "Manhã",
  afternoon: "Tarde",
  total: "Total",
  measured_on: "Data",
  lot: "Lote",
  notes: "Obs.",
};

export function ReviewWorkspace({
  review,
  token,
  decide,
  onDecided,
}: ReviewWorkspaceProps): JSX.Element {
  const decideFn = decide ?? defaultDecide(token ?? "");

  return (
    <section aria-label="Revisão de importação">
      <header className="row-between">
        <div>
          <h2>Conferência da ficha</h2>
          <p className="muted">
            Importação {review.import_id.slice(0, 8)} · {review.status}
          </p>
        </div>
        {review.declared_lot === null && review.declared_measured_on === null ? null : (
          <span className="role-pill">
            Declarado: lote {review.declared_lot ?? "—"}, data{" "}
            {review.declared_measured_on ?? "—"}
          </span>
        )}
      </header>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {review.lines.map((line) => (
          <li key={line.id}>
            <ReviewLineCard line={line} decide={decideFn} onDecided={onDecided} />
          </li>
        ))}
      </ul>
    </section>
  );
}

type LineMode = "idle" | "confirming-approval" | "submitting";

interface ReviewLineCardProps {
  line: ReviewLine;
  decide: DecideFn;
  onDecided?: (lineId: string, result: DecisionResult) => void;
}

function ReviewLineCard({
  line,
  decide,
  onDecided,
}: ReviewLineCardProps): JSX.Element {
  const [mode, setMode] = useState<LineMode>("idle");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const requiresReplacementReason = line.existing_measurement !== null;
  const canConfirmApproval = !requiresReplacementReason || reason.trim() !== "";

  const handleStartApproval = (): void => {
    setMode("confirming-approval");
  };

  const handleConfirmApproval = async (): Promise<void> => {
    setMode("submitting");
    setError(null);
    try {
      const result = await decide(line.id, "approve", null, reason, line.version);
      onDecided?.(line.id, result);
    } catch {
      setError("Não foi possível registrar a aprovação. Tente novamente.");
      setMode("confirming-approval");
    }
  };

  const handleReject = async (): Promise<void> => {
    setMode("submitting");
    setError(null);
    try {
      const result = await decide(line.id, "reject", null, reason, line.version);
      onDecided?.(line.id, result);
    } catch {
      setError("Não foi possível registrar a rejeição. Tente novamente.");
      setMode("idle");
    }
  };

  return (
    <article className="review-line" aria-label={`Linha ${line.line_number}`}>
      <div className="row-between">
        <strong>Linha {line.line_number}</strong>
        {line.candidate_animal_id === null ? (
          <span className="tag none">sem animal</span>
        ) : (
          <span className="tag">animal encontrado</span>
        )}
      </div>
      {line.crop_url === null ? null : (
        <img src={line.crop_url} alt={`Recorte da linha ${line.line_number}`} />
      )}
      <NormalizedValuesTable line={line} />
      <AlertList alerts={line.alerts} />

      {mode === "confirming-approval" && line.existing_measurement !== null ? (
        <ReplacementWarning
          existingMeasurement={line.existing_measurement}
          reason={reason}
          onReasonChange={setReason}
        />
      ) : null}

      {mode === "idle" ? (
        <div className="row">
          <button type="button" onClick={handleStartApproval}>
            Aprovar
          </button>
          <button type="button" className="btn-danger" onClick={handleReject}>
            Rejeitar
          </button>
        </div>
      ) : null}

      {mode === "confirming-approval" ? (
        <div className="row">
          <button
            type="button"
            onClick={handleConfirmApproval}
            disabled={!canConfirmApproval}
          >
            Confirmar aprovação
          </button>
          <button type="button" className="btn-ghost" onClick={() => setMode("idle")}>
            Cancelar
          </button>
        </div>
      ) : null}

      {error === null ? null : <p role="alert">{error}</p>}
    </article>
  );
}

function NormalizedValuesTable({ line }: { line: ReviewLine }): JSX.Element {
  const entries = Object.entries(line.normalized_values ?? {});
  return (
    <dl>
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{FIELD_LABEL[key] ?? key}</dt>
          <dd>{value === null ? "—" : String(value)}</dd>
        </div>
      ))}
      {line.confidence === null ? null : (
        <div>
          <dt>Confiança</dt>
          <dd>{Math.round(line.confidence * 100)}%</dd>
        </div>
      )}
    </dl>
  );
}

function AlertList({ alerts }: { alerts: ReviewAlert[] }): JSX.Element | null {
  if (alerts.length === 0) {
    return null;
  }
  return (
    <ul>
      {alerts.map((alert) => (
        <li key={alert.code} data-severity={alert.severity}>
          {alert.message}
        </li>
      ))}
    </ul>
  );
}
