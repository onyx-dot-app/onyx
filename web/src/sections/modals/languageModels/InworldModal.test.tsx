import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import InworldModal from "@/sections/modals/languageModels/InworldModal";
import type { LLMProviderView } from "@/lib/languageModels/types";

const catalog = [
  {
    name: "auto",
    display_name: "Auto",
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    is_router: true,
  },
  {
    name: "openai/gpt-5-mini",
    display_name: "gpt-5-mini",
    max_input_tokens: 400000,
    supports_image_input: true,
    supports_reasoning: true,
    is_router: false,
  },
];

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Inworld provider setup", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/inworld/available-models")) {
          return jsonResponse(catalog);
        }
        if (url.includes("/built-in/options/")) {
          return jsonResponse({ name: "inworld", known_models: [] });
        }
        if (init?.method === "PUT") {
          return jsonResponse({ id: 42, provider: "inworld" });
        }
        return jsonResponse({ providers: [] });
      });
  });

  afterEach(() => jest.restoreAllMocks());

  it("discovers models, tests the connection, and saves an Inworld provider", async () => {
    const user = setupUser();
    const onSuccess = jest.fn();
    render(<InworldModal variant="onboarding" onSuccess={onSuccess} />);

    expect(
      screen.getByDisplayValue("https://api.inworld.ai/v1")
    ).toBeInTheDocument();
    await user.type(
      await screen.findByLabelText(/API key/i),
      "inworld-test-key"
    );
    await user.click(screen.getByRole("button", { name: "Refresh models" }));
    expect(await screen.findByText("gpt-5-mini")).toBeInTheDocument();
    const connect = screen.getByRole("button", { name: "Connect" });
    await waitFor(() => expect(connect).toBeEnabled());
    await user.click(connect);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/test",
      expect.objectContaining({
        body: expect.stringContaining('"provider":"inworld"'),
      })
    );
    const saveCall = fetchSpy.mock.calls.find(
      ([, init]) => init?.method === "PUT"
    );
    expect(saveCall?.[1]?.body).toEqual(
      expect.stringContaining('"api_base":"https://api.inworld.ai/v1"')
    );
    expect(saveCall?.[1]?.body).toEqual(
      expect.stringContaining('"is_router":true')
    );
  });

  it("refreshes saved credentials without selecting newly discovered models", async () => {
    const existing: LLMProviderView = {
      id: 42,
      name: "Inworld",
      provider: "inworld",
      api_key: "inw-...key",
      api_base: "https://api.inworld.ai/v1",
      api_version: null,
      deployment_name: null,
      custom_config: null,
      is_public: true,
      is_auto_mode: false,
      groups: [],
      personas: [],
      model_configurations: [
        {
          ...catalog[1]!,
          is_visible: true,
          custom_display_name: "My model",
          effectiveDisplayName: "My model",
        },
      ],
    };
    const user = setupUser();
    const onSuccess = jest.fn();
    render(
      <InworldModal
        variant="onboarding"
        existingLlmProvider={existing}
        onSuccess={onSuccess}
      />
    );

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/inworld/available-models",
        expect.objectContaining({
          body: JSON.stringify({
            api_base: "https://api.inworld.ai/v1",
            api_key: "inw-...key",
            provider_id: 42,
          }),
        })
      )
    );
    const save = screen.getByRole("button", { name: "Update" });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const saveCall = fetchSpy.mock.calls.find(
      ([, init]) => init?.method === "PUT"
    );
    const body = JSON.parse(saveCall?.[1]?.body ?? "{}");
    expect(body.api_key).toBeUndefined();
    expect(body.api_key_changed).toBe(false);
    expect(body.model_configurations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "auto", is_visible: false }),
        expect.objectContaining({
          name: "openai/gpt-5-mini",
          is_visible: true,
          custom_display_name: "My model",
        }),
      ])
    );
  });

  it("keeps connection disabled when model discovery fails", async () => {
    fetchSpy.mockImplementation(async (input) =>
      String(input).endsWith("/inworld/available-models")
        ? jsonResponse({ detail: "Invalid Inworld key" }, 400)
        : jsonResponse({ name: "inworld", known_models: [], providers: [] })
    );
    const user = setupUser();
    render(<InworldModal variant="onboarding" />);
    await user.type(await screen.findByLabelText(/API key/i), "invalid-key");
    await user.click(screen.getByRole("button", { name: "Refresh models" }));
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(
      false
    );
  });
});
