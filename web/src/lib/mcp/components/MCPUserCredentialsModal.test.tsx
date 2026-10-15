import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { Modal } from "@opal/components";
import { MCPUserCredentialsContent } from "@/lib/mcp/components/MCPUserCredentialsModal";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/mcp/types";
import type { MCPAuthenticationServer } from "@/lib/mcp/types";

const server: MCPAuthenticationServer = {
  id: 1,
  name: "Calendar",
  auth_type: MCPAuthenticationType.API_TOKEN,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
  user_can_authenticate: false,
};
function setup(
  userCredentials?: Record<string, string>,
  onSubmit = jest.fn().mockResolvedValue(undefined)
) {
  const onBack = jest.fn();
  const onClose = jest.fn();
  render(
    <Modal open>
      <MCPUserCredentialsContent
        server={{ ...server, user_credentials: userCredentials }}
        onBack={onBack}
        onClose={onClose}
        onSubmit={onSubmit}
      />
    </Modal>
  );
  return { onBack, onClose, onSubmit, user: setupUser() };
}

describe("MCPUserCredentialsModal", () => {
  it("returns to tools without confirmation when existing credentials are unchanged", async () => {
    const { user, onBack } = setup({ api_key: "existing" });
    await user.click(screen.getByRole("button", { name: "Back to tools" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText("Discard unsaved changes?")
    ).not.toBeInTheDocument();
  });
  it("confirms dirty Back, restores values on Escape, and discards to the list", async () => {
    const { user, onBack, onClose } = setup();
    await user.type(screen.getByLabelText("API Key"), "secret");
    await user.click(screen.getByRole("button", { name: "Back to tools" }));
    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await user.keyboard("{Escape}");
    expect(screen.getByLabelText("API Key")).toHaveValue("secret");
    expect(screen.getByLabelText("API Key")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Back to tools" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });
  it.each(["close", "escape"])(
    "confirms dirty %s before closing the whole flow",
    async (method) => {
      const { user, onClose, onBack } = setup();
      await user.type(screen.getByLabelText("API Key"), "secret");
      if (method === "close")
        await user.click(screen.getByRole("button", { name: "Close" }));
      else await user.keyboard("{Escape}");
      expect(
        await screen.findByText("Discard unsaved changes?")
      ).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: "Discard changes" }));
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onBack).not.toHaveBeenCalled();
    }
  );
  it("protects pending submissions and keeps failed credentials for correction", async () => {
    let rejectRequest: (reason: Error) => void = () => undefined;
    const onSubmit = jest.fn(
      () =>
        new Promise<void>((_, reject) => {
          rejectRequest = reject;
        })
    );
    const { user, onClose, onBack } = setup(undefined, onSubmit);
    await user.type(screen.getByLabelText("API Key"), "secret");
    await user.click(screen.getByRole("button", { name: "Save API Key" }));
    expect(
      screen.getByRole("button", { name: "Back to tools" })
    ).toBeDisabled();
    await user.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(onBack).not.toHaveBeenCalled();
    rejectRequest(new Error("Invalid key"));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid key")
    );
    expect(screen.getByLabelText("API Key")).toHaveValue("secret");
  });
});
