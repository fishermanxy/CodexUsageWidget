import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getConfigDir } from "../config";

export const RESET_CREDIT_DETAILS_CACHE = "reset-credit-details-cache.json";
const PRODUCER_VERSION = "2.60.0";

type ResetCredit = { grantedAt?: string; expiresAt: string };
type CacheEntry = { availableCount: number; credits: ResetCredit[]; updatedAt: number; lastFailureAt?: number };
type Cache = { schemaVersion: 1; producerVersion: string; revision: number; accounts: Record<string, CacheEntry> };

const syncFlights = new Map<string, Promise<void>>();

function cachePath(): string { return join(getConfigDir(), RESET_CREDIT_DETAILS_CACHE); }

async function readCache(): Promise<Cache> {
  try {
    const parsed = JSON.parse(await readFile(cachePath(), "utf8")) as Partial<Cache>;
    if (parsed.schemaVersion === 1 && parsed.accounts && typeof parsed.accounts === "object") {
      return { schemaVersion: 1, producerVersion: String(parsed.producerVersion || PRODUCER_VERSION), revision: Number(parsed.revision || 0), accounts: parsed.accounts };
    }
  } catch {}
  return { schemaVersion: 1, producerVersion: PRODUCER_VERSION, revision: 0, accounts: {} };
}

async function writeCache(cache: Cache): Promise<void> {
  await mkdir(getConfigDir(), { recursive: true });
  const target = cachePath();
  const temp = `${target}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temp, JSON.stringify(cache), "utf8");
  await rename(temp, target);
}

function parseDetails(value: unknown, fallbackCount: number): { availableCount: number; credits: ResetCredit[] } {
  const obj = typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
  const rawCredits = Array.isArray(obj.credits) ? obj.credits : [];
  const credits = rawCredits.flatMap((raw): ResetCredit[] => {
    if (typeof raw !== "object" || raw === null) return [];
    const credit = raw as Record<string, unknown>;
    return typeof credit.expires_at === "string" ? [{ expiresAt: credit.expires_at, ...(typeof credit.granted_at === "string" ? { grantedAt: credit.granted_at } : {}) }] : [];
  });
  const nested = obj.rate_limit_reset_credits as { available_count?: unknown } | null | undefined;
  const count = nested?.available_count ?? obj.available_count;
  return { availableCount: typeof count === "number" && Number.isFinite(count) ? Math.max(0, count) : fallbackCount, credits };
}

/** Best-effort, token-free-on-disk cache refresh. Failures never escape to routing. */
export async function syncResetCreditDetails(accountId: string, availableCount: number, auth: { accessToken: string; chatgptAccountId: string }): Promise<void> {
  const active = syncFlights.get(accountId);
  if (active) return active;
  const flight = syncResetCreditDetailsOnce(accountId, availableCount, auth);
  syncFlights.set(accountId, flight);
  try {
    await flight;
  } catch {
    // Details are auxiliary UI data. A cache or filesystem failure must never
    // turn a successful WHAM quota refresh into a routing failure.
  } finally {
    if (syncFlights.get(accountId) === flight) syncFlights.delete(accountId);
  }
}

async function syncResetCreditDetailsOnce(accountId: string, availableCount: number, auth: { accessToken: string; chatgptAccountId: string }): Promise<void> {
  const cache = await readCache();
  const previous = cache.accounts[accountId];
  const hasCompleteDetails = availableCount > 0
    && Array.isArray(previous?.credits)
    && previous.credits.length === availableCount;
  if (previous?.availableCount === availableCount && hasCompleteDetails) return;
  const now = Date.now();
  if (availableCount <= 0) {
    const previousCredits = Array.isArray(previous?.credits) ? previous.credits : [];
    if (previous?.availableCount !== 0 || previousCredits.length !== 0 || previous?.lastFailureAt !== undefined) {
      cache.accounts[accountId] = { availableCount: 0, credits: [], updatedAt: now };
      cache.revision += 1;
      await writeCache(cache);
    }
    return;
  }
  try {
    const response = await fetch("https://chatgpt.com/backend-api/wham/rate-limit-reset-credits", {
      headers: { Authorization: `Bearer ${auth.accessToken}`, "ChatGPT-Account-Id": auth.chatgptAccountId },
      signal: AbortSignal.timeout(8_000),
    });
    if (!response.ok) throw new Error(`upstream ${response.status}`);
    const details = parseDetails(await response.json(), availableCount);
    // The WHAM usage response is the change detector. Keep its count as the
    // cache key even if the detail endpoint omits or formats its own summary.
    cache.accounts[accountId] = { availableCount, credits: details.credits, updatedAt: now };
  } catch {
    cache.accounts[accountId] = { availableCount, credits: previous?.credits ?? [], updatedAt: previous?.updatedAt ?? now, lastFailureAt: now };
  }
  cache.revision += 1;
  await writeCache(cache);
}
