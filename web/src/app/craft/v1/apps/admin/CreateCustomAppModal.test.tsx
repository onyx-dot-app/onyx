/**
 * @jest-environment jsdom
 */

import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import * as externalAppsService from "@/app/craft/services/externalAppsService";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/admin/craft/apps",
}));

beforeEach(() => {
  // Navigation skips a URL it is already on, so each test starts here.
  window.history.replaceState(null, "", "/admin/craft/apps");
});

const CUSTOM_APP: ExternalAppAdminResponse = {
  id: 17,
  name: "Acme CRM",
  app_type: "CUSTOM",
  upstream_url_patterns: ["https://api.acme.test/*"],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  enabled: true,
  actions: [],
  users_can_manage_policies: true,
  is_onyx_managed: false,
};

function renderExistingApp({
  onClose = jest.fn(),
  onSaved = jest.fn(),
}: {
  onClose?: jest.Mock;
  onSaved?: jest.Mock;
} = {}) {
  const { unmount } = render(
    <CreateCustomAppModal
      onClose={onClose}
      onSaved={onSaved}
      existingApp={CUSTOM_APP}
    />
  );
  return { onClose, onSaved, unmount };
}

describe("CreateCustomAppModal", () => {
  it("saves Craft availability above user permissions", async () => {
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockResolvedValue(CUSTOM_APP);
    renderExistingApp();
    const availability = screen.getByRole("switch", {
      name: "Enable for Craft",
    });
    const permissions = screen.getByRole("switch", {
      name: "Let users manage approval settings",
    });
    expect(
      availability.compareDocumentPosition(permissions) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    fireEvent.click(availability);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        CUSTOM_APP.id,
        expect.objectContaining({ enabled: false })
      )
    );
  });

  it("preserves availability changes made by another administrator", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockResolvedValue({ ...CUSTOM_APP, enabled: false });
    const view = render(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={CUSTOM_APP}
      />
    );
    view.rerender(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={{ ...CUSTOM_APP, enabled: false }}
      />
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen.getByRole("switch", { name: "Enable for Craft" })
    ).not.toBeChecked();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "New name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalled()
    );
    expect(
      jest.mocked(externalAppsService.updateExternalApp).mock.calls[0]?.[1]
    ).not.toHaveProperty("enabled");
  });

  it("keeps an availability draft through saved-value refreshes", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockResolvedValue(CUSTOM_APP);
    const view = render(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={CUSTOM_APP}
      />
    );
    const availability = screen.getByRole("switch", {
      name: "Enable for Craft",
    });
    fireEvent.click(availability);
    view.rerender(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={{ ...CUSTOM_APP, enabled: false }}
      />
    );
    expect(availability).not.toBeChecked();
    view.rerender(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={CUSTOM_APP}
      />
    );
    expect(availability).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        CUSTOM_APP.id,
        expect.objectContaining({ enabled: false })
      )
    );
  });

  it("describes a disabled app accurately", () => {
    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={{ ...CUSTOM_APP, enabled: false }}
      />
    );
    expect(
      screen.getAllByText(
        "This app is disabled in Craft. Main Chat does not support it."
      )[0]
    ).toBeVisible();
  });

  it("labels the name and discards a new draft from the close button", () => {
    const onClose = jest.fn();
    render(
      <CreateCustomAppModal
        existingApp={null}
        onClose={onClose}
        onSaved={jest.fn()}
      />
    );
    const name = screen.getByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Draft" } });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("data-width", "lg");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
  });

  it("keeps the editor shell stable during discard confirmation", () => {
    renderExistingApp();
    expect(
      screen.getAllByText(
        "This app is available in Craft. Main Chat does not support it."
      )[0]
    ).toBeVisible();
    expect(screen.queryByText("https://api.acme.test")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    const confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    expect(confirmation).toHaveAttribute("data-width", "lg");
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("saves a change to user management without changing app configuration", async () => {
    const user = setupUser();
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockResolvedValue(CUSTOM_APP);
    renderExistingApp();
    await user.click(
      screen.getByRole("switch", {
        name: "Let users manage approval settings",
      })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        CUSTOM_APP.id,
        expect.objectContaining({ users_can_manage_policies: false })
      )
    );
  });

  it("focuses the name only when creating an app", () => {
    const { unmount } = renderExistingApp();
    expect(screen.getByPlaceholderText("My Custom App")).not.toHaveFocus();
    unmount();

    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={null}
      />
    );
    expect(screen.getByPlaceholderText("My Custom App")).toHaveFocus();
  });

  it("creates the app and closes", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest
      .mocked(externalAppsService.createCustomExternalApp)
      .mockResolvedValue(CUSTOM_APP);

    render(
      <CreateCustomAppModal
        onClose={onClose}
        onSaved={onSaved}
        existingApp={null}
      />
    );

    expect(screen.queryByText(/bundle/i)).not.toBeInTheDocument();
    const createButton = screen.getByRole("button", { name: "Create" });
    expect(createButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("My Custom App"), {
      target: { value: "Acme CRM" },
    });
    const patternInput = screen.getByPlaceholderText(
      "https://api.example.com/*"
    );
    fireEvent.change(patternInput, {
      target: { value: "https://api.acme.test/*" },
    });
    fireEvent.keyDown(patternInput, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Create" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(externalAppsService.createCustomExternalApp).toHaveBeenCalledWith({
        name: "Acme CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: {},
        enabled: true,
        users_can_manage_policies: true,
        organization_credentials: {},
      });
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("sends edited custom app settings", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue({
      ...CUSTOM_APP,
      name: "Updated CRM",
    });
    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={CUSTOM_APP}
      />
    );

    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Updated CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(17, {
        name: "Updated CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: {},
        users_can_manage_policies: true,
        organization_credentials: {},
      })
    );
  });

  it("separates configuration, authentication, and tools", async () => {
    jest
      .mocked(externalAppsService.createCustomExternalApp)
      .mockResolvedValue(CUSTOM_APP);
    render(
      <CreateCustomAppModal
        existingApp={null}
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(screen.getByRole("tab", { name: "Tools" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Reports API" },
    });
    const pattern = screen.getByPlaceholderText("https://api.example.com/*");
    fireEvent.change(pattern, {
      target: { value: "https://reports.internal/*" },
    });
    fireEvent.keyDown(pattern, { key: "Enter", code: "Enter" });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Authentication" }), {
      button: 0,
    });
    fireEvent.change(screen.getByPlaceholderText("Authorization"), {
      target: { value: "Authorization" },
    });
    fireEvent.change(screen.getByPlaceholderText("Bearer {api_key}"), {
      target: { value: "Bearer {reports_key}" },
    });
    fireEvent.change(screen.getByPlaceholderText("api_key"), {
      target: { value: "reports_key" },
    });
    fireEvent.change(screen.getByPlaceholderText("sk-…"), {
      target: { value: "reports-secret" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Configuration" }), {
      button: 0,
    });
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Reports API"
    );
    expect(screen.getByPlaceholderText("sk-…")).toHaveValue("reports-secret");
    expect(screen.getByPlaceholderText("sk-…")).toHaveAttribute(
      "type",
      "password"
    );
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(externalAppsService.createCustomExternalApp).toHaveBeenCalledWith({
        enabled: true,
        users_can_manage_policies: true,
        name: "Reports API",
        upstream_url_patterns: ["https://reports.internal/*"],
        auth_template: { Authorization: "Bearer {reports_key}" },
        organization_credentials: { reports_key: "reports-secret" },
      })
    );
  });

  it("masks organization credentials and saves their original values after reveal", async () => {
    const user = setupUser();
    const app = {
      ...CUSTOM_APP,
      auth_template: { Authorization: "Bearer {api_key}" },
      organization_credentials: { api_key: "sk-original-secret+/=" },
    };
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(app);
    render(
      <CreateCustomAppModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={app}
      />
    );

    await user.click(screen.getByRole("tab", { name: "Authentication" }));
    const credential = screen.getByPlaceholderText("sk-…");
    expect(credential).toHaveAttribute("type", "password");
    expect(credential).toHaveValue("sk-original-secret+/=");
    expect(screen.getByDisplayValue("api_key")).toHaveAttribute("type", "text");
    expect(screen.getByDisplayValue("Bearer {api_key}")).toHaveAttribute(
      "type",
      "text"
    );

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(credential).toHaveAttribute("type", "text");
    expect(credential).toHaveValue("sk-original-secret+/=");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(credential).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("tab", { name: "Tools" }));
    await user.click(screen.getByRole("tab", { name: "Configuration" }));
    expect(credential).toHaveValue("sk-original-secret+/=");
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(
      screen.getByRole("textbox", { name: "Name" }),
      "Updated CRM"
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(17, {
        name: "Updated CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: { Authorization: "Bearer {api_key}" },
        organization_credentials: { api_key: "sk-original-secret+/=" },
        users_can_manage_policies: true,
      })
    );
  });

  it("warns before discarding dirty app settings", () => {
    const { onClose } = renderExistingApp();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).not.toHaveBeenCalled();
    let confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Cancel" })
    );
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Close" })
    );
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("cannot discard an app edit while its save is in flight", async () => {
    const save = deferred<ExternalAppAdminResponse>();
    jest
      .mocked(externalAppsService.updateExternalApp)
      .mockReturnValue(save.promise);
    const { onClose } = renderExistingApp();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Updated Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledTimes(1)
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve({ ...CUSTOM_APP, name: "Updated Acme CRM" });
      await save.promise;
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
