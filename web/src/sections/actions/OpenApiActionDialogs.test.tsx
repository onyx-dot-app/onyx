/** @jest-environment jsdom */
import {
  act,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Button } from "@opal/components";
import OpenApiActionDialogs from "@/sections/actions/OpenApiActionDialogs";
import type { ToolSnapshot } from "@/lib/tools/types";
import {
  updateCustomTool,
  updateToolStatus,
  validateToolDefinition,
} from "@/lib/tools/svc";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_available: true, appName: "Onyx" }),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: true }),
}));
jest.mock("@/lib/auth/hooks", () => ({
  useOAuthPassThroughEnabled: () => false,
}));
jest.mock("@/lib/tools/svc");

const tool: ToolSnapshot = {
  id: 42,
  name: "API",
  display_name: "API",
  description: "API actions",
  definition: null,
  custom_headers: [{ key: "Authorization", value: "old-secret" }],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: false,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, delete: true, toggle: true, authenticate: true },
};

beforeEach(() => {
  jest
    .mocked(validateToolDefinition)
    .mockResolvedValue({ data: [], error: null });
  jest.mocked(updateCustomTool).mockResolvedValue({ data: tool, error: null });
});

it("keeps the workflow mounted when schema editing advances to authentication", async () => {
  const user = setupUser();
  const onClosed = jest.fn();
  render(
    <OpenApiActionDialogs
      initialTool={tool}
      onChanged={jest.fn()}
      onClosed={onClosed}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Configure authentication" })
  );
  expect(screen.getByDisplayValue("old-secret")).toBeInTheDocument();
  expect(onClosed).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
});

it("saves authentication through the shared workflow and refreshes its owner", async () => {
  const user = setupUser();
  const onChanged = jest.fn();
  const onClosed = jest.fn();
  render(
    <OpenApiActionDialogs
      initialTool={tool}
      onChanged={onChanged}
      onClosed={onClosed}
    />
  );
  await user.click(
    await screen.findByRole("button", { name: "Configure authentication" })
  );
  const secret = screen.getByDisplayValue("old-secret");
  await user.clear(secret);
  await user.type(secret, "new-secret");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() =>
    expect(updateCustomTool).toHaveBeenCalledWith(42, {
      custom_headers: [{ key: "Authorization", value: "new-secret" }],
      passthrough_auth: false,
      oauth_config_id: null,
    })
  );
  expect(onChanged).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
});

it("waits for the refreshed catalog before closing a saved source schema", async () => {
  const user = setupUser();
  let finishRefresh: (() => void) | undefined;
  const refreshed = new Promise<void>((resolve) => {
    finishRefresh = resolve;
  });
  const onChanged = jest.fn(() => refreshed);
  const onClosed = jest.fn();
  render(
    <OpenApiActionDialogs
      initialTool={tool}
      onChanged={onChanged}
      onClosed={onClosed}
    />
  );
  const definition = await screen.findByPlaceholderText(
    "Enter your OpenAPI schema here"
  );
  fireEvent.change(definition, {
    target: {
      value: JSON.stringify({
        openapi: "3.0.3",
        info: { title: "Updated API", version: "1" },
        paths: {},
      }),
    },
  });
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(onClosed).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => {
    finishRefresh?.();
    await refreshed;
  });
  await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
});

it("keeps disconnect open after failure so the admin can retry", async () => {
  const user = setupUser();
  const onClosed = jest.fn();
  const onChanged = jest.fn();
  jest
    .mocked(updateToolStatus)
    .mockRejectedValueOnce(new Error("Disconnect failed"))
    .mockResolvedValueOnce({ updated_count: 1, tool_ids: [tool.id] });
  render(
    <OpenApiActionDialogs onChanged={onChanged} onClosed={onClosed}>
      {(actions) => (
        <Button onClick={() => actions.disconnect(tool)}>
          Disconnect action
        </Button>
      )}
    </OpenApiActionDialogs>
  );
  await user.click(screen.getByRole("button", { name: "Disconnect action" }));
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(updateToolStatus).toHaveBeenCalledTimes(1));
  expect(onClosed).not.toHaveBeenCalled();
  expect(onChanged).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
  expect(onChanged).toHaveBeenCalledTimes(1);
});
