import {
  ApiError,
  type Animal,
  type AnimalCreateInput,
  type AnimalDetail,
  type AnimalPage,
  type AnimalSearch,
  type AnimalUpdateInput,
  type CurrentUser,
  type Farm,
  type LotKind,
  type DashboardFilters,
  type DashboardSummary,
  type ExitReason,
  type ImportMode,
  type ImportPreview,
  type ImportRecord,
  type PasswordReset,
  type ProductionSheet,
  type Reading,
  type Role,
  type Supply,
  type UserAccount,
  type UserPage,
  type DecisionRequest,
  type DecisionResult,
  type ImportReview,
  type LoginResult,
  type MeasurementRecord,
  type UploadResult,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body as T;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export async function login(
  email: string,
  password: string,
): Promise<LoginResult> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    // O refresh volta num cookie HttpOnly; sem isto o navegador o descarta.
    credentials: "include",
  });
  return parseJsonOrThrow<LoginResult>(response);
}

/**
 * Renova o token de acesso usando o cookie de sessão.
 *
 * O acesso dura pouco de propósito. Esta chamada é o que permite continuar
 * trabalhando sem refazer login — o token nunca fica guardado por horas, e o
 * cookie que o renova não é legível por JavaScript.
 *
 * Devolve `null` quando a sessão acabou, para a interface levar ao login sem
 * tratar isso como erro inesperado.
 */
export async function refreshSession(): Promise<LoginResult | null> {
  const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (response.status === 401) {
    return null;
  }
  return parseJsonOrThrow<LoginResult>(response);
}

/** Encerra a sessão no servidor, não apenas no navegador. */
export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function getCurrentUser(token: string): Promise<CurrentUser> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<CurrentUser>(response);
}

export interface UploadImportInput {
  farmId: string;
  file: File;
  declaredLot?: string;
  declaredPeriod?: string;
}

export async function uploadImport(
  input: UploadImportInput,
  token: string,
): Promise<UploadResult> {
  const formData = new FormData();
  formData.set("farm_id", input.farmId);
  formData.set("file", input.file);
  if (input.declaredLot) {
    formData.set("declared_lot", input.declaredLot);
  }
  if (input.declaredPeriod) {
    formData.set("declared_period", input.declaredPeriod);
  }

  const response = await fetch(`${API_BASE_URL}/api/imports`, {
    method: "POST",
    headers: authHeaders(token),
    body: formData,
  });
  return parseJsonOrThrow<UploadResult>(response);
}

export async function reprocessImport(
  importId: string,
  token: string,
): Promise<UploadResult> {
  const response = await fetch(
    `${API_BASE_URL}/api/imports/${importId}/reprocess`,
    { method: "POST", headers: authHeaders(token) },
  );
  return parseJsonOrThrow<UploadResult>(response);
}

export async function getImportReview(
  importId: string,
  token: string,
): Promise<ImportReview> {
  const response = await fetch(
    `${API_BASE_URL}/api/imports/${importId}/review`,
    { headers: authHeaders(token) },
  );
  return parseJsonOrThrow<ImportReview>(response);
}

export interface MeasurementFilter {
  farmId: string;
  from?: string;
  to?: string;
}

