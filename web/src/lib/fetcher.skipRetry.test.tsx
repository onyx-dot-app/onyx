/**
 * Regression coverage for skipRetryOnAuthError: auth errors never retry;
 * non-auth retries fire after backoff while visible; hidden tabs defer the
 * retry until visibility returns instead of dropping the chain.
 */
import { FetchError, skipRetryOnAuthError } from "@/lib/fetcher";
import { setDocumentVisibility } from "@tests/setup/test-utils";

type RetryParams = Parameters<typeof skipRetryOnAuthError>;
const emptyConfig = {} as RetryParams[2];

// ts-jest compiles to ES5, where `class extends Error` breaks instanceof on
// construction; build via the prototype so the guard's instanceof check holds.
function makeAuthError(status: number): FetchError {
  const err = Object.create(FetchError.prototype) as FetchError;
  err.status = status;
  return err;
}

function makeRevalidate() {
  return jest.fn().mockResolvedValue(true) as unknown as RetryParams[3] &
    jest.Mock;
}

describe("skipRetryOnAuthError", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    setDocumentVisibility(true);
  });

  afterEach(() => {
    jest.useRealTimers();
    setDocumentVisibility(true);
  });

  test("never retries auth errors", () => {
    const revalidate = makeRevalidate();
    skipRetryOnAuthError(makeAuthError(401), "key", emptyConfig, revalidate, {
      retryCount: 0,
      dedupe: false,
    });

    jest.advanceTimersByTime(60000);
    expect(revalidate).not.toHaveBeenCalled();
  });

  test("retries non-auth errors after backoff while visible", () => {
    const revalidate = makeRevalidate();
    skipRetryOnAuthError(new Error("boom"), "key", emptyConfig, revalidate, {
      retryCount: 0,
      dedupe: false,
    });

    jest.advanceTimersByTime(2000);
    expect(revalidate).toHaveBeenCalledWith({ retryCount: 0 });
  });

  test("defers the retry while hidden and fires on return to visibility", () => {
    const revalidate = makeRevalidate();
    skipRetryOnAuthError(new Error("boom"), "key", emptyConfig, revalidate, {
      retryCount: 0,
      dedupe: false,
    });

    setDocumentVisibility(false);
    jest.advanceTimersByTime(2000);
    expect(revalidate).not.toHaveBeenCalled();

    setDocumentVisibility(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(revalidate).toHaveBeenCalledWith({ retryCount: 0 });
  });
});
