import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import NaceModal from "@/sections/modals/languageModels/NaceModal";
import { PointerEventsCheckLevel } from "@testing-library/user-event";

jest.mock("@/lib/languageModels/hooks", () => ({
  useWellKnownLLMProvider: () => ({ wellKnownLLMProvider: undefined }),
  useAdminLanguageModels: () => ({ defaultText: undefined }),
}));

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

describe("Nace provider setup", () => {
  afterEach(() => jest.restoreAllMocks());

  it("discovers Drex models and saves credentials without assigning a chat default", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            String(url).endsWith("available-models")
              ? [
                  {
                    name: "drex-max",
                    display_name: "drex-max",
                    supports_chat: false,
                    supports_decisions: true,
                    supports_image_input: false,
                    max_input_tokens: null,
                  },
                  {
                    name: "drex-v2.0",
                    display_name: "drex-v2.0",
                    supports_chat: false,
                    supports_decisions: true,
                    supports_image_input: false,
                    max_input_tokens: null,
                  },
                ]
              : { id: 42 }
          ),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );
    const onSuccess = jest.fn();
    render(<NaceModal shouldMarkAsDefault onSuccess={onSuccess} />);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    expect(screen.queryByLabelText(/API base/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/API key/i), "nace-test-key");
    await user.click(screen.getByRole("button", { name: "Refresh models" }));
    expect(await screen.findByText("drex-max")).toBeInTheDocument();
    expect(screen.getByText("drex-v2.0")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/nace/available-models",
      expect.objectContaining({
        body: JSON.stringify({ api_key: "nace-test-key" }),
      })
    );
    await user.click(screen.getByRole("button", { name: "Select All" }));
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/decision-provider/test",
      expect.objectContaining({
        body: expect.stringContaining('"model":"drex-max"'),
      })
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/decision-provider",
      expect.objectContaining({
        body: expect.stringContaining('"provider":"nace"'),
      })
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/decision-provider",
      expect.objectContaining({
        body: expect.stringContaining(
          '"selected_model_names":["drex-max","drex-v2.0"]'
        ),
      })
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/admin/llm/default",
      expect.anything()
    );
    expect(screen.queryByText("Auto-update models")).not.toBeInTheDocument();
  });
});