export async function getMeasurements(
  filter: MeasurementFilter,
  token: string,
): Promise<MeasurementRecord[]> {
  const params = new URLSearchParams({ farm_id: filter.farmId });
  if (filter.from) {
    params.set("from", filter.from);
  }
  if (filter.to) {
    params.set("to", filter.to);
  }

  const response = await fetch(`${API_BASE_URL}/api/measurements?${params.toString()}`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<MeasurementRecord[]>(response);
}

export async function decideLine(
  lineId: string,
  payload: DecisionRequest,
  token: string,
): Promise<DecisionResult> {
  const response = await fetch(
    `${API_BASE_URL}/api/extracted-lines/${lineId}/decision`,
    {
      method: "POST",
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  return parseJsonOrThrow<DecisionResult>(response);
}


// --- Cadastro mestre ---
//
// Nenhuma destas funções recebe `farm_id`: a fazenda é resolvida no servidor.
// Pedir isso ao usuário seria expor um UUID a quem só quer achar uma vaca.

function jsonHeaders(token: string): HeadersInit {
  return { ...authHeaders(token), "Content-Type": "application/json" };
}

export async function getCurrentFarm(token: string): Promise<Farm> {
  const response = await fetch(`${API_BASE_URL}/api/farms/current`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<Farm>(response);
}

export async function searchAnimals(
  token: string,
  search: AnimalSearch = {},
): Promise<AnimalPage> {
  const params = new URLSearchParams();
  if (search.brinco) params.set("brinco", search.brinco);
  if (search.name) params.set("name", search.name);
  if (search.semBrinco) params.set("sem_brinco", "true");
  if (search.rebanho) params.set("rebanho", search.rebanho);
  params.set("limit", String(search.limit ?? 25));
  params.set("offset", String(search.offset ?? 0));

  const response = await fetch(`${API_BASE_URL}/api/animals?${params}`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<AnimalPage>(response);
}

export async function getAnimal(
  token: string,
  animalId: string,
): Promise<AnimalDetail> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<AnimalDetail>(response);
}

export async function createAnimal(
  token: string,
  input: AnimalCreateInput,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(input),
  });
  return parseJsonOrThrow<Animal>(response);
}

export async function updateAnimal(
  token: string,
  animalId: string,
  changes: AnimalUpdateInput,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify(changes),
  });
  return parseJsonOrThrow<Animal>(response);
}

/** Vincular brinco muda a identidade operacional, então a evidência é exigida. */
export async function linkBrinco(
  token: string,
  animalId: string,
  brinco: string,
  evidence: string,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}/brinco`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ brinco, evidence }),
  });
  return parseJsonOrThrow<Animal>(response);
}

export async function assignLot(
  token: string,
  animalId: string,
  lote: string,
  validFrom: string,
  kind?: LotKind,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}/lote`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ lote, valid_from: validFrom, kind }),
  });
  return parseJsonOrThrow<Animal>(response);
}

// --- Contas ---

export async function listUsers(token: string): Promise<UserPage> {
  const response = await fetch(`${API_BASE_URL}/api/users`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<UserPage>(response);
}

export async function createUser(
  token: string,
  email: string,
  password: string,
  role: Role,
): Promise<UserAccount> {
  const response = await fetch(`${API_BASE_URL}/api/users`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ email, password, role }),
  });
  return parseJsonOrThrow<UserAccount>(response);
}

export async function updateUser(
  token: string,
  userId: string,
  changes: { role?: Role; is_active?: boolean },
): Promise<UserAccount> {
  const response = await fetch(`${API_BASE_URL}/api/users/${userId}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify(changes),
  });
  return parseJsonOrThrow<UserAccount>(response);
}

export async function changeOwnPassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/users/me/password`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.json());
  }
}


// --- Painel do rebanho ---

export async function getDashboard(
  token: string,
  filters: DashboardFilters = {},
): Promise<DashboardSummary> {
  const params = new URLSearchParams();
  if (filters.measuredOn) params.set("measured_on", filters.measuredOn);
  if (filters.lote) params.set("lote", filters.lote);
  if (filters.situacao) params.set("situacao", filters.situacao);

  const query = params.toString();
  const response = await fetch(
    `${API_BASE_URL}/api/dashboard${query ? `?${query}` : ""}`,
    { headers: authHeaders(token) },
  );
  return parseJsonOrThrow<DashboardSummary>(response);
}

export async function listSupplies(token: string): Promise<Supply[]> {
  const response = await fetch(`${API_BASE_URL}/api/supplies`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<Supply[]>(response);
}

export async function createSupply(
  token: string,
  name: string,
  pricePerKg: number,
): Promise<Supply> {
  const response = await fetch(`${API_BASE_URL}/api/supplies`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ name, price_per_kg: pricePerKg }),
  });
  return parseJsonOrThrow<Supply>(response);
}

