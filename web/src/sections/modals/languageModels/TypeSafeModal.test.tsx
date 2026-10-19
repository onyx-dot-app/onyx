import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import TypeSafeModal from "@/sections/modals/languageModels/TypeSafeModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import { PointerEventsCheckLevel } from "@testing-library/user-event";

jest.mock("@/lib/languageModels/hooks", () => ({
  useWellKnownLLMProvider: () => ({ wellKnownLLMProvider: undefined }),
  useAdminLanguageModels: () => ({ defaultText: undefined }),
}));

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

describe("TypeSafe provider setup", () => {
  afterEach(() => jest.restoreAllMocks());

  it("discovers decision models and saves credentials without assigning a chat default", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            String(url).endsWith("available-models")
              ? [
                  {
                    name: "jev-latest",
                    display_name: "Jev Latest",
                    supports_chat: false,
                    supports_decisions: true,
                    supports_image_input: false,
                    max_input_tokens: null,
                  },
                  {
                    name: "jev-preview",
                    display_name: "Jev Preview",
                    supports_chat: false,
                    supports_decisions: true,
                    supports_image_input: false,
                    max_input_tokens: null,
                  },
                ]
              : { id: 42 }
          ),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        )
    );
    const onSuccess = jest.fn();
    render(<TypeSafeModal shouldMarkAsDefault onSuccess={onSuccess} />);
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    await user.type(screen.getByLabelText(/API key/i), "typesafe-test-key");
    await user.click(screen.getByRole("button", { name: "Refresh models" }));
    expect(await screen.findByText("Jev Latest")).toBeInTheDocument();
    expect(screen.getByText("Jev Preview")).toBeInTheDocument();
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
        body: expect.stringContaining('"supports_decisions":true'),
      })
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/admin/llm/default",
      expect.anything()
    );
    expect(screen.queryByText("Auto-update models")).not.toBeInTheDocument();
  });

  it("discovers models with stored credentials and never offers a chat default", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            String(url).endsWith("available-models")
              ? [
                  {
                    name: "jev-preview",
                    display_name: "Jev Preview",
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
    render(
      <TypeSafeModal
        existingLlmProvider={{
          id: 42,
          name: "TypeSafe AI",
          provider: "typesafe",
          api_key: "********",
          model_configurations: [],
          is_public: true,
          is_auto_mode: false,
          groups: [],
          personas: [],
          api_base: null,
          api_version: null,
          custom_config: null,
          deployment_name: null,
        }}
        onSuccess={onSuccess}
      />
    );
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    await user.click(screen.getByRole("button", { name: "Refresh models" }));
    expect(await screen.findByText("Jev Preview")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/typesafe/available-models",
      expect.objectContaining({
        body: JSON.stringify({ provider_id: 42 }),
      })
    );
    expect(
      screen.queryByRole("button", { name: /set.*default/i })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Update" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(fetchSpy).toHaveBeenCalledWith(
      SWR_KEYS.adminLlmProviders,
      expect.objectContaining({
        body: expect.stringContaining('"name":"jev-preview"'),
      })
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/admin/llm/default",
      expect.anything()
    );
  });
});
