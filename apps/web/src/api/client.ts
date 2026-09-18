import {
  ApiError,
  type CurrentUser,
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
