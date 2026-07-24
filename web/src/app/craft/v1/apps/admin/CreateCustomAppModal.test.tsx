/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import * as externalAppsService from "@/app/craft/services/externalAppsService";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

const mockUseUserSkills = jest.fn();
const mockRouterPush = jest.fn();

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  usePathname: () => "/admin/craft/apps",
}));

const CUSTOM_APP: ExternalAppAdminResponse = {
  id: 17,
  name: "Acme CRM",
  app_type: "CUSTOM",
  upstream_url_patterns: ["https://api.acme.test/*"],
  auth_template: {},
  organization_credentials: {},
  enabled: true,
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};

function renderExistingApp({
  onClose = jest.fn(),
  onSaved = jest.fn(),
}: {
  onClose?: jest.Mock;
  onSaved?: jest.Mock;
} = {}) {
  render(
    <CreateCustomAppModal
      onClose={onClose}
      onSaved={onSaved}
      existingApp={CUSTOM_APP}
    />
  );
  return { onClose, onSaved };
}

describe("CreateCustomAppModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUserSkills.mockReturnValue({
      data: { builtins: [], customs: [] },
      isLoading: false,
    });
  });

  it("persists the app before offering the optional skills step", async () => {
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
        organization_credentials: {},
      });
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Add skills to Acme CRM")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Associate existing" })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("confirms visibility promotion and batches association with app edits", async () => {
    const editableSkill = {
      source: "custom" as const,
      id: "skill-a",
      name: "acme-lookup",
      description: "Looks up Acme records",
      is_available: true,
      unavailable_reason: null,
      is_valid: true,
      is_personal: true,
      enabled: false,
      can_toggle: true,
      author_user_id: "admin-id",
      author_email: "admin@example.com",
      owner: { id: "admin-id", email: "admin@example.com" },
      ownership_vacant: false,
      created_at: null,
      updated_at: null,
      user_shares: [],
      group_shares: [],
      public_permission: null,
      user_permission: "OWNER" as const,
      external_app: null,
    };
    mockUseUserSkills.mockReturnValue({
      data: {
        builtins: [],
        customs: [
          editableSkill,
          { ...editableSkill, id: "skill-b" },
          {
            ...editableSkill,
            id: "invalid-skill",
            name: "broken-skill",
            is_valid: false,
          },
        ],
      },
      isLoading: false,
    });
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue({
      ...CUSTOM_APP,
      associated_skills: [
        { id: "skill-a", name: "acme-lookup", is_valid: true },
      ],
    });

    const { onClose, onSaved } = renderExistingApp();

    const appModal = screen.getByRole("dialog", { name: /Edit Acme CRM/ });
    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    expect(appModal).not.toContainElement(
      screen.getByPlaceholderText("Search editable skills...")
    );
    fireEvent.click(screen.getAllByRole("button", { name: /acme-lookup/ })[0]!);
    expect(
      screen.getByText(
        "App-associated skills must be available to everyone. This change is applied when you save the app."
      )
    ).toBeInTheDocument();
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Make organization-wide" })
    );
    fireEvent.click(screen.getByRole("button", { name: "Associate existing" }));
    const sameNamedSkills = screen.getAllByRole("button", {
      name: "Associate acme-lookup",
    });
    expect(sameNamedSkills).toHaveLength(2);
    const disabledSameNamedSkill = sameNamedSkills.find(
      (item) => item.getAttribute("aria-disabled") === "true"
    );
    expect(disabledSameNamedSkill).toHaveTextContent(
      "A skill named “acme-lookup” is already associated."
    );
    const invalidSkill = screen.getByRole("button", {
      name: "Associate broken-skill",
    });
    expect(invalidSkill).toHaveAttribute("aria-disabled", "true");
    expect(invalidSkill).toHaveTextContent(
      "Invalid skill — fix it before associating."
    );
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(17, {
        name: "Acme CRM",
        upstream_url_patterns: ["https://api.acme.test/*"],
        auth_template: {},
        organization_credentials: {},
        associated_skill_ids: ["skill-a"],
      })
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("guards unsaved edits before skill creation without persisting them", () => {
    const { onClose, onSaved } = renderExistingApp();

    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(
      screen.getByRole("button", { name: /^Start from scratch/ })
    );

    expect(mockRouterPush).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/craft/v1/skills/new?externalAppId=17&externalAppName=Acme+CRM"
    );
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
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
    expect(
      screen.getByRole("dialog", { name: "Discard unsaved changes?" })
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
  });

  it("restores unsaved app settings after upload is canceled", () => {
    const { onClose } = renderExistingApp();
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Edited Acme CRM" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));

    expect(externalAppsService.updateExternalApp).not.toHaveBeenCalled();
    expect(screen.getByText("Upload skill")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByDisplayValue("Edited Acme CRM")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("preserves the draft when refreshed app data arrives", () => {
    const props = {
      onClose: jest.fn(),
      onSaved: jest.fn(),
      existingApp: CUSTOM_APP,
    };
    const { rerender } = render(<CreateCustomAppModal {...props} />);
    fireEvent.change(screen.getByDisplayValue("Acme CRM"), {
      target: { value: "Unsaved Acme CRM" },
    });

    rerender(
      <CreateCustomAppModal
        {...props}
        existingApp={{ ...CUSTOM_APP, associated_skills: [] }}
      />
    );

    expect(screen.getByDisplayValue("Unsaved Acme CRM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });
});
