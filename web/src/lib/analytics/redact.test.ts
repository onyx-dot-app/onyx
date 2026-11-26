import type { CaptureResult, CapturedNetworkRequest } from "posthog-js";
import {
  redactCapturedRequest,
  redactEventUrls,
  redactUrl,
} from "@/lib/analytics/redact";

describe("redactUrl", () => {
  test.each([
    [
      "https://onyx.example.com/auth/magic-link?token=abc",
      "https://onyx.example.com/auth/magic-link?token=redacted",
    ],
    [
      "/auth/reset-password?token=abc&tenant=t1",
      "/auth/reset-password?token=redacted&tenant=t1",
    ],
    [
      "/auth/verify-email?token=abc#top",
      "/auth/verify-email?token=redacted#top",
    ],
  ])("hides the token in %s", (url, expected) => {
    expect(redactUrl(url)).toBe(expected);
  });

  test.each([
    "/app/chat?id=42",
    "https://onyx.example.com/app",
    "not a url ::",
  ])("leaves %s as it is", (url) => {
    expect(redactUrl(url)).toBe(url);
  });
});

describe("redactEventUrls", () => {
  test("hides the token in every URL the event carries", () => {
    const event = {
      uuid: "u",
      event: "$autocapture",
      properties: {
        $current_url: "https://onyx.example.com/auth/magic-link?token=abc",
        $referrer: "https://mail.example.com/",
        other: "token=abc",
      },
      $set_once: {
        $initial_current_url:
          "https://onyx.example.com/auth/magic-link?token=abc",
      },
    } as unknown as CaptureResult;

    const result = redactEventUrls(event);

    expect(result?.properties.$current_url).toBe(
      "https://onyx.example.com/auth/magic-link?token=redacted"
    );
    expect(result?.$set_once?.$initial_current_url).toBe(
      "https://onyx.example.com/auth/magic-link?token=redacted"
    );
    // Only URL properties are touched.
    expect(result?.properties.other).toBe("token=abc");
    expect(result?.properties.$referrer).toBe("https://mail.example.com/");
  });

  test("passes a dropped event through", () => {
    expect(redactEventUrls(null)).toBeNull();
  });
});

describe("redactCapturedRequest", () => {
  test("hides the token in the URL a replay records, keeping the rest", () => {
    // The recorder passes the page URL as a bare `{ name }`.
    const request = {
      name: "https://onyx.example.com/auth/magic-link?token=abc",
      method: "GET",
    } as CapturedNetworkRequest;

    expect(redactCapturedRequest(request)).toEqual({
      name: "https://onyx.example.com/auth/magic-link?token=redacted",
      method: "GET",
    });
  });
});
