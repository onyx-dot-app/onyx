/**
 * Mock Service Worker (MSW) setup for API mocking in tests.
 *
 * NOTE: Due to ESM compatibility issues with Jest and MSW v2, this file is NOT
 * imported globally. Import it directly in tests that need API mocking.
 *
 * IMPORTANT: MSW has compatibility issues with Jest. For now, use direct fetch mocking
 * or mock SWR responses instead. This file is kept as documentation for future use
 * when MSW compatibility improves.
 *
 * Example usage:
 *
 * import { http, HttpResponse } from "msw";
 * import { setupServer } from "msw/node";
 *
 * const server = setupServer(
 *   http.get("/api/credentials", () => HttpResponse.json([]))
 * );
 *
 * beforeAll(() => server.listen());
 * afterEach(() => server.resetHandlers());
 * afterAll(() => server.close());
 */

// Placeholder - MSW setup to be added per-test as needed
export const setupMockServer = () => {
  console.warn("MSW is not fully configured yet. Use direct mocking instead.");
};
