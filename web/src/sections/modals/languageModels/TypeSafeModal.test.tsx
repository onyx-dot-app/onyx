import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import TypeSafeModal from "@/sections/modals/languageModels/TypeSafeModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import { PointerEventsCheckLevel } from "@testing-library/user-event";

jest.mock("@/lib/languageModels/hooks", () => ({
  useWellKnownLLMProvider: () => ({ wellKnownLLMProvider: undefined }),
}));

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

describe("TypeSafe provider setup", () => {
  afterEach(() => jest.restoreAllMocks());

  it("tests System One and saves credentials without assigning a chat default", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 42 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    const onSuccess = jest.fn();
    render(<TypeSafeModal shouldMarkAsDefault onSuccess={onSuccess} />);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    await user.type(screen.getByLabelText(/API key/i), "typesafe-test-key");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/test",
      expect.objectContaining({
        body: expect.stringContaining('"model":"jev-latest"'),
      })
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      `${SWR_KEYS.adminLlmProviders}?is_creation=true`,
      expect.objectContaining({
        body: expect.stringContaining('"model_configurations":[]'),
      })
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/admin/llm/default",
      expect.anything()
    );
    expect(screen.queryByText("Auto-update models")).not.toBeInTheDocument();
  });
});
