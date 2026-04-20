import { act } from "@testing-library/react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import SignupChallengeGate from "./SignupChallengeGate";

// Cloudflare's Turnstile widget is an external script. Capture its render
// options so tests can drive the widget's callbacks.
type TurnstileOptions = {
  sitekey: string;
  callback: (token: string) => void;
  "error-callback"?: (code: string) => void;
  "expired-callback"?: () => void;
};
let capturedOptions: TurnstileOptions | null;

const TURNSTILE_SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js";

function seedTurnstile() {
  // Pre-seed the <script> tag so TurnstileChallenge's loader takes the
  // "script already exists" branch instead of appending a fresh one.
  const tag = document.createElement("script");
  tag.src = TURNSTILE_SCRIPT_SRC;
  document.head.appendChild(tag);

  const render = jest.fn(
    (_container: HTMLElement, options: TurnstileOptions) => {
      capturedOptions = options;
      return "widget-id-1";
    }
  );
  // Cloudflare widget global stub.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).turnstile = {
    render,
    reset: jest.fn(),
    remove: jest.fn(),
  };
}

function teardownTurnstile() {
  capturedOptions = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).turnstile;
  document
    .querySelectorAll(`script[src="${TURNSTILE_SCRIPT_SRC}"]`)
    .forEach((s) => s.remove());
}

describe("SignupChallengeGate", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    capturedOptions = null;
    seedTurnstile();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    teardownTurnstile();
    fetchSpy.mockRestore();
  });

  test("renders children immediately when turnstile is disabled (empty site key)", () => {
    render(
      <SignupChallengeGate siteKey="">
        <p>Protected signup form</p>
      </SignupChallengeGate>
    );

    expect(screen.getByText(/protected signup form/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/verify you're a human/i)
    ).not.toBeInTheDocument();
  });

  test("hides children and shows challenge prompt when a site key is configured", () => {
    render(
      <SignupChallengeGate siteKey="site-key-123">
        <p>Protected signup form</p>
      </SignupChallengeGate>
    );

    expect(screen.getByText(/verify you're a human/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/protected signup form/i)
    ).not.toBeInTheDocument();
  });

  test("reveals children after the challenge widget succeeds and the backend accepts the token", async () => {
    // Mock POST /api/auth/turnstile/verify (accepted).
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true }),
    } as Response);

    render(
      <SignupChallengeGate siteKey="site-key-123">
        <p>Protected signup form</p>
      </SignupChallengeGate>
    );

    await waitFor(() => expect(capturedOptions).not.toBeNull());

    // Widget got a valid Turnstile token and calls back into our component.
    await act(async () => {
      capturedOptions?.callback("turnstile-token-xyz");
    });

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/turnstile/verify",
        expect.objectContaining({ method: "POST" })
      )
    );

    expect(
      await screen.findByText(/protected signup form/i)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/verify you're a human/i)
    ).not.toBeInTheDocument();
  });

  test("shows a user-friendly error when the backend rejects the token", async () => {
    // Mock POST /api/auth/turnstile/verify (rejected).
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        error_code: "UNAUTHORIZED",
        detail: "Turnstile verification failed: invalid-input-response",
      }),
    } as Response);

    render(
      <SignupChallengeGate siteKey="site-key-123">
        <p>Protected signup form</p>
      </SignupChallengeGate>
    );

    await waitFor(() => expect(capturedOptions).not.toBeNull());
    await act(async () => {
      capturedOptions?.callback("any-token");
    });

    expect(
      await screen.findByText(/verification failed\. please try again/i)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/protected signup form/i)
    ).not.toBeInTheDocument();
  });

  test("shows a humanized error when the widget itself errors out", async () => {
    render(
      <SignupChallengeGate siteKey="site-key-123">
        <p>Protected signup form</p>
      </SignupChallengeGate>
    );

    await waitFor(() => expect(capturedOptions).not.toBeNull());
    // Simulate Cloudflare returning a 400xxx configuration error.
    await act(async () => {
      capturedOptions?.["error-callback"]?.("400020");
    });

    expect(
      await screen.findByText(/challenge couldn't load/i)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/protected signup form/i)
    ).not.toBeInTheDocument();
  });
});
