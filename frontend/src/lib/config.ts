/**
 * Runtime configuration, read once and validated.
 *
 * Fails loudly at module load rather than producing `undefined` fetch URLs that
 * only surface as a confusing network error later.
 */

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `Missing ${name}. Copy .env.local.example to .env.local and fill it in.`,
    );
  }
  return value;
}

export type AppEnv = "local" | "prod";

export const config = {
  apiBaseUrl: required(
    "NEXT_PUBLIC_API_BASE_URL",
    process.env.NEXT_PUBLIC_API_BASE_URL,
  ).replace(/\/$/, ""),
  appEnv: (process.env.NEXT_PUBLIC_APP_ENV ?? "local") as AppEnv,
} as const;
