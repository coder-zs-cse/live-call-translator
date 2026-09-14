/**
 * Typed client for the backend.
 *
 * Every response shape is declared here. No `any`, and no raw `fetch` calls
 * scattered through components - when the backend contract changes, this file
 * is the one that stops compiling.
 */

import { config } from "@/lib/config";

export interface DependencyHealth {
  name: string;
  healthy: boolean;
  detail: string | null;
}

export interface HealthResponse {
  status: string;
  environment: AppEnvironment;
  version: string;
  dependencies: DependencyHealth[];
}

export type AppEnvironment = "local" | "prod";

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
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(
      `${init?.method ?? "GET"} ${path} failed`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

export const api = {
  health: (): Promise<HealthResponse> => request<HealthResponse>("/api/v1/health"),
};
