import type { NextRequest } from "next/server";
import { cookies } from "next/headers";
import { GET } from "@/app/admin/connectors/[connector]/auth/callback/route";

jest.mock("next/headers", () => ({ cookies: jest.fn() }));
jest.mock("@/lib/redirectSS", () => ({
  getDomain: () => "https://tritongpt-canvas-dev.ucsd.edu",
}));
jest.mock("@/lib/utilsSS", () => ({
  buildUrl: (path: string) => `https://backend.example${path}`,
}));
jest.mock("@/lib/userSS", () => ({
  processCookies: () => "auth=regular-session",
}));

const mockFetch = jest.fn();

function callbackRequest(state: string): NextRequest {
  const url = new URL(
    `https://tritongpt-canvas-dev.ucsd.edu/admin/connectors/google-drive/auth/callback?code=google-code&state=${state}`
  );
  return { url: url.toString(), nextUrl: url } as NextRequest;
}

beforeEach(() => {
  jest.mocked(cookies).mockResolvedValue({
    get: () => undefined,
  } as never);
  mockFetch.mockResolvedValue({ ok: true });
  global.fetch = mockFetch as unknown as typeof fetch;
});

afterEach(() => {
  mockFetch.mockReset();
});

it("finishes Canvas Google Drive OAuth without a popup session cookie", async () => {
  const response = await GET(
    callbackRequest("lti_google_drive_one-time-state")
  );

  expect(mockFetch).toHaveBeenCalledWith(
    new URL("https://backend.example/auth/lti/google-drive/callback"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: "google-code",
        state: "lti_google_drive_one-time-state",
      }),
    }
  );
  expect(await response.text()).toContain('status: "success"');
});

it("keeps the regular Google Drive callback on its existing path", async () => {
  await GET(callbackRequest("regular-admin-state"));

  expect(mockFetch).toHaveBeenCalledWith(
    "https://backend.example/manage/connector/google-drive/callback?code=google-code&state=regular-admin-state",
    { headers: { cookie: "auth=regular-session" } }
  );
});
