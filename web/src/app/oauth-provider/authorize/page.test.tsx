import { notFound, redirect } from "next/navigation";
import { getCurrentUserSS } from "@/lib/users/svcSS";
import Page from "@/app/oauth-provider/authorize/page";
import OAuthProviderConsent from "@/sections/oauth-provider/OAuthProviderConsent";

jest.mock("next/navigation", () => ({
  notFound: jest.fn(() => {
    throw new Error("notFound");
  }),
  redirect: jest.fn((location: string) => {
    throw new Error(`redirect:${location}`);
  }),
}));

jest.mock("@/lib/users/svcSS", () => ({
  getCurrentUserSS: jest.fn(),
}));

const mockGetCurrentUserSS = jest.mocked(getCurrentUserSS);
const requestId = "a".repeat(43);

afterEach(() => {
  jest.clearAllMocks();
});

test.each([undefined, "bad", ["a".repeat(43)]])(
  "rejects malformed request identifiers: %p",
  async (request) => {
    await expect(
      Page({
        searchParams: Promise.resolve({ request }),
      })
    ).rejects.toThrow("notFound");

    expect(notFound).toHaveBeenCalledTimes(1);
    expect(mockGetCurrentUserSS).not.toHaveBeenCalled();
  }
);

test("redirects signed-out users back to the pending authorization", async () => {
  mockGetCurrentUserSS.mockResolvedValue(null);

  await expect(
    Page({
      searchParams: Promise.resolve({ request: requestId }),
    })
  ).rejects.toThrow(
    `redirect:/auth/login?next=%2Foauth-provider%2Fauthorize%3Frequest%3D${requestId}`
  );

  expect(redirect).toHaveBeenCalledWith(
    `/auth/login?next=%2Foauth-provider%2Fauthorize%3Frequest%3D${requestId}`
  );
});

test("renders consent for signed-in users", async () => {
  mockGetCurrentUserSS.mockResolvedValue({
    id: "user-id",
  } as Awaited<ReturnType<typeof getCurrentUserSS>>);

  const page = await Page({
    searchParams: Promise.resolve({ request: requestId }),
  });

  expect(page.type).toBe(OAuthProviderConsent);
  expect(page.props).toEqual({ requestId, userId: "user-id" });
});
