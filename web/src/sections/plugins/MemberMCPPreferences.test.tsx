import { MCPConnectionStatus } from "@/lib/mcp/types";
import useSWR from "swr";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MemberMCPPreferences from "@/sections/plugins/MemberMCPPreferences";
import type { MCPServer, MCPServersResponse } from "@/lib/mcp/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  memberServer,
  jsonResponse,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

const chatLabel = "Enable in main Chat by default";
const craftLabel = "Enable in Craft by default";
let mockCraftEnabled: boolean | undefined = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_enabled: mockCraftEnabled }),
}));

beforeEach(() => {
  mockCraftEnabled = true;
});

function CachedRoster({ cacheKey }: { cacheKey: string }) {
  const { data } = useSWR<MCPServersResponse>(cacheKey, null);
  return (
    <output aria-label={cacheKey}>{JSON.stringify(data?.mcp_servers)}</output>
  );
}

function show(server: MCPServer = memberServer(), surface?: "all" | "craft") {
  const lists = [
    SWR_KEYS.mcpServers,
    SWR_KEYS.mcpServersCraft,
    SWR_KEYS.agentMcpServers(0),
  ];
  return render(
    <>
      <MemberMCPPreferences server={server} surface={surface} />
      {lists.map((cacheKey) => (
        <CachedRoster key={cacheKey} cacheKey={cacheKey} />
      ))}
    </>,
    {
      swrConfig: {
        provider: () =>
          new Map(
            lists.map((key) => [key, { data: { mcp_servers: [server] } }])
          ),
      },
    }
  );
}

afterEach(() => jest.restoreAllMocks());

test.each([false, undefined])(
  "Craft defaults stay hidden when Craft access is %s while Chat remains available",
  (enabled) => {
    mockCraftEnabled = enabled;
    show();
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    );
    expect(
      screen.queryByRole("switch", { name: craftLabel })
    ).not.toBeInTheDocument();
  }
);

test("each personal default sends one PATCH across multiple cached lists and retains credentials", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(
      jsonResponse({ enabled_in_chat: false, enabled_in_craft: true })
    )
    .mockResolvedValueOnce(
      jsonResponse({ enabled_in_chat: false, enabled_in_craft: false })
    );
  show(memberServer({ user_credentials: { api_key: "retained-credential" } }));
  const user = setupUser();
  await user.click(screen.getByRole("switch", { name: chatLabel }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    )
  );
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(screen.getByRole("switch", { name: craftLabel })).toBeChecked();
  expect(requests).toHaveBeenCalledTimes(1);
  expect(requests).toHaveBeenLastCalledWith("/api/mcp/server/7/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled_in_chat: false }),
  });
  for (const key of [
    SWR_KEYS.mcpServers,
    SWR_KEYS.mcpServersCraft,
    SWR_KEYS.agentMcpServers(0),
  ]) {
    expect(screen.getByLabelText(key)).toHaveTextContent(
      '"user_enabled_in_chat":false'
    );
    expect(screen.getByLabelText(key)).toHaveTextContent(
      '"api_key":"retained-credential"'
    );
  }
  await user.click(screen.getByRole("switch", { name: craftLabel }));
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: craftLabel })
    ).not.toHaveAttribute("aria-disabled")
  );
  expect(requests).toHaveBeenCalledTimes(2);
  expect(requests).toHaveBeenLastCalledWith("/api/mcp/server/7/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled_in_craft: false }),
  });
});

test("a pending save is optimistic, failure restores every list, and retry succeeds", async () => {
  const first = deferred<Response>();
  const requests = jest
    .spyOn(global, "fetch")
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce(
      jsonResponse({ enabled_in_chat: false, enabled_in_craft: true })
    );
  show();
  const user = setupUser();
  await user.click(screen.getByRole("switch", { name: chatLabel }));
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(screen.getByRole("switch", { name: chatLabel })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
  await user.click(screen.getByRole("switch", { name: chatLabel }));
  expect(requests).toHaveBeenCalledTimes(1);
  await act(async () =>
    first.resolve(jsonResponse({ detail: "Save failed" }, 500))
  );
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("switch", { name: chatLabel })).toBeChecked();
  for (const key of [
    SWR_KEYS.mcpServers,
    SWR_KEYS.mcpServersCraft,
    SWR_KEYS.agentMcpServers(0),
  ]) {
    expect(screen.getByLabelText(key)).not.toHaveTextContent(
      '"user_enabled_in_chat":false'
    );
  }
  await user.click(screen.getByRole("switch", { name: chatLabel }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    )
  );
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(requests).toHaveBeenCalledTimes(2);
});

test("workspace flags disable personal toggles without writing", async () => {
  const requests = jest.spyOn(global, "fetch");
  show(
    memberServer({ default_chat_enabled: false, available_in_craft: false })
  );
  expect(
    screen.getByText("Your admin has disabled this plugin for Craft.")
  ).toBeVisible();
  expect(
    screen.getByText("Your admin has disabled this plugin for Main Chat.")
  ).toBeVisible();
  const user = setupUser();
  for (const label of [chatLabel, craftLabel]) {
    const control = screen.getByRole("switch", { name: label });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toBeChecked();
    await user.click(control);
  }
  expect(requests).not.toHaveBeenCalled();
});

test("members can save defaults before signing in and Craft shows only its default", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      jsonResponse({ enabled_in_chat: true, enabled_in_craft: false })
    );
  show(
    memberServer({ connection_status: MCPConnectionStatus.NOT_CONNECTED }),
    "craft"
  );
  expect(
    screen.queryByRole("switch", { name: chatLabel })
  ).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("switch", { name: craftLabel }));
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: craftLabel })
    ).not.toHaveAttribute("aria-disabled")
  );
  expect(requests).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("switch", { name: craftLabel })).not.toBeChecked();
});

test("saving keeps unloaded and nonmatching agent rosters unchanged", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      jsonResponse({ enabled_in_chat: false, enabled_in_craft: true })
    );
  const matching = SWR_KEYS.agentMcpServers(0);
  const unrelated = SWR_KEYS.agentMcpServers(99);
  const unloaded = SWR_KEYS.agentMcpServers(100);
  function SavePreference() {
    useSWR<MCPServersResponse>(matching, null);
    useSWR<MCPServersResponse>(unrelated, null);
    useSWR<MCPServersResponse>(unloaded, null);
    return <MemberMCPPreferences server={memberServer()} />;
  }
  const cache = new Map<string, { data?: MCPServersResponse }>([
    [
      matching,
      { data: { assistant_id: "default", mcp_servers: [memberServer()] } },
    ],
    [
      unrelated,
      {
        data: {
          assistant_id: "custom",
          mcp_servers: [memberServer({ id: 8 })],
        },
      },
    ],
    [unloaded, {}],
  ]);
  render(<SavePreference />, { swrConfig: { provider: () => cache } });
  await setupUser().click(screen.getByRole("switch", { name: chatLabel }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    )
  );
  expect(cache.get(matching)?.data?.assistant_id).toBe("default");
  expect(cache.get(unrelated)?.data).toEqual({
    assistant_id: "custom",
    mcp_servers: [memberServer({ id: 8 })],
  });
  expect(cache.get(unloaded)?.data).toBeUndefined();
  expect(requests).toHaveBeenCalledTimes(1);
});
