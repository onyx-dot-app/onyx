import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ConnectAiTools from "@/sections/oauth-provider/ConnectAiTools";
import messages from "@/i18n/messages/en.json";
import { downloadFile } from "@/lib/download";
import type { Settings } from "@/lib/settings/types";
import { mockFetch } from "@tests/setup/integrationTestUtils";

const copy = messages.mcpOAuth.connectTools;
const MCP_URL = "https://onyx.example.com/mcp/";

let mockSettings: Pick<
  Settings,
  "onyx_mcp_url" | "onyx_plugin_export_enabled"
> = {};

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => mockSettings,
}));
jest.mock("@/lib/download", () => ({ downloadFile: jest.fn() }));

afterEach(() => jest.restoreAllMocks());

test("copies the MCP URL, downloads the plugin and links the guides", async () => {
  mockSettings = { onyx_mcp_url: MCP_URL, onyx_plugin_export_enabled: true };
  mockFetch({ "/api/plugins/onyx-plugin/export": new Response("zip") });
  const user = setupUser();
  render(<ConnectAiTools />);

  expect(screen.getByText(MCP_URL)).toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://docs.onyx.app/overview/onyx_anywhere/mcp_server#connect-your-ai-tools"
  );

  const writeText = jest
    .spyOn(navigator.clipboard, "writeText")
    .mockResolvedValue();
  await user.click(screen.getByRole("button", { name: copy.mcpUrl.copy }));
  expect(writeText).toHaveBeenCalledWith(MCP_URL);

  await user.click(screen.getByRole("button", { name: copy.plugin.download }));
  await waitFor(() =>
    expect(downloadFile).toHaveBeenCalledWith(
      "onyx-plugin.zip",
      expect.objectContaining({ content: expect.anything() })
    )
  );
});

test("leaves the plugin out when the image holds no plugin files", () => {
  mockSettings = { onyx_mcp_url: MCP_URL, onyx_plugin_export_enabled: false };
  render(<ConnectAiTools />);

  expect(screen.getByText(MCP_URL)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.plugin.download })
  ).not.toBeInTheDocument();
});

test("renders nothing without the OAuth provider", () => {
  mockSettings = { onyx_mcp_url: null };
  const { container } = render(<ConnectAiTools />);

  expect(container).toBeEmptyDOMElement();
});
