import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import Page from "@/app/admin/document-processing/page";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/document-processing",
}));

afterEach(() => jest.restoreAllMocks());

it("saves the document processing key in JSON instead of the URL", async () => {
  const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => false,
  } as Response);
  const user = setupUser();
  render(<Page />);
  await user.type(await screen.findByRole("textbox"), "test-key&value");
  await user.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search-settings/upsert-unstructured-api-key",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unstructured_api_key: "test-key&value" }),
      }
    );
  });
});

it.each(["", "   "])("prevents blank API key submissions (%j)", async (key) => {
  const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => false,
  } as Response);
  const user = setupUser();
  render(<Page />);
  const input = await screen.findByRole("textbox");
  if (key) await user.type(input, key);
  const save = screen.getByRole("button", { name: /save/i });
  await user.click(save);
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/search-settings/upsert-unstructured-api-key",
    expect.anything()
  );
  await user.type(input, "test-key");
  await user.clear(input);
  await user.click(save);
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/search-settings/upsert-unstructured-api-key",
    expect.anything()
  );
});
