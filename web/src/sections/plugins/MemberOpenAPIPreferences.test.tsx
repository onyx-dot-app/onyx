import { render, screen, setupUser } from "@tests/setup/test-utils";
import MemberOpenAPIPreferences from "@/sections/plugins/MemberOpenAPIPreferences";
import { memberTool } from "@/sections/plugins/__tests__/memberPluginFixtures";

const chatLabel = "Enable in default Chat";
afterEach(() => jest.restoreAllMocks());

test("switch reports a draft change without requests and renders controlled values", async () => {
  const requests = jest.spyOn(global, "fetch");
  const onChange = jest.fn();
  const tool = memberTool();
  const { rerender } = render(
    <MemberOpenAPIPreferences
      tool={tool}
      values={{ enabled_in_chat: true }}
      onChange={onChange}
    />
  );
  const control = screen.getByRole("switch", { name: chatLabel });
  await setupUser().click(control);
  expect(onChange).toHaveBeenCalledWith({ enabled_in_chat: false });
  expect(control).toBeChecked();
  expect(requests).not.toHaveBeenCalled();
  rerender(
    <MemberOpenAPIPreferences
      tool={tool}
      values={{ enabled_in_chat: false }}
      onChange={onChange}
    />
  );
  expect(control).not.toBeChecked();
});

test.each([false, undefined])(
  "workspace availability %s locks personal control",
  async (default_chat_enabled) => {
    const onChange = jest.fn();
    render(
      <MemberOpenAPIPreferences
        tool={memberTool({ default_chat_enabled })}
        values={{ enabled_in_chat: true }}
        onChange={onChange}
      />
    );
    const control = screen.getByRole("switch", { name: chatLabel });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toBeChecked();
    await setupUser().hover(control);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Your admin has disabled this plugin for Main Chat."
    );
    await setupUser().click(control);
    expect(onChange).not.toHaveBeenCalled();
  }
);

test("parent disables editing while saving", async () => {
  const onChange = jest.fn();
  render(
    <MemberOpenAPIPreferences
      tool={memberTool()}
      values={{ enabled_in_chat: true }}
      onChange={onChange}
      disabled
    />
  );
  const control = screen.getByRole("switch", { name: chatLabel });
  expect(control).toHaveAttribute("aria-disabled", "true");
  await setupUser().click(control);
  expect(onChange).not.toHaveBeenCalled();
});
