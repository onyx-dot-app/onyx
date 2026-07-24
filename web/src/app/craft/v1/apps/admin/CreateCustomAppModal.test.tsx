/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import * as externalAppsService from "@/app/craft/services/externalAppsService";

const mockUseUserSkills = jest.fn();

jest.mock("@/app/craft/services/externalAppsService");
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/admin/craft/apps",
}));

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
    jest.mocked(externalAppsService.createCustomExternalApp).mockResolvedValue({
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
    });

    render(
      <CreateCustomAppModal
        open
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
    const onClose = jest.fn();
    const onSaved = jest.fn();
    const existingApp = {
      id: 17,
      name: "Acme CRM",
      app_type: "CUSTOM" as const,
      upstream_url_patterns: ["https://api.acme.test/*"],
      auth_template: {},
      organization_credentials: {},
      enabled: true,
      actions: [],
      associated_skills: [],
      is_onyx_managed: false,
    };
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
      ...existingApp,
      associated_skills: [
        { id: "skill-a", name: "acme-lookup", is_valid: true },
      ],
    });

    render(
      <CreateCustomAppModal
        open
        onClose={onClose}
        onSaved={onSaved}
        existingApp={existingApp}
      />
    );

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
    expect(
      sameNamedSkills.filter(
        (item) => item.getAttribute("aria-disabled") === "true"
      )
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Associate broken-skill" })
    ).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getAllByText("Invalid skill — fix it before associating.").length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("A skill named “acme-lookup” is already associated.")
        .length
    ).toBeGreaterThan(0);
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

  it("keeps app settings mounted beneath the upload chooser", () => {
    const existingApp = {
      id: 17,
      name: "Acme CRM",
      app_type: "CUSTOM" as const,
      upstream_url_patterns: ["https://api.acme.test/*"],
      auth_template: {},
      organization_credentials: {},
      enabled: true,
      actions: [],
      associated_skills: [],
      is_onyx_managed: false,
    };

    render(
      <CreateCustomAppModal
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
        existingApp={existingApp}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));
    fireEvent.click(screen.getByRole("button", { name: /^Upload a skill/ }));

    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2);
    expect(screen.getByText("Edit Acme CRM")).toBeInTheDocument();
    expect(screen.getByText("Upload skill")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByDisplayValue("Acme CRM")).toBeInTheDocument();
  });
});
