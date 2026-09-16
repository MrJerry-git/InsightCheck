import { appConfig } from "@/lib/config";
import type { LesionDemoAnalysis } from "@/types/lesion";
import type { HealthStatus } from "@/types/system";

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
    throw new ApiError(`Request failed: ${response.statusText}`, response.status);
  }

  return (await response.json()) as T;
}

export const apiClient = {
  getHealth: () => request<HealthStatus>("/health"),
  getLesionDemoAnalysis: () =>
    request<LesionDemoAnalysis>("/lesion-analysis/demo"),
};
