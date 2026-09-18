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
  /** Verdadeiro depois de uma redefinição feita pelo administrador. */
  must_change_password?: boolean;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  /** Enquanto verdadeiro, a conta só alcança a troca de senha. */
  must_change_password?: boolean;
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
  milk_price_per_liter?: number | null;
}

export type LotKind = "diet" | "management";

export interface LotAssignment {
  lote: string;
  /** `diet` = lote de ordenha; `management` = área ou categoria da fazenda. */
  kind: LotKind;
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
  /** Lote de ordenha. Nulo quando o animal não está em nenhum. */
  lote_atual: string | null;
  /** Área ou categoria em que o animal está (BEZERREIRO, ENGORDA…). */
  grupo_manejo: string | null;
  /** Baixa. Nulos enquanto o animal está no rebanho. */
  exited_on?: string | null;
  exit_reason?: ExitReason | null;
  exit_notes?: string | null;
}

export type ExitReason = "venda" | "morte" | "descarte" | "doacao" | "outro";

export const EXIT_REASON_LABEL: Record<ExitReason, string> = {
  venda: "Venda",
  morte: "Morte",
  descarte: "Descarte",
  doacao: "Doação",
  outro: "Outro motivo",
};

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
  /** Padrão do servidor: só quem está no rebanho. */
  rebanho?: "ativos" | "baixados" | "todos";
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
  /** Senha redefinida e ainda não trocada pelo dono da conta. */
  reset_pending?: boolean;
  created_at: string;
}

export interface PasswordReset {
  /** Aparece só nesta resposta: o servidor não guarda o valor. */
  temporary_password: string;
  expires_at: string;
}

export interface UserPage {
  items: UserAccount[];
  total: number;
}

// --- Painel do rebanho ---

export interface LotSummary {
  lote: string;
  animals: number;
  production: number;
  feed_cost: number;
  revenue: number | null;
  profit: number | null;
  cost_per_animal: number;
  production_per_animal: number;
  cost_ratio: number;
}

export interface SupplyBreakdown {
  name: string;
  price_per_kg: number;
  total_cost: number;
  cost_by_lot: Record<string, number>;
}

export interface Producer {
  animal_id: string;
  brinco: string | null;
  name: string | null;
  lote: string | null;
  production: number;
}

export interface ProductionPoint {
  measured_on: string;
  liters: number;
  animals: number;
}

export interface DashboardSummary {
  measured_on: string | null;
  available_dates: string[];
  production_by_date: ProductionPoint[];
  milk_price: number | null;
  total_animals: number;
  animals_without_lot: number;
  animals_with_reading: number;
  by_situation: Record<string, number>;
  by_status: Record<string, number>;
  by_management_group: Record<string, number>;
  lactation_stages: Record<string, number>;
  lots: LotSummary[];
  feed_breakdown: SupplyBreakdown[];
  top_producers: Producer[];
  bottom_producers: Producer[];
  total_production: number;
  total_feed_cost: number;
  total_revenue: number | null;
  total_profit: number | null;
}

export interface DashboardFilters {
  measuredOn?: string;
  lote?: string;
  situacao?: string;
}

export interface SupplyDiet {
  lote: string;
  kg_per_day: number;
}

export interface Supply {
  id: string;
  name: string;
  price_per_kg: number;
  legacy_id: string | null;
  diets: SupplyDiet[];
}

// --- Lançamento de produção ---

export interface Reading {
  id: string;
  animal_id: string;
  measured_on: string;
  producao: number | null;
  provenance: string;
  entered_by: string | null;
  supersedes: string | null;
  created_at: string;
}

export interface SheetItem {
  animal_id: string;
  brinco: string | null;
  name: string | null;
  situacao: string | null;
  producao: number | null;
  measurement_id: string | null;
  provenance: string | null;
}

export interface ProductionSheet {
  measured_on: string;
  /** Nulo quando a chamada pediu só a lista de lotes. */
  lote: string | null;
  lotes: string[];
  items: SheetItem[];
}

/** Corpo do 409: já existe outro valor lançado para a vaca nesta data. */
export interface ReadingConflict {
  message: string;
  existing: Reading;
}

// --- Importação de coleta por arquivo ---

export type ImportMode = "new_only" | "replace";

