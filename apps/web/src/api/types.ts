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

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
}

export interface MeasurementRecord {
  id: string;
  animal_id: string;
  animal_identifier: string;
  animal_name: string | null;
  measured_on: string;
  values: Record<string, unknown>;
  reviewed_by: string | null;
  created_at: string;
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

// --- Cadastro mestre ---

export interface Farm {
  id: string;
  name: string;
  code: string | null;
}

export interface LotAssignment {
  lote: string;
  valid_from: string;
  valid_to: string | null;
  source: string;
  reviewed_by: string | null;
}

export interface Animal {
  id: string;
  farm_id: string;
  brinco: string | null;
  brinco_origem: string | null;
  legacy_id: string | null;
  numero_legado: string | null;
  name: string | null;
  situacao: string | null;
  status: string | null;
  ultimo_parto: string | null;
  nascimento: string | null;
  peso: number | null;
  observacoes: string | null;
  lote_atual: string | null;
}

export interface AnimalDetail extends Animal {
  historico_lotes: LotAssignment[];
}

export interface AnimalPage {
  items: Animal[];
  total: number;
  limit: number;
  offset: number;
}

export interface AnimalSearch {
  brinco?: string;
  name?: string;
  semBrinco?: boolean;
  limit?: number;
  offset?: number;
}

export interface AnimalCreateInput {
  brinco?: string | null;
  name?: string | null;
  numero_legado?: string | null;
  situacao?: string | null;
  status?: string | null;
  ultimo_parto?: string | null;
  lote?: string | null;
  lote_valid_from?: string | null;
}

export type AnimalUpdateInput = Partial<{
  name: string | null;
  situacao: string | null;
  status: string | null;
  ultimo_parto: string | null;
  numero_legado: string | null;
  observacoes: string | null;
}>;

// --- Contas ---

export type Role = "operator" | "reviewer" | "admin";

export interface UserAccount {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface UserPage {
  items: UserAccount[];
  total: number;
}
