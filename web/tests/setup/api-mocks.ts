/**
 * Reusable API Mocking Utilities
 *
 * This file provides helper functions for mocking API responses in tests.
 * Import these utilities to make your tests more readable and maintainable.
 *
 * @example
 * ```typescript
 * import { mockApiSuccess, mockApiError, mockNetworkError } from "@tests/setup/api-mocks";
 *
 * it("handles successful API response", async () => {
 *   mockApiSuccess(fetchSpy, { id: 1, name: "Test" });
 *   // ... test code ...
 * });
 * ```
 */

/**
 * Mock a successful API response with 200 OK status
 */
export function mockApiSuccess<T = any>(
  fetchSpy: jest.SpyInstance,
  data: T,
  status: number = 200
): void {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    status,
    json: async () => data,
    headers: new Headers({ "Content-Type": "application/json" }),
  } as Response);
}

/**
 * Mock an API error response with custom status and error message
 */
export function mockApiError(
  fetchSpy: jest.SpyInstance,
  status: number,
  detail: string
): void {
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status,
    json: async () => ({ detail }),
    headers: new Headers({ "Content-Type": "application/json" }),
  } as Response);
}

/**
 * Mock a network error (rejected promise)
 */
export function mockNetworkError(
  fetchSpy: jest.SpyInstance,
  message: string = "Network request failed"
): void {
  fetchSpy.mockRejectedValueOnce(new Error(message));
}

/**
 * Mock a 400 Bad Request error
 */
export function mockBadRequestError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Bad Request"
): void {
  mockApiError(fetchSpy, 400, detail);
}

/**
 * Mock a 401 Unauthorized error
 */
export function mockUnauthorizedError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Unauthorized"
): void {
  mockApiError(fetchSpy, 401, detail);
}

/**
 * Mock a 403 Forbidden error
 */
export function mockForbiddenError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Forbidden"
): void {
  mockApiError(fetchSpy, 403, detail);
}

/**
 * Mock a 404 Not Found error
 */
export function mockNotFoundError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Not Found"
): void {
  mockApiError(fetchSpy, 404, detail);
}

/**
 * Mock a 409 Conflict error (e.g., duplicate email)
 */
export function mockConflictError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Conflict"
): void {
  mockApiError(fetchSpy, 409, detail);
}

/**
 * Mock a 500 Internal Server Error
 */
export function mockServerError(
  fetchSpy: jest.SpyInstance,
  detail: string = "Internal Server Error"
): void {
  mockApiError(fetchSpy, 500, detail);
}

/**
 * Mock a slow API response (useful for testing loading states)
 */
export function mockSlowApiSuccess<T = any>(
  fetchSpy: jest.SpyInstance,
  data: T,
  delayMs: number = 1000
): void {
  fetchSpy.mockImplementationOnce(
    () =>
      new Promise((resolve) =>
        setTimeout(
          () =>
            resolve({
              ok: true,
              status: 200,
              json: async () => data,
              headers: new Headers({ "Content-Type": "application/json" }),
            } as Response),
          delayMs
        )
      )
  );
}

/**
 * Mock multiple sequential API responses
 *
 * @example
 * ```typescript
 * mockSequentialResponses(fetchSpy, [
 *   { success: true, data: item1 },
 *   { success: true, data: item2 },
 *   { success: false, status: 400, detail: "Error" },
 * ]);
 * ```
 */
export function mockSequentialResponses(
  fetchSpy: jest.SpyInstance,
  responses: Array<
    | { success: true; data: any; status?: number }
    | { success: false; status: number; detail: string }
  >
): void {
  responses.forEach((response) => {
    if (response.success) {
      mockApiSuccess(fetchSpy, response.data, response.status);
    } else {
      mockApiError(fetchSpy, response.status, response.detail);
    }
  });
}

/**
 * Extract and parse request body from fetch spy call
 */
export function getRequestBody<T = any>(
  fetchSpy: jest.SpyInstance,
  callIndex: number = 0
): T {
  const [_, options] = fetchSpy.mock.calls[callIndex];
  return JSON.parse(options.body) as T;
}

/**
 * Extract request URL from fetch spy call
 */
export function getRequestUrl(
  fetchSpy: jest.SpyInstance,
  callIndex: number = 0
): string {
  const [url] = fetchSpy.mock.calls[callIndex];
  return url;
}

/**
 * Extract request method from fetch spy call
 */
export function getRequestMethod(
  fetchSpy: jest.SpyInstance,
  callIndex: number = 0
): string {
  const [_, options] = fetchSpy.mock.calls[callIndex];
  return options.method;
}

/**
 * Extract request headers from fetch spy call
 */
export function getRequestHeaders(
  fetchSpy: jest.SpyInstance,
  callIndex: number = 0
): Record<string, string> {
  const [_, options] = fetchSpy.mock.calls[callIndex];
  return options.headers;
}

/**
 * Validate complete request details
 */
export function expectRequest(
  fetchSpy: jest.SpyInstance,
  expected: {
    url: string;
    method: string;
    body?: any;
    headers?: Record<string, string>;
    callIndex?: number;
  }
): void {
  const callIndex = expected.callIndex ?? 0;
  const [url, options] = fetchSpy.mock.calls[callIndex];

  expect(url).toBe(expected.url);
  expect(options.method).toBe(expected.method);

  if (expected.body !== undefined) {
    const requestBody = JSON.parse(options.body);
    expect(requestBody).toEqual(expected.body);
  }

  if (expected.headers) {
    expect(options.headers).toEqual(expect.objectContaining(expected.headers));
  }
}

/**
 * Setup fetch spy for tests (call in beforeEach)
 */
export function setupFetchSpy(): jest.SpyInstance {
  return jest.spyOn(global, "fetch");
}

/**
 * Cleanup fetch spy (call in afterEach)
 */
export function cleanupFetchSpy(fetchSpy: jest.SpyInstance): void {
  fetchSpy.mockRestore();
}
