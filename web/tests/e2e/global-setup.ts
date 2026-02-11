import { FullConfig, request } from "@playwright/test";
import {
  TEST_ADMIN_CREDENTIALS,
  TEST_ADMIN2_CREDENTIALS,
  TEST_USER_CREDENTIALS,
} from "./constants";
import { OnyxApiClient } from "./utils/onyxApiClient";

const PREFLIGHT_TIMEOUT_MS = 60_000;
const PREFLIGHT_POLL_INTERVAL_MS = 2_000;

/**
 * Poll the health endpoint until the server is ready or we time out.
 * Fails fast with a clear error so developers don't see cryptic browser errors.
 */
async function waitForServer(baseURL: string): Promise<void> {
  const healthURL = baseURL;
  const deadline = Date.now() + PREFLIGHT_TIMEOUT_MS;

  console.log(`[global-setup] Waiting for server at ${healthURL} ...`);

  while (Date.now() < deadline) {
    try {
      const res = await fetch(healthURL);
      if (res.ok) {
        console.log("[global-setup] Server is ready.");
        return;
      }
      console.log(`[global-setup] Server returned ${res.status}, retrying ...`);
    } catch {
      // Connection refused / DNS error — server not up yet.
    }
    await new Promise((r) => setTimeout(r, PREFLIGHT_POLL_INTERVAL_MS));
  }

  throw new Error(
    `Onyx is not running at ${baseURL}. ` +
      `Timed out after ${
        PREFLIGHT_TIMEOUT_MS / 1000
      }s waiting for ${healthURL} to return 200. ` +
      `Make sure the server is running (e.g. \`ods compose dev\`).`
  );
}

/**
 * Register a user via the backend API. Idempotent — silently succeeds if the
 * user already exists (HTTP 400 with "REGISTER_USER_ALREADY_EXISTS").
 */
async function ensureUserExists(
  apiBase: string,
  email: string,
  password: string
): Promise<void> {
  const ctx = await request.newContext({ baseURL: apiBase });
  try {
    const res = await ctx.post("/api/auth/register", {
      data: { email, username: email, password },
    });

    if (res.ok()) {
      console.log(`[global-setup] Registered user ${email}`);
    } else {
      const body = await res.text();
      // "REGISTER_USER_ALREADY_EXISTS" is the standard FastAPI-Users error code
      if (
        res.status() === 400 &&
        body.includes("REGISTER_USER_ALREADY_EXISTS")
      ) {
        console.log(`[global-setup] User ${email} already exists, skipping.`);
      } else {
        console.warn(
          `[global-setup] Unexpected response registering ${email}: ${res.status()} ${body}`
        );
      }
    }
  } finally {
    await ctx.dispose();
  }
}

/**
 * Log in via the API and save the resulting cookies as a Playwright storage
 * state file.  No browser is needed — this uses Playwright's lightweight
 * request context, which is much faster and produces no console noise.
 */
async function apiLoginAndSaveState(
  baseURL: string,
  email: string,
  password: string,
  storageStatePath: string
): Promise<void> {
  const ctx = await request.newContext({ baseURL });
  try {
    const res = await ctx.post("/api/auth/login", {
      form: { username: email, password },
    });
    if (!res.ok()) {
      const body = await res.text();
      throw new Error(
        `[global-setup] Login failed for ${email}: ${res.status()} ${body}`
      );
    }
    await ctx.storageState({ path: storageStatePath });
  } finally {
    await ctx.dispose();
  }
}

/**
 * Promote a user to admin via the manage API.
 * Requires an authenticated context (admin storage state).
 */
async function promoteToAdmin(
  baseURL: string,
  adminStorageState: string,
  email: string
): Promise<void> {
  const ctx = await request.newContext({
    baseURL,
    storageState: adminStorageState,
  });
  try {
    const res = await ctx.patch("/api/manage/set-user-role", {
      data: {
        user_email: email,
        new_role: "admin",
      },
    });
    if (res.ok()) {
      console.log(`[global-setup] Promoted ${email} to admin`);
    } else if (res.status() === 403) {
      throw new Error(
        `[global-setup] Cannot promote ${email} — the primary admin account ` +
          `(${TEST_ADMIN_CREDENTIALS.email}) does not have the admin role.\n\n` +
          `This usually happens when running tests against a non-fresh database ` +
          `where another user was registered first.\n\n` +
          `To fix this, either:\n` +
          `  1. Promote the user manually: ${baseURL}/admin/users\n` +
          `  2. Reset to a seeded database: ods db restore --fetch-seeded\n`
      );
    } else {
      const body = await res.text();
      console.warn(
        `[global-setup] Failed to promote ${email}: ${res.status()} ${body}`
      );
    }
  } finally {
    await ctx.dispose();
  }
}

async function globalSetup(config: FullConfig) {
  // Get baseURL from config, fallback to localhost:3000
  const baseURL = config.projects[0]?.use?.baseURL || "http://localhost:3000";

  // ── Preflight check ──────────────────────────────────────────────────
  await waitForServer(baseURL);

  // ── Provision test users via API ─────────────────────────────────────
  // The first user registered becomes the admin automatically.
  // Order matters: admin first, then user, then admin2.
  await ensureUserExists(
    baseURL,
    TEST_ADMIN_CREDENTIALS.email,
    TEST_ADMIN_CREDENTIALS.password
  );
  await ensureUserExists(
    baseURL,
    TEST_USER_CREDENTIALS.email,
    TEST_USER_CREDENTIALS.password
  );
  await ensureUserExists(
    baseURL,
    TEST_ADMIN2_CREDENTIALS.email,
    TEST_ADMIN2_CREDENTIALS.password
  );

  // ── Login via API and save storage state ───────────────────────────
  await apiLoginAndSaveState(
    baseURL,
    TEST_ADMIN_CREDENTIALS.email,
    TEST_ADMIN_CREDENTIALS.password,
    "admin_auth.json"
  );

  // Promote admin2 now that we have an admin session
  await promoteToAdmin(
    baseURL,
    "admin_auth.json",
    TEST_ADMIN2_CREDENTIALS.email
  );

  await apiLoginAndSaveState(
    baseURL,
    TEST_USER_CREDENTIALS.email,
    TEST_USER_CREDENTIALS.password,
    "user_auth.json"
  );

  await apiLoginAndSaveState(
    baseURL,
    TEST_ADMIN2_CREDENTIALS.email,
    TEST_ADMIN2_CREDENTIALS.password,
    "admin2_auth.json"
  );

  // ── Ensure a public LLM provider exists ───────────────────────────
  // Many tests depend on a default LLM being configured (file uploads,
  // assistant creation, etc.).  Re-use the admin session we just saved.
  const adminCtx = await request.newContext({
    baseURL,
    storageState: "admin_auth.json",
  });
  try {
    const client = new OnyxApiClient(adminCtx, baseURL);
    await client.ensurePublicProvider();
  } finally {
    await adminCtx.dispose();
  }
}

export default globalSetup;
