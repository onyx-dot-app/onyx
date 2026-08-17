import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { ValidSources } from "@/lib/types";

const SALESFORCE_URL_ERROR =
  "Invalid OAuth configuration: Salesforce URL must use HTTPS";

afterEach(() => {
  jest.restoreAllMocks();
});

test("surfaces the backend OAuth validation error", async () => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      location: { href: "http://localhost:3000/admin/connectors/salesforce" },
    },
  });
  jest.spyOn(global, "fetch").mockResolvedValue({
    ok: false,
    json: jest.fn().mockResolvedValue({ detail: SALESFORCE_URL_ERROR }),
  } as unknown as Response);

  await expect(
    getConnectorOauthRedirectUrl(ValidSources.Salesforce, {
      salesforce_my_domain_url: "company.my.salesforce.com",
    })
  ).rejects.toThrow(SALESFORCE_URL_ERROR);
});
