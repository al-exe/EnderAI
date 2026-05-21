export type Config = {
  baseUrl: string;
  bearerToken?: string;
  timeoutMs: number;
};

/**
 * Load config from env. Honors both the new ``TASKFORCE_*`` names
 * (canonical going forward, TF-180) and the legacy ``ENDERAI_*`` names
 * (kept as aliases for backwards compat through one release).
 *
 * Precedence is "canonical first": if both ``TASKFORCE_BEARER_TOKEN``
 * and ``ENDERAI_BEARER_TOKEN`` are set, the taskforce one wins.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const baseUrl = (
    env.TASKFORCE_BASE_URL ??
    env.ENDERAI_BASE_URL ??
    "https://enderai-backend.onrender.com"
  ).trim();
  const bearerToken =
    env.TASKFORCE_BEARER_TOKEN?.trim() ||
    env.ENDERAI_BEARER_TOKEN?.trim() ||
    undefined;

  const timeoutMsRaw = (
    env.TASKFORCE_TIMEOUT_MS ??
    env.ENDERAI_TIMEOUT_MS ??
    "30000"
  ).trim();
  const timeoutMs = Number.parseInt(timeoutMsRaw, 10);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error(`Invalid TASKFORCE_TIMEOUT_MS / ENDERAI_TIMEOUT_MS: ${timeoutMsRaw}`);
  }

  // Validate baseUrl is a proper absolute URL early (better errors to users).
  // Allow http for local dev.
  // eslint-disable-next-line no-new
  new URL(baseUrl);

  return { baseUrl, bearerToken, timeoutMs };
}
