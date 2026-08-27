export type AlertSeverity = "info" | "warning" | "error";

export interface ReviewAlert {
  code: string;
  severity: AlertSeverity;
  message: string;
  details: Record<string, unknown>;
}

export interface ExistingMeasurement {
  id: string;
  measured_on: string;
  values: Record<string, unknown>;
}

export interface ReviewLine {
  id: string;
  line_number: number;
  version: number;
  raw_values: Record<string, unknown>;
  normalized_values: Record<string, unknown> | null;
  confidence: number | null;
  candidate_animal_id: string | null;
  crop_url: string | null;
  alerts: ReviewAlert[];
  existing_measurement: ExistingMeasurement | null;
}

export interface ImportReview {
  import_id: string;
  status: string;
  declared_lot: string | null;
  declared_measured_on: string | null;
  lines: ReviewLine[];
}

export interface UploadResult {
  id: string;
  status: string;
}

export type DecisionAction = "approve" | "reject";

export interface DecisionRequest {
  action: DecisionAction;
  corrected_values?: Record<string, unknown> | null;
  reason?: string | null;
  expected_version: number;
}

export interface DecisionResult {
  line_id: string;
  version: number;
  measurement_id: string | null;
  measurement_status: string | null;
}

export interface ApiErrorBody {
  code: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.code);
    this.status = status;
    this.code = body.code;
    this.body = body;
  }
}
