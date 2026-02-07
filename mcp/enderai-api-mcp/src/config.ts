export type Config = {
  baseUrl: string;
  bearerToken?: string;
  timeoutMs: number;
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const baseUrl = (env.ENDERAI_BASE_URL ?? "https://enderai-backend.onrender.com").trim();
  const bearerToken = env.ENDERAI_BEARER_TOKEN?.trim() || undefined;

  const timeoutMsRaw = (env.ENDERAI_TIMEOUT_MS ?? "30000").trim();
  const timeoutMs = Number.parseInt(timeoutMsRaw, 10);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error(`Invalid ENDERAI_TIMEOUT_MS: ${timeoutMsRaw}`);
  }

  // Validate baseUrl is a proper absolute URL early (better errors to users).
  // Allow http for local dev.
  // eslint-disable-next-line no-new
  new URL(baseUrl);

  return { baseUrl, bearerToken, timeoutMs };
}
