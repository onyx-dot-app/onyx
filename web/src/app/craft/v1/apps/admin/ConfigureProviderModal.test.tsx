/**
 * @jest-environment jsdom
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import * as externalAppsService from "@/app/craft/services/externalAppsService";
import type { SkillCreationDraft } from "@/lib/skills/creationDraft";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const mockRouterPush = jest.fn();
const mockUseUserSkills = jest.fn();

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));
jest.mock("@/lib/skills/creationDraft", () => ({
  stageSkillCreationDraft: () => "draft-id",
}));
jest.mock("@/sections/modals/skills/CreateSkillModal", () => ({
  CreateSkillModalContent: ({
    hidden = false,
    onRequestClose,
    onContinue,
    onDirtyChange,
  }: {
    hidden?: boolean;
    onRequestClose: () => void;
    onContinue: (draft: SkillCreationDraft) => void;
    onDirtyChange?: (dirty: boolean) => void;
  }) =>
    hidden ? null : (
      <>
        <div>Upload skill</div>
        <button type="button" onClick={() => onDirtyChange?.(true)}>
          Select bundle
        </button>
        <button type="button" onClick={onRequestClose}>
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onContinue({} as SkillCreationDraft)}
        >
          Review skill
        </button>
      </>
    ),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  usePathname: () => "/admin/craft/apps",
}));

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
  associated_skills: [
    { id: "custom-skill", name: "slack-workflow", is_valid: true },
  ],
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
  it("shows the saved service origin in its header without regex syntax", () => {
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
    expect(screen.getAllByText("https://api.linear.app")[0]).toBeVisible();
    expect(screen.queryByText("https://api\\.linear\\.app/.*")).toBeNull();
  });

  it("shows the descriptor origin before creation", () => {
    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    expect(screen.getAllByText("https://slack.com")[0]).toBeVisible();
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
    mockUseUserSkills.mockReturnValue({
      data: { builtins: [], customs: [] },
      isLoading: false,
    });
  });

  it("omits unchanged associations from a provider settings update", async () => {
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
      .mockResolvedValue({ ...APP, associated_skills: [] });

    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
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
          users_can_manage_policies: true,
          organization_credentials: {},
          action_policies: {},
        }
      )
    );
    expect(await screen.findByText("Add skills to Slack")).toBeInTheDocument();
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
      .mockResolvedValue({ ...APP, associated_skills: [] });

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
          users_can_manage_policies: true,
          organization_credentials: { subdomain: "acme" },
        })
      )
    );
  });

  it("guards unsaved provider edits before skill creation", () => {
    const { onClose } = renderExistingProvider();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "unsaved-token" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Skills" }), {
      button: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(
      screen.getByRole("menuitem", { name: /^Start from scratch/ })
    );

    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/craft/v1/skills/new?externalAppId=7&externalAppName=Slack"
    );
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("directs GitHub imports through the Skills page", () => {
    renderExistingProvider();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Skills" }), {
      button: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));

    expect(
      screen.getByRole("menuitem", { name: /Import from GitHub/ })
    ).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(
        "If your skills are in GitHub, import them on the Skills page first, then associate them with this app."
      )
    ).toBeInTheDocument();
  });

  it("restores unsaved provider settings after upload is canceled", () => {
    const { onClose } = renderExistingProvider();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "updated-token" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Skills" }), {
      button: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /^Upload a skill/ }));

    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("dialog", { name: /^Slack/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Configuration" }), {
      button: 0,
    });
    expect(screen.getByPlaceholderText("Token")).toHaveValue("updated-token");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("confirms before accidentally closing a selected upload", () => {
    const { onClose } = renderExistingProvider();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Skills" }), {
      button: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select bundle" }));

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(
      within(
        screen.getByRole("dialog", { name: "Discard unsaved changes?" })
      ).getByRole("button", { name: "Cancel" })
    );
    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(screen.getByRole("dialog", { name: /^Slack/ })).toBeVisible();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("guards unsaved provider settings before reviewing an upload", () => {
    renderExistingProvider();
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "unsaved-token" },
    });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Skills" }), {
      button: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review skill" }));

    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/craft/v1/skills/new?externalAppId=7&externalAppName=Slack&draft=draft-id"
    );
  });

  it("keeps a newly created provider durable while skills are skipped", async () => {
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue({ ...APP, associated_skills: [] });
    const onClose = jest.fn();

    render(
      <ConfigureProviderModal
        onClose={onClose}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "org-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("Add skills to Slack")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save skills" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("guards a selected upload in the post-create skills step", async () => {
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue({ ...APP, associated_skills: [] });

    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "org-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Add skills to Slack")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select bundle" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    const confirmation = screen.getByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Cancel" })
    );

    expect(screen.getByText("Upload skill")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled();
  });

  it("guards pending post-create associations before reviewing an upload", async () => {
    mockUseUserSkills.mockReturnValue({
      data: {
        builtins: [],
        customs: [
          customFixture({
            id: "pending-skill",
            name: "slack-helper",
            description: "Uses Slack",
            enabled: false,
            author_user_id: "admin-id",
            author_email: "admin@example.com",
            owner: { id: "admin-id", email: "admin@example.com" },
            ownership_vacant: false,
            user_permission: "OWNER",
          }),
        ],
      },
      isLoading: false,
    });
    jest
      .mocked(externalAppsService.createBuiltInExternalApp)
      .mockResolvedValue({ ...APP, associated_skills: [] });

    render(
      <ConfigureProviderModal
        onClose={jest.fn()}
        onSaved={jest.fn()}
        descriptor={DESCRIPTOR}
        existingApp={null}
      />
    );
    fireEvent.change(screen.getByPlaceholderText("Token"), {
      target: { value: "org-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Add skills to Slack")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    fireEvent.click(screen.getByRole("option", { name: /^slack-helper/ }));
    expect(screen.getByRole("button", { name: "Save skills" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /^Upload a skill/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review skill" }));

    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/craft/v1/skills/new?externalAppId=7&externalAppName=Slack&draft=draft-id"
    );
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });
});
