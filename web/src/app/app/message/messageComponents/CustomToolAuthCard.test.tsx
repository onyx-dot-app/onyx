import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import type { ToolSnapshot } from "@/lib/tools/types";

jest.mock("swr", () => ({
  __esModule: true,
  default: () => ({ data: [], isLoading: false, mutate: jest.fn() }),
  SWRConfig: ({ children }: { children: React.ReactNode }) => children,
}));

const tool: ToolSnapshot = {
  id: 1,
  name: "example",
  display_name: "Example",
  description: "Example tool",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  oauth_config_id: 1,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
};

afterEach(() => jest.restoreAllMocks());

test.each([true, false])(
  "reports an OAuth failure without logging response details (ok=%s)",
  async (ok) => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue({
      ok,
      json: async () => ({
        authorization_url: "javascript:alert(1)",
        state: "test",
        detail: "private-response-marker",
      }),
    } as Response);
    const errorLog = jest.spyOn(console, "error").mockImplementation(() => {});
    const errorToast = jest.spyOn(toast, "error").mockReturnValue("test-toast");
    const originalLocation = window.location.href;
    const user = setupUser();
    render(
      <CustomToolAuthCard
        toolName="Example"
        toolId={1}
        tools={[tool]}
        agentId={1}
      />
    );
    await user.click(screen.getByRole("button", { name: /connect/i }));
    await waitFor(() =>
      expect(errorToast).toHaveBeenCalledWith(
        "An error occurred during the OAuth process. Please try again."
      )
    );
    expect(errorLog.mock.calls).toEqual([
      ["[useToolOAuthStatus] OAuth initiation failed"],
    ]);
    expect(window.location.href).toBe(originalLocation);
    expect(screen.getByRole("button", { name: /connect/i })).toBeEnabled();
  }
);
