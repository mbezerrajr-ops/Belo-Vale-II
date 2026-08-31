import type { ExistingMeasurement } from "../../api/types";

interface ReplacementWarningProps {
  existingMeasurement: ExistingMeasurement;
  reason: string;
  onReasonChange: (reason: string) => void;
}

export function ReplacementWarning({
  existingMeasurement,
  reason,
  onReasonChange,
}: ReplacementWarningProps): JSX.Element {
  const reasonFieldId = `replacement-reason-${existingMeasurement.id}`;

  return (
    <div role="alert" className="replacement-warning">
      <p>
        Uma medição oficial ativa de {existingMeasurement.measured_on} já
        existe para este animal e será substituída por esta aprovação.
      </p>
      <label htmlFor={reasonFieldId}>Motivo da substituição</label>
      <textarea
        id={reasonFieldId}
        required
        value={reason}
        onChange={(event) => onReasonChange(event.target.value)}
      />
    </div>
  );
}
