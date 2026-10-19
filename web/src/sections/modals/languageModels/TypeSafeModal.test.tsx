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

  it.each([false, true])(
    "updates a provider with all decision models hidden (rotate key: %s)",
    async (rotateKey) => {
      const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(
        async () =>
          new Response(JSON.stringify({ id: 42 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
      );
      const onSuccess = jest.fn();
      render(
        <TypeSafeModal
          existingLlmProvider={{
            id: 42,
            name: "TypeSafe AI",
            provider: "typesafe",
            api_key: "********",
            model_configurations: [
              {
                name: "jev-preview",
                is_visible: false,
                supports_chat: false,
                supports_decisions: true,
                supports_image_input: false,
                supports_reasoning: false,
                effectiveDisplayName: "Jev Preview",
                max_input_tokens: null,
              },
            ],
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
      await user.clear(screen.getByLabelText(/display name/i));
      await user.type(
        screen.getByLabelText(/display name/i),
        "Renamed TypeSafe"
      );
      if (rotateKey) {
        await user.clear(screen.getByLabelText(/API key/i));
        await user.type(
          screen.getByLabelText(/API key/i),
          "rotated-typesafe-key"
        );
      } else {
        expect(screen.getByLabelText(/API key/i)).toHaveValue("********");
      }
      await user.click(screen.getByRole("button", { name: "Update" }));
      await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
      const savedBody = fetchSpy.mock.calls.find(
        ([url]) => url === SWR_KEYS.adminLlmProviders
      )?.[1]?.body;
      expect(typeof savedBody).toBe("string");
      expect(JSON.parse(String(savedBody))).toMatchObject({
        name: "Renamed TypeSafe",
        api_key_changed: rotateKey,
        model_configurations: [{ name: "jev-preview", is_visible: false }],
      });
      if (rotateKey) {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            body: expect.stringContaining('"model":"jev-preview"'),
          })
        );
        expect(JSON.parse(String(savedBody))).toHaveProperty(
          "api_key",
          "rotated-typesafe-key"
        );
      } else {
        expect(fetchSpy).not.toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.anything()
        );
        expect(JSON.parse(String(savedBody))).not.toHaveProperty("api_key");
      }
    }
  );

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
