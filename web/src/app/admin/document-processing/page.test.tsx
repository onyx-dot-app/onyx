import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import Page from "@/app/admin/document-processing/page";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/document-processing",
}));

afterEach(() => jest.restoreAllMocks());

const UPSERT_URL = "/api/search-settings/upsert-unstructured-api-key";

function mockFetch() {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body: unknown = url.includes("unstructured-api-key-set")
        ? { is_set: false, api_key_masked: null, api_token_id: null }
        : url.includes("/api/admin/api-tokens")
          ? []
          : null;
      return { ok: true, json: async () => body } as Response;
    });
}

it("saves the document processing key in JSON instead of the URL", async () => {
  const fetchMock = mockFetch();
  const user = setupUser();
  render(<Page />);
  await user.type(
    await screen.findByPlaceholderText("abc***xyz"),
    "test-key&value"
  );
  await user.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(UPSERT_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: { type: "new", value: "test-key&value" },
      }),
    });
  });
});

it.each(["", "   "])("prevents blank API key submissions (%j)", async (key) => {
  const fetchMock = mockFetch();
  const user = setupUser();
  render(<Page />);
  const input = await screen.findByPlaceholderText("abc***xyz");
  if (key) await user.type(input, key);
  const save = screen.getByRole("button", { name: /save/i });
  await user.click(save);
  expect(fetchMock).not.toHaveBeenCalledWith(UPSERT_URL, expect.anything());
  await user.type(input, "test-key");
  await user.clear(input);
  await user.click(save);
  expect(fetchMock).not.toHaveBeenCalledWith(UPSERT_URL, expect.anything());
});
