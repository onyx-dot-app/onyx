import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import type { ChatShortcutActions } from "@/lib/shortcuts/hooks";
import ChatShortcuts, {
  useChatJumpHint,
} from "@/sections/sidebar/ChatShortcuts";

const mockActions: ChatShortcutActions = {
  newChat: jest.fn(),
  resetNewSession: jest.fn(),
  toggleModelPicker: jest.fn(),
  previousChat: jest.fn(),
  nextChat: jest.fn(),
  jumpToChat: jest.fn(),
};

jest.mock("@/lib/shortcuts/hooks", () => ({
  useChatShortcutActions: () => mockActions,
}));

beforeEach(() => jest.clearAllMocks());

test("Ctrl+Alt reveals chat jump hints until release or window blur", async () => {
  function Hints() {
    const { modifier } = useChatJumpHint();
    return modifier ? <span>{modifier}</span> : null;
  }

  render(
    <>
      <ChatShortcuts />
      <Hints />
    </>
  );
  const user = setupUser();

  await user.keyboard("{Control>}");
  expect(screen.queryByText("ctrl+alt")).not.toBeInTheDocument();
  await user.keyboard("{Alt>}");
  expect(screen.getByText("ctrl+alt")).toBeInTheDocument();
  await user.keyboard("9");
  expect(mockActions.jumpToChat).toHaveBeenCalledWith(8);
  await user.keyboard("{/Alt}");
  expect(screen.queryByText("ctrl+alt")).not.toBeInTheDocument();
  await user.keyboard("{Alt>}");
  expect(screen.getByText("ctrl+alt")).toBeInTheDocument();
  fireEvent.blur(window);
  expect(screen.queryByText("ctrl+alt")).not.toBeInTheDocument();
});

describe("while a modal is open", () => {
  test("no chat shortcut runs", async () => {
    render(
      <>
        <ChatShortcuts />
        <DialogPrimitive.Root open>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Content aria-describedby={undefined}>
              <VisuallyHidden.Root asChild>
                <DialogPrimitive.Title>Palette</DialogPrimitive.Title>
              </VisuallyHidden.Root>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>
      </>
    );

    await setupUser().keyboard("{Control>}/{/Control}");

    expect(mockActions.toggleModelPicker).not.toHaveBeenCalled();
  });

  test("without a modal, the chat shortcut runs", async () => {
    render(<ChatShortcuts />);

    await setupUser().keyboard("{Control>}/{/Control}");

    expect(mockActions.toggleModelPicker).toHaveBeenCalledTimes(1);
  });
});

describe("Alt+Up and Alt+Down", () => {
  test("do not switch chats from a text field", async () => {
    render(
      <>
        <ChatShortcuts />
        <textarea aria-label="Message" />
      </>
    );
    const user = setupUser();

    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.keyboard("{Alt>}{ArrowUp}{ArrowDown}{/Alt}");

    expect(mockActions.previousChat).not.toHaveBeenCalled();
    expect(mockActions.nextChat).not.toHaveBeenCalled();
  });

  test("switch chats from the page", async () => {
    render(<ChatShortcuts />);

    await setupUser().keyboard("{Alt>}{ArrowUp}{ArrowDown}{/Alt}");

    expect(mockActions.previousChat).toHaveBeenCalledTimes(1);
    expect(mockActions.nextChat).toHaveBeenCalledTimes(1);
  });
});
