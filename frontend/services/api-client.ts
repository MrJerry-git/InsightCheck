import { appConfig } from "@/lib/config";
import type { LesionDemoAnalysis } from "@/types/lesion";
import type { HealthStatus } from "@/types/system";
import type { ImportedHistory, ImportedPatient, ImportResult, ImportValidation } from "@/types/imports";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(`请求失败 (${response.status})：${detail}`, response.status);
  }

  return (await response.json()) as T;
}

export const apiClient = {
  validateImport: (payload: unknown) => request<ImportValidation>("/imports/validate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }),
  importData: (payload: unknown) => request<ImportResult>("/imports", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }),
  getImportedPatients: () => request<ImportedPatient[]>("/imports/patients?limit=1000"),
  getImportedHistory: (id: string) =>
    request<ImportedHistory>(`/imports/patients/${encodeURIComponent(id)}/timeline`),
  getHealth: () => request<HealthStatus>("/health"),
  getLesionDemoAnalysis: () =>
    request<LesionDemoAnalysis>("/lesion-analysis/demo"),
};
