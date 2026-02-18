export const TEST_ADMIN_CREDENTIALS = {
  email: "admin_user@example.com",
  password: "TestPassword123!",
};

export const TEST_ADMIN2_CREDENTIALS = {
  email: "admin2_user@example.com",
  password: "TestPassword123!",
};

/**
 * Number of distinct worker users provisioned during global setup.
 * Must be >= the max concurrent workers in playwright.config.ts.
 * Playwright's workerIndex can exceed this (retries spawn new workers
 * with incrementing indices), so callers should use modulo:
 *   workerIndex % WORKER_USER_POOL_SIZE
 */
export const WORKER_USER_POOL_SIZE = 8;

export function workerUserCredentials(workerIndex: number): {
  email: string;
  password: string;
} {
  return {
    email: `worker${workerIndex}@example.com`,
    password: "WorkerPassword123!",
  };
}
