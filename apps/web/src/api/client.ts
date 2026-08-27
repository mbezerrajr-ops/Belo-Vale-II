import {
  ApiError,
  type DecisionRequest,
  type DecisionResult,
  type ImportReview,
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
