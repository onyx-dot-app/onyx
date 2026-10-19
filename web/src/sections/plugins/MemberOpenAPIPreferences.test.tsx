import useSWR from "swr";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import MemberOpenAPIPreferences from "@/sections/plugins/MemberOpenAPIPreferences";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  memberTool,
  jsonResponse,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

const chatLabel = "Enable in main Chat by default";

function CachedTools() {
  const { data } = useSWR<ToolSnapshot[]>(SWR_KEYS.tools, null);
  return <output aria-label="Cached tools">{JSON.stringify(data)}</output>;
}

function show(tool: ToolSnapshot = memberTool(), cached = true) {
  return render(
    <>
      <MemberOpenAPIPreferences tool={tool} />
      <CachedTools />
    </>,
    {
      swrConfig: {
        provider: () =>
          new Map(
            cached
              ? [[SWR_KEYS.tools, { data: [tool, memberTool({ id: 8 })] }]]
              : []
          ),
      },
    }
  );
}

afterEach(() => jest.restoreAllMocks());

test("saves one personal preference without changing workspace availability or credentials", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({ enabled_in_chat: false }));
  const tool = memberTool({
    custom_headers: [{ key: "Authorization", value: "retained-credential" }],
  });
  show(tool);
  expect(screen.getByRole("switch", { name: chatLabel })).toBeChecked();
  await setupUser().click(screen.getByRole("switch", { name: chatLabel }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    )
  );
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(requests).toHaveBeenCalledTimes(1);
  expect(requests).toHaveBeenCalledWith("/api/tool/7/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled_in_chat: false }),
  });
  expect(
    JSON.parse(screen.getByLabelText("Cached tools").textContent ?? "[]")
  ).toEqual([{ ...tool, user_enabled_in_chat: false }, memberTool({ id: 8 })]);
});

test("pending saves lock the switch, rollback on error, and allow retry", async () => {
  const first = deferred<Response>();
  const requests = jest
    .spyOn(global, "fetch")
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce(jsonResponse({ enabled_in_chat: false }));
  show();
  const user = setupUser();
  const control = screen.getByRole("switch", { name: chatLabel });
  await user.click(control);
  expect(control).not.toBeChecked();
  expect(control).toHaveAttribute("aria-disabled", "true");
  await user.click(control);
  expect(requests).toHaveBeenCalledTimes(1);
  await act(async () => first.resolve(jsonResponse({ detail: "Failed" }, 500)));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(control).toBeChecked();
  expect(control).not.toHaveAttribute("aria-disabled");
  await user.click(control);
  await waitFor(() => expect(control).not.toHaveAttribute("aria-disabled"));
  expect(control).not.toBeChecked();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(requests).toHaveBeenCalledTimes(2);
});

test.each([false, undefined])(
  "admin Chat availability %s locks personal control without writes",
  async (default_chat_enabled) => {
    const requests = jest.spyOn(global, "fetch");
    show(memberTool({ default_chat_enabled }));
    const control = screen.getByRole("switch", { name: chatLabel });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toBeChecked();
    expect(
      screen.getByText("Your admin has disabled this plugin for Main Chat.")
    ).toBeVisible();
    await setupUser().click(control);
    expect(requests).not.toHaveBeenCalled();
  }
);

test("standalone details seed their cache and persist before OAuth without extra fetches", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({ enabled_in_chat: false }));
  show(memberTool({ oauth_config_id: 3 }), false);
  expect(requests).not.toHaveBeenCalled();
  await setupUser().click(screen.getByRole("switch", { name: chatLabel }));
  await waitFor(() =>
    expect(screen.getByRole("switch", { name: chatLabel })).not.toHaveAttribute(
      "aria-disabled"
    )
  );
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(requests).toHaveBeenCalledTimes(1);
});

test("cached workspace and personal flags override a stale detail prop", () => {
  const tool = memberTool();
  render(<MemberOpenAPIPreferences tool={tool} />, {
    swrConfig: {
      provider: () =>
        new Map([
          [
            SWR_KEYS.tools,
            { data: [{ ...tool, user_enabled_in_chat: false }] },
          ],
        ]),
    },
  });
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
});
