import { render, screen, setupUser } from "@tests/setup/test-utils";
import MemberMCPPreferences from "@/sections/plugins/MemberMCPPreferences";
import { memberServer } from "@/sections/plugins/__tests__/memberPluginFixtures";

const chatLabel = "Enable in default Chat";
const craftLabel = "Enable in Craft";
let mockCraftEnabled: boolean | undefined = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_enabled: mockCraftEnabled }),
}));

beforeEach(() => {
  mockCraftEnabled = true;
});
afterEach(() => jest.restoreAllMocks());

test("switches report draft changes without requests and render controlled values", async () => {
  const requests = jest.spyOn(global, "fetch");
  const onChange = jest.fn();
  const server = memberServer();
  const { rerender } = render(
    <MemberMCPPreferences
      server={server}
      values={{ enabled_in_chat: true, enabled_in_craft: true }}
      onChange={onChange}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("switch", { name: chatLabel }));
  expect(onChange).toHaveBeenLastCalledWith({ enabled_in_chat: false });
  expect(screen.getByRole("switch", { name: chatLabel })).toBeChecked();
  rerender(
    <MemberMCPPreferences
      server={server}
      values={{ enabled_in_chat: false }}
      onChange={onChange}
    />
  );
  expect(screen.getByRole("switch", { name: chatLabel })).not.toBeChecked();
  expect(screen.getByRole("switch", { name: craftLabel })).toBeChecked();
  await user.click(screen.getByRole("switch", { name: craftLabel }));
  expect(onChange).toHaveBeenLastCalledWith({ enabled_in_craft: false });
  expect(requests).not.toHaveBeenCalled();
});

test.each([false, undefined])(
  "Craft access %s hides its preference",
  (enabled) => {
    mockCraftEnabled = enabled;
    render(
      <MemberMCPPreferences
        server={memberServer()}
        values={{ enabled_in_chat: true, enabled_in_craft: true }}
        onChange={jest.fn()}
      />
    );
    expect(screen.getByRole("switch", { name: chatLabel })).toBeChecked();
    expect(
      screen.queryByRole("switch", { name: craftLabel })
    ).not.toBeInTheDocument();
  }
);

test("Craft surface shows only its preference", () => {
  render(
    <MemberMCPPreferences
      server={memberServer()}
      surface="craft"
      values={{ enabled_in_chat: true, enabled_in_craft: true }}
      onChange={jest.fn()}
    />
  );
  expect(
    screen.queryByRole("switch", { name: chatLabel })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("switch", { name: craftLabel })).toBeChecked();
});

test.each([true, false])(
  "disabled or unavailable controls never change preferences (%s)",
  async (disabled) => {
    const onChange = jest.fn();
    render(
      <MemberMCPPreferences
        server={memberServer({
          default_chat_enabled: disabled,
          available_in_craft: disabled,
        })}
        values={{ enabled_in_chat: true, enabled_in_craft: true }}
        onChange={onChange}
        disabled={disabled}
      />
    );
    for (const label of [chatLabel, craftLabel]) {
      const control = screen.getByRole("switch", { name: label });
      expect(control).toHaveAttribute("aria-disabled", "true");
      await setupUser().click(control);
    }
    expect(onChange).not.toHaveBeenCalled();
  }
);
