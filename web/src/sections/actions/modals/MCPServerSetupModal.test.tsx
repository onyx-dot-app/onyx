import { renderHook } from "@testing-library/react";
import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import {
  MCPModalStory,
  type MCPStoryScenario,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import * as UserProvider from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import messages from "@/i18n/messages/en.json";

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof UserProvider>(
    "@/providers/UserProvider"
  );
  return { ...actual, useUser: jest.fn(actual.useUser) };
});

const confirmationCopy = messages.chat.modals.unsavedChanges;
const setupCopy = messages.actions.mcpSetup;

beforeEach(() => {
  jest
    .mocked(UserProvider.useUser)
    .mockImplementation(
      jest.requireActual<typeof UserProvider>("@/providers/UserProvider")
        .useUser
    );
  const context = renderHook(() => UserProvider.useUser());
  const base = context.result.current;
  context.unmount();
  jest.mocked(UserProvider.useUser).mockReturnValue({
    ...base,
    permissions: [Permission.MANAGE_ACTIONS],
  });
});

async function openDetails(scenario: MCPStoryScenario = { edit: true }) {
  render(<MCPModalStory kind="add" scenario={scenario} />);
  await screen.findByRole("textbox", { name: "Server Name" });
  return setupUser();
}

async function findConfirmation() {
  return screen.findByRole("dialog", { name: confirmationCopy.header.title });
}

test.each(["Cancel", "Close", "Escape", "outside"] as const)(
  "%s asks before discarding changes and cancellation preserves the draft",
  async (action) => {
    const user = await openDetails();
    await user.type(
      screen.getByRole("textbox", { name: "Server Name" }),
      " draft"
    );
    if (action === "Escape") await user.keyboard("{Escape}");
    else if (action === "outside") {
      // JSDOM cannot hit-test the unlabelled overlay; send its outside event.
      fireEvent.pointerDown(document.body, { button: 0, pointerType: "mouse" });
    } else await user.click(screen.getByRole("button", { name: action }));

    const confirmation = await findConfirmation();
    await user.click(
      within(confirmation).getByRole("button", {
        name: confirmationCopy.cancelButton.label,
      })
    );
    expect(
      screen.queryByRole("dialog", { name: confirmationCopy.header.title })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
      "Analytics MCP draft"
    );
  }
);

test.each(["Close", "Escape", "outside"] as const)(
  "%s on the confirmation returns to the same draft without reopening confirmation",
  async (action) => {
    const user = await openDetails();
    const dialog = screen.getByRole("dialog");
    await user.type(
      screen.getByRole("textbox", { name: "Server Name" }),
      " draft"
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await findConfirmation()).toBe(dialog);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    if (action === "Escape") await user.keyboard("{Escape}");
    else if (action === "outside") {
      fireEvent.pointerDown(document.body, { button: 0, pointerType: "mouse" });
    } else {
      await user.click(screen.getByRole("button", { name: "Close" }));
    }
    const name = await screen.findByRole("textbox", { name: "Server Name" });
    expect(name).toHaveValue("Analytics MCP draft");
    expect(screen.getByRole("dialog")).toBe(dialog);
    // Interacting with the restored form must not trigger another close attempt.
    await user.click(name);
    await user.type(name, " retained");
    expect(name).toHaveValue("Analytics MCP draft retained");
    expect(
      screen.queryByRole("dialog", { name: confirmationCopy.header.title })
    ).not.toBeInTheDocument();
  }
);

test("discard closes the dialog and reopening loads saved values", async () => {
  const user = await openDetails();
  await user.type(
    screen.getByRole("textbox", { name: "Server Name" }),
    " draft"
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(
    within(await findConfirmation()).getByRole("button", {
      name: confirmationCopy.discardButton.label,
    })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  await user.click(screen.getByRole("button", { name: "Reopen preview" }));
  expect(
    await screen.findByRole("textbox", { name: "Server Name" })
  ).toHaveValue("Analytics MCP");
});

test("a clean form closes without confirmation", async () => {
  const user = await openDetails();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("a hidden authentication draft still guards closing server configuration", async () => {
  const user = await openDetails({ edit: true, wizard: true });
  await user.click(screen.getByRole("button", { name: setupCopy.continue }));
  await user.click(
    await screen.findByRole("tab", { name: "Use your own OAuth client" })
  );
  await user.type(
    screen.getByRole("textbox", { name: /^Client ID/ }),
    "client-draft"
  );
  await user.click(screen.getByRole("button", { name: setupCopy.back }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(
    within(await findConfirmation()).getByRole("button", {
      name: confirmationCopy.cancelButton.label,
    })
  );
  await user.click(screen.getByRole("button", { name: setupCopy.continue }));
  expect(
    await screen.findByRole("textbox", { name: /^Client ID/ })
  ).toHaveValue("client-draft");
});

test("successfully saved details close without confirmation", async () => {
  const user = await openDetails();
  await user.type(
    screen.getByRole("textbox", { name: "Server Name" }),
    " saved"
  );
  await user.click(screen.getByRole("button", { name: "Save Changes" }));

  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("a failed save preserves the dirty guard", async () => {
  const user = await openDetails({ edit: true, submit: "save-error" });
  await user.type(
    screen.getByRole("textbox", { name: "Server Name" }),
    " unsaved"
  );
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(await findConfirmation()).toBeInTheDocument();
});

test.each(["Cancel", "Close", "Escape"] as const)(
  "%s on delete confirmation retains the server draft",
  async (action) => {
    const user = await openDetails();
    await user.type(
      screen.getByRole("textbox", { name: "Server Name" }),
      " draft"
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const confirmation = await screen.findByRole("dialog", {
      name: messages.actions.mcpCard.deleteModal.title,
    });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    if (action === "Escape") await user.keyboard("{Escape}");
    else
      await user.click(
        within(confirmation).getByRole("button", { name: action })
      );
    expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
      "Analytics MCP draft"
    );
    expect(
      screen.queryByRole("dialog", {
        name: messages.actions.mcpCard.deleteModal.title,
      })
    ).not.toBeInTheDocument();
  }
);

test("confirmed deletion closes the setup after the server delete request", async () => {
  const user = await openDetails();
  const network = jest.spyOn(window, "fetch");
  await user.type(
    screen.getByRole("textbox", { name: "Server Name" }),
    " draft"
  );
  await user.click(screen.getByRole("button", { name: "Delete" }));
  const confirmation = await screen.findByRole("dialog", {
    name: messages.actions.mcpCard.deleteModal.title,
  });
  await user.click(
    within(confirmation).getByRole("button", { name: "Delete" })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(network).toHaveBeenCalledWith(
    "/api/admin/mcp/server/42",
    expect.objectContaining({ method: "DELETE" })
  );
  network.mockRestore();
});