export type ImportRowStatus =
  | "new"
  | "same"
  | "different"
  | "not_found"
  | "no_brinco"
  | "invalid"
  | "exited"
  | "duplicate";

export interface ImportPreviewRow {
  location: string;
  brinco_lido: string;
  brinco: string | null;
  nome_arquivo: string | null;
  producao: number;
  status: ImportRowStatus;
  animal_id: string | null;
  animal_nome: string | null;
  existing_measurement_id: string | null;
  existing_producao: number | null;
  existing_provenance: string | null;
  notes: string[];
}

export interface ImportProblem {
  location: string;
  text: string;
  reason: string;
}

export interface KeptReading {
  animal_id: string;
  brinco: string | null;
  nome: string | null;
  producao: number | null;
}

export interface ImportPreview {
  file_format: "csv" | "xlsx" | "pdf";
  filename: string;
  sha256: string;
  measured_on: string;
  counts: Record<ImportRowStatus, number>;
  rows: ImportPreviewRow[];
  problems: ImportProblem[];
  /** Leituras da data que não estão no arquivo: ficam como estão. */
  kept: KeptReading[];
}

export interface ImportSummary {
  created: number;
  replaced: number;
  skipped_same: number;
  skipped_different: number;
  not_found: number;
  no_brinco: number;
  invalid: number;
  exited: number;
  duplicate: number;
  unreadable_lines: number;
  kept: number;
}

export interface ImportRecord {
  id: string;
  measured_on: string;
  filename: string;
  file_format: string;
  mode: ImportMode;
  reason: string | null;
  imported_by: string;
  created_at: string;
  summary: ImportSummary;
  /** O mesmo arquivo já tinha sido importado nesta data e modo. */
  already_imported: boolean;
}

// --- Histórico e consulta ---

export type MeasurementStatus = "active" | "superseded" | "voided";

export type Provenance =
  | "manual_entry"
  | "file_import"
  | "legacy_baseline"
  | "ocr_review"
  | "proposal_review";

export interface ProductionHistoryEntry {
  id: string;
  measured_on: string;
  producao: number | null;
  status: MeasurementStatus;
  provenance: Provenance;
  /** Quem lançou, importou ou aprovou. */
  responsible: string | null;
  created_at: string;
  /** Leitura que esta substituiu, quando é uma correção ou substituição. */
  supersedes: string | null;
  /** Arquivo de origem, para leituras importadas. */
  source: string | null;
  /** Motivo da correção, anulação ou substituição. */
  reason: string | null;
  lote_observado: string | null;
}

export interface SupplyPrice {
  effective_on: string;
  price_per_kg: number;
  source: string;
  recorded_by: string | null;
}

export interface Features {
  /** Leitura de fichas por foto: só com OCR real (ou demonstração). */
  photo_sheets: boolean;
}

// --- Propostas de eventos (caixa de revisão) ---

export type EventType = "production" | "calving" | "dry_off" | "exit" | "lot_change" | "note";

export type ProposalStatus = "pending" | "approved" | "rejected";

export interface AnimalSummary {
  id: string;
  brinco: string | null;
  name: string | null;
  situacao: string | null;
  lote_atual: string | null;
  grupo_manejo: string | null;
  exited_on: string | null;
}

export interface ProposalAlert {
  code: string;
  message: string;
  field?: string;
}

export interface Proposal {
  id: string;
  source: {
    id: string;
    kind: "photo" | "audio" | "text";
    label: string;
    reference_date: string | null;
    extractor_name: string;
    created_at: string;
  };
  position: number;
  event_type: EventType;
  brinco_lido: string | null;
  nome_lido: string | null;
  /** Encontrado pelo brinco. Nunca pelo nome. */
  candidate: AnimalSummary | null;
  /** Só sugestões, pelo nome lido: quem revisa escolhe. */
  name_suggestions: AnimalSummary[];
  payload: Record<string, string | number | null>;
  raw_fields: Record<string, string | null>;
  evidence: { text?: string; [key: string]: unknown };
  confidence: Record<string, number>;
  alerts: ProposalAlert[];
  status: ProposalStatus;
  version: number;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  applied_payload: Record<string, string | number | null> | null;
  result: Record<string, unknown> | null;
}

export interface ApproveProposalInput {
  expected_version: number;
  animal_id: string;
  payload: Record<string, string | number | null>;
  replace_reason: string | null;
}
