/**
 * Phase 0 landing page: proves the frontend can reach the backend.
 *
 * Phase 6 replaces this with the real dashboard - live calls, the call
 * inspector, usage. Until then it earns its place by failing visibly when the
 * two halves are misconfigured, which is the most common local setup mistake.
 */

import type { ReactNode } from "react";

import { api, type HealthResponse } from "@/lib/api";
import { config } from "@/lib/config";

export const dynamic = "force-dynamic";

async function loadHealth(): Promise<HealthResponse | { error: string }> {
  try {
    return await api.health();
  } catch (error) {
    return { error: error instanceof Error ? error.message : "unknown error" };
  }
}

export default async function Home(): Promise<ReactNode> {
  const health = await loadHealth();

  return (
    <main>
      <h1>Live Call Translator</h1>
      <p className="subtitle">
        Admin panel · environment <strong>{config.appEnv}</strong> · api{" "}
        <span className="name">{config.apiBaseUrl}</span>
      </p>

      <div className="card">
        <h2 style={{ fontSize: 15, margin: "0 0 12px" }}>Backend health</h2>
        {"error" in health ? (
          <p className="bad">
            Cannot reach the backend: {health.error}. Is it running on{" "}
            <span className="name">{config.apiBaseUrl}</span>?
          </p>
        ) : (
          <>
            <div className="row">
              <span>status</span>
              <span className={health.status === "ok" ? "ok" : "bad"}>
                {health.status}
              </span>
            </div>
            {health.dependencies.map((dependency) => (
              <div className="row" key={dependency.name}>
                <span className="name">{dependency.name}</span>
                <span className={dependency.healthy ? "ok" : "bad"}>
                  {dependency.detail ?? (dependency.healthy ? "ok" : "failing")}
                </span>
              </div>
            ))}
          </>
        )}
      </div>

      <p className="subtitle" style={{ marginBottom: 0 }}>
        Next: phases 1–4 in <span className="name">docs/PLAN.md</span> — media
        path, single-leg translation, IVR, then the two-leg bridge.
      </p>
    </main>
  );
}
