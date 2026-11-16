/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import * as externalAppsService from "@/app/craft/services/externalAppsService";

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

const DESCRIPTOR: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: ["https://slack.com/api/.*"],
  auth_template: { Authorization: "Bearer {token}" },
  required_org_credential_fields: [
    {
      key: "token",
      label: "Token",
      description: "Slack organization token",
      secret: true,
    },
  ],
  setup_instructions: "Configure Slack.",
  actions: [],
};

const APP: ExternalAppAdminResponse = {
  id: 7,
  name: "Slack",
  app_type: "SLACK",
  upstream_url_patterns: DESCRIPTOR.upstream_url_patterns,
  auth_template: DESCRIPTOR.auth_template,
  organization_credentials: { token: "masked-token" },
  credential_placeholder_keys: ["token"],
  enabled: true,
  actions: [],
  users_can_manage_policies: true,
  is_onyx_managed: false,
};

function renderExistingProvider(onClose = jest.fn()) {
  render(
    <ConfigureProviderModal
      onClose={onClose}
      onSaved={jest.fn()}
      descriptor={DESCRIPTOR}
      existingApp={APP}
    />
  );
  return { onClose };
}

describe("ConfigureProviderModal", () => {
  it("saves Craft availability above user permissions", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    renderExistingProvider();
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
        APP.id,
        expect.objectContaining({ enabled: false })
      )
    );
  });

  it.each([false, true])(
    "preserves concurrent availability changes for managed=%s",
    async (managed) => {
      const initial = { ...APP, is_onyx_managed: managed };
      const onClose = jest.fn();
      const onSaved = jest.fn();
      jest
        .mocked(externalAppsService.updateExternalApp)
        .mockResolvedValue({ ...initial, enabled: false });
      const view = render(
        <ConfigureProviderModal
          onClose={onClose}
          onSaved={onSaved}
          descriptor={DESCRIPTOR}
          existingApp={initial}
        />
      );
      view.rerender(
        <ConfigureProviderModal
          onClose={onClose}
          onSaved={onSaved}
          descriptor={DESCRIPTOR}
          existingApp={{ ...initial, enabled: false }}
        />
      );
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
      expect(
        screen.getByRole("switch", { name: "Enable for Craft" })
      ).not.toBeChecked();
      fireEvent.click(
        screen.getByRole("switch", {
          name: "Let users manage approval settings",
        })
      );
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(externalAppsService.updateExternalApp).toHaveBeenCalled()
      );
      expect(
        jest.mocked(externalAppsService.updateExternalApp).mock.calls[0]?.[1]
      ).not.toHaveProperty("enabled");
    }
  );

  it("keeps an availability draft through saved-value refreshes", async () => {
    const onClose = jest.fn();
    const onSaved = jest.fn();
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    const view = render(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={onSaved}
        descriptor={DESCRIPTOR}
        existingApp={APP}
      />
    );
    const availability = screen.getByRole("switch", {
      name: "Enable for Craft",
    });
    fireEvent.click(availability);
    view.rerender(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={onSaved}
        descriptor={DESCRIPTOR}
        existingApp={{ ...APP, enabled: false }}
      />
    );
    expect(availability).not.toBeChecked();
    view.rerender(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={onSaved}
        descriptor={DESCRIPTOR}
        existingApp={APP}
      />
    );
    expect(availability).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        APP.id,
        expect.objectContaining({ enabled: false })
      )
    );
  });

  it("describes a disabled app accurately", () => {
    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={{ ...APP, enabled: false }}
      />
    );
    expect(
      screen.getAllByText(
        "This app is disabled in Craft. Main Chat does not support it."
      )[0]
    ).toBeVisible();
  });

  it("shows an app description instead of the saved service URL", () => {
    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={{
          ...APP,
          upstream_url_patterns: ["https://api\\.linear\\.app/.*"],
        }}
      />
    );
    expect(
      screen.getAllByText(
        "This app is available in Craft. Main Chat does not support it."
      )[0]
    ).toBeVisible();
    expect(
      screen.queryByText("https://api.linear.app")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("https://api\\.linear\\.app/.*")).toBeNull();
  });

  it("shows an app description before creation", () => {
    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    expect(
      screen.getAllByText(
        "This app is available in Craft. Main Chat does not support it."
      )[0]
    ).toBeVisible();
    expect(screen.queryByText("https://slack.com")).not.toBeInTheDocument();
  });

  it("separates configuration and authentication and retains edits across tabs", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    renderExistingProvider();
    expect(screen.queryByText("Craft only")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toBeVisible();
    expect(screen.getByLabelText("Token")).not.toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Support Slack" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Authentication" }), {
      button: 0,
    });
    expect(screen.getByText(DESCRIPTOR.setup_instructions)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "new-token" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tools" }), {
      button: 0,
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Configuration" }), {
      button: 0,
    });
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Support Slack"
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          name: "Support Slack",
          organization_credentials: { token: "new-token" },
        })
      )
    );
  });

  it("keeps managed provider credentials out of the editor", () => {
    render(
      <ConfigureProviderModal
        existingApp={{ ...APP, is_onyx_managed: true }}
        descriptor={DESCRIPTOR}
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(screen.getByRole("tab", { name: "Authentication" })).toBeVisible();
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tools" })).toBeVisible();
  });

  it("labels provider credentials and closes a new draft without confirmation", () => {
    const onClose = jest.fn();
    render(
      <ConfigureProviderModal
        existingApp={null}
        descriptor={DESCRIPTOR}
        onClose={onClose}
        onSaved={jest.fn()}
      />
    );
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "draft-token" },
    });
    expect(screen.getByRole("dialog")).toHaveAttribute("data-width", "lg");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" })
    ).not.toBeInTheDocument();
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("sends edited provider settings", async () => {
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
    const { onClose } = renderExistingProvider();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "updated-token" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(7, {
        name: "Slack",
        upstream_url_patterns: ["https://slack.com/api/.*"],
        auth_template: { Authorization: "Bearer {token}" },
        action_policies: {},
        users_can_manage_policies: true,
        organization_credentials: { token: "updated-token" },
      })
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("creates a provider whose valid defaults need no manual edits", async () => {
    const noInputDescriptor: BuiltInExternalAppDescriptor = {
      ...DESCRIPTOR,
      required_org_credential_fields: [],
    };
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue(APP);

    const onClose = jest.fn();
    const onSaved = jest.fn();
    render(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={onSaved}
        descriptor={noInputDescriptor}
        existingApp={null}
      />
    );

    const addButton = screen.getByRole("button", { name: "Add" });
    expect(addButton).toBeEnabled();
    fireEvent.click(addButton);

    await waitFor(() =>
      expect(externalAppsService.createBuiltInExternalApp).toHaveBeenCalledWith(
        {
          name: "Slack",
          app_type: "SLACK",
          upstream_url_patterns: DESCRIPTOR.upstream_url_patterns,
          auth_template: DESCRIPTOR.auth_template,
          enabled: true,
          users_can_manage_policies: true,
          organization_credentials: {},
          action_policies: {},
        }
      )
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("sends account input to the backend for gateway resolution", async () => {
    const perAccountDescriptor: BuiltInExternalAppDescriptor = {
      ...DESCRIPTOR,
      app_type: "ZENDESK",
      name: "Zendesk",
      upstream_url_patterns: ["https://{subdomain}\\.zendesk\\.com/api/v2/.*"],
      required_org_credential_fields: [
        {
          key: "subdomain",
          label: "Subdomain",
          description: "Your Zendesk subdomain",
          secret: false,
        },
      ],
    };
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue(APP);

    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={perAccountDescriptor}
        existingApp={null}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("Subdomain"), {
      target: { value: "acme" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(externalAppsService.createBuiltInExternalApp).toHaveBeenCalledWith(
        expect.objectContaining({
          upstream_url_patterns: perAccountDescriptor.upstream_url_patterns,
          enabled: true,
          users_can_manage_policies: true,
          organization_credentials: { subdomain: "acme" },
        })
      )
    );
  });
});