export async function updateSupplyPrice(
  token: string,
  supplyId: string,
  pricePerKg: number,
): Promise<Supply> {
  const response = await fetch(`${API_BASE_URL}/api/supplies/${supplyId}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify({ price_per_kg: pricePerKg }),
  });
  return parseJsonOrThrow<Supply>(response);
}

export async function setSupplyDiet(
  token: string,
  supplyId: string,
  lote: string,
  kgPerDay: number,
): Promise<Supply> {
  const response = await fetch(`${API_BASE_URL}/api/supplies/${supplyId}/diet`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify({ lote, kg_per_day: kgPerDay }),
  });
  return parseJsonOrThrow<Supply>(response);
}

export async function setMilkPrice(
  token: string,
  pricePerLiter: number,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/farms/current/milk-price`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify({ milk_price_per_liter: pricePerLiter }),
  });
  await parseJsonOrThrow(response);
}

// --- Baixa de animal ---

export async function registerExit(
  token: string,
  animalId: string,
  exitedOn: string,
  reason: ExitReason,
  notes: string | null,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}/exit`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ exited_on: exitedOn, reason, notes }),
  });
  return parseJsonOrThrow<Animal>(response);
}

export async function undoExit(
  token: string,
  animalId: string,
  reason: string,
): Promise<Animal> {
  const response = await fetch(`${API_BASE_URL}/api/animals/${animalId}/exit/undo`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ reason }),
  });
  return parseJsonOrThrow<Animal>(response);
}

// --- Redefinição de senha ---

export async function resetUserPassword(
  token: string,
  userId: string,
): Promise<PasswordReset> {
  const response = await fetch(`${API_BASE_URL}/api/users/${userId}/password-reset`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<PasswordReset>(response);
}

// --- Lançamento de produção ---

export async function getProductionSheet(
  token: string,
  measuredOn: string,
  lote: string | null,
): Promise<ProductionSheet> {
  const params = new URLSearchParams({ measured_on: measuredOn });
  if (lote) params.set("lote", lote);
  const response = await fetch(`${API_BASE_URL}/api/production/sheet?${params}`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<ProductionSheet>(response);
}

/** 201 cria; 200 é o mesmo valor reenviado (retry); 409 é outro valor. */
export async function enterReading(
  token: string,
  animalId: string,
  measuredOn: string,
  producao: number,
): Promise<Reading> {
  const response = await fetch(`${API_BASE_URL}/api/production`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ animal_id: animalId, measured_on: measuredOn, producao }),
  });
  return parseJsonOrThrow<Reading>(response);
}

export async function correctReading(
  token: string,
  measurementId: string,
  producao: number,
  reason: string,
): Promise<Reading> {
  const response = await fetch(
    `${API_BASE_URL}/api/production/${measurementId}/correction`,
    {
      method: "POST",
      headers: jsonHeaders(token),
      body: JSON.stringify({ producao, reason }),
    },
  );
  return parseJsonOrThrow<Reading>(response);
}

export async function voidReading(
  token: string,
  measurementId: string,
  reason: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/production/${measurementId}/void`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.json());
  }
}

// --- Importação de coleta por arquivo ---

function importForm(file: File, measuredOn: string): FormData {
  const form = new FormData();
  form.set("file", file);
  form.set("measured_on", measuredOn);
  return form;
}

/** Lê o arquivo no servidor e mostra o que aconteceria. Não grava nada. */
export async function previewImport(
  token: string,
  file: File,
  measuredOn: string,
): Promise<ImportPreview> {
  const response = await fetch(`${API_BASE_URL}/api/production/import/preview`, {
    method: "POST",
    headers: authHeaders(token),
    body: importForm(file, measuredOn),
  });
  return parseJsonOrThrow<ImportPreview>(response);
}

/** Grava. O servidor recalcula tudo a partir do arquivo; nada da prévia é reenviado. */
export async function commitImport(
  token: string,
  file: File,
  measuredOn: string,
  mode: ImportMode,
  reason: string | null,
): Promise<ImportRecord> {
  const form = importForm(file, measuredOn);
  form.set("mode", mode);
  if (reason) form.set("reason", reason);
  const response = await fetch(`${API_BASE_URL}/api/production/import`, {
    method: "POST",
    headers: authHeaders(token),
    body: form,
  });
  return parseJsonOrThrow<ImportRecord>(response);
}

export async function listImports(token: string): Promise<ImportRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/production/imports`, {
    headers: authHeaders(token),
  });
  return parseJsonOrThrow<ImportRecord[]>(response);
}
