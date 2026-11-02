import { NextRequest } from "next/server";
import { GET } from "@/app/admin/connectors/[connector]/auth/callback/route";

jest.mock("@/lib/utilsSS", () => ({
  buildUrl: (path: string) => `http://api-server:8080${path}`,
}));

jest.mock("@/lib/redirectSS", () => ({
  getDomain: () => "http://localhost:3000",
}));

jest.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => undefined,
    getAll: () => [{ name: "google_drive_credential_id", value: "42" }],
  }),
}));

afterEach(() => {
  jest.restoreAllMocks();
});

it.each(["google-drive", "gmail"])(
  "routes %s callbacks by path when both Google scopes are returned",
  async (connector) => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));
    const query = new URLSearchParams({
      code: "auth-code",
      state: "oauth-state",
      scope:
        "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.readonly",
    });
    const request = new NextRequest(
      `http://localhost:3000/admin/connectors/${connector}/auth/callback?${query}`
    );

    const response = await GET(request, {
      params: Promise.resolve({ connector }),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      `http://api-server:8080/manage/connector/${connector}/callback?${query}`,
      { headers: { cookie: "google_drive_credential_id=42" } }
    );
    expect(response.headers.get("location")).toBe(
      `http://localhost:3000/admin/connectors/${connector}`
    );
  }
);

it("rejects unsupported connectors before calling the backend", async () => {
  const fetchMock = jest.spyOn(global, "fetch");
  const response = await GET(
    new NextRequest(
      "http://localhost:3000/admin/connectors/unknown/auth/callback"
    ),
    { params: Promise.resolve({ connector: "unknown" }) }
  );

  expect(response.status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
});
