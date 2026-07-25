import { render, screen, setupUser } from "@tests/setup/test-utils";
import SkillCard, {
  type BuiltinSkillCardItem,
  type CustomSkillCardItem,
} from "@/sections/cards/SkillCard";
import type { CustomSkill } from "@/lib/skills/types";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

function builtIn(
  overrides: Partial<BuiltinSkillCardItem> = {}
): BuiltinSkillCardItem {
  return {
    id: "skill-id",
    name: "Browser",
    description: "Browse the web",
    source: "builtin",
    enabled: true,
    can_toggle: false,
    is_available: true,
    ...overrides,
  };
}

function custom(overrides: Partial<CustomSkill> = {}): CustomSkillCardItem {
  const skill: CustomSkill = {
    source: "custom",
    id: "custom-skill-id",
    name: "Report Writer",
    description: "Draft reports",
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: true,
    enabled: true,
    can_toggle: true,
    author_user_id: "user-id",
    author_email: "owner@example.com",
    owner: { id: "user-id", email: "owner@example.com" },
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: null,
    user_permission: "OWNER",
    external_app: null,
    ...overrides,
  };
  return {
    id: skill.id,
    name: skill.name,
    description: skill.description,
    source: "custom",
    skill,
    enabled: skill.enabled,
    can_toggle: skill.can_toggle,
    author_email: skill.author_email,
    is_personal: true,
  };
}

function invalidCustom(): CustomSkillCardItem {
  return custom({
    id: "invalid-skill-id",
    name: "Invalid skill",
    description: "Invalid bundle",
    is_valid: false,
    enabled: false,
    can_toggle: false,
  });
}

describe("SkillCard", () => {
  it("does not render a preference switch for native built-ins", () => {
    render(<SkillCard item={builtIn()} />);

    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("reports user preference changes for toggleable skills", async () => {
    const user = setupUser();
    const item = custom();
    const onEnabledChange = jest.fn();
    render(<SkillCard item={item} onEnabledChange={onEnabledChange} />);

    await user.click(
      screen.getByRole("switch", { name: "Disable Report Writer" })
    );

    expect(onEnabledChange).toHaveBeenCalledWith(item, false);
  });

  it("disables a pending preference switch and ignores duplicate clicks", async () => {
    const user = setupUser();
    const onEnabledChange = jest.fn();
    render(
      <SkillCard
        item={custom()}
        onEnabledChange={onEnabledChange}
        enablementPending
      />
    );

    const preferenceSwitch = screen.getByRole("switch", {
      name: "Disable Report Writer",
    });
    expect(preferenceSwitch).toBeDisabled();

    await user.click(preferenceSwitch);
    expect(onEnabledChange).not.toHaveBeenCalled();
  });

  it("directs users to recreate invalid skills without showing a switch", () => {
    render(<SkillCard item={invalidCustom()} />);

    expect(screen.getByText("Invalid")).toBeInTheDocument();
    expect(
      screen.getByText("Delete this invalid skill and create a new one.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("keeps a selected skill on while its app is unavailable", () => {
    const { container } = render(
      <SkillCard
        item={custom({
          enabled: true,
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: false,
          },
        })}
      />
    );

    expect(
      screen.getByText("Connect app “Acme CRM” to use")
    ).toBeInTheDocument();
    const preferenceSwitch = screen.getByRole("switch", {
      name: "Disable Report Writer for Acme CRM",
    });
    expect(preferenceSwitch).toBeChecked();
    expect(preferenceSwitch).toBeEnabled();
    expect(
      container.querySelector(".card[data-variant='secondary']")
    ).toBeInTheDocument();
  });

  it("does not offer an enable toggle until the app is connected", () => {
    const { container } = render(
      <SkillCard
        item={custom({
          enabled: false,
          can_toggle: false,
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: false,
          },
        })}
      />
    );

    expect(
      screen.getByText("Connect app “Acme CRM” to enable")
    ).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(
      container.querySelector(".card[data-variant='disabled']")
    ).toBeInTheDocument();
  });

  it("distinguishes an admin-disabled app dependency", () => {
    render(
      <SkillCard
        item={custom({
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: false,
            ready: false,
          },
        })}
      />
    );

    expect(screen.getByText("App “Acme CRM” is disabled")).toBeInTheDocument();
    expect(
      screen.getByRole("switch", {
        name: "Disable Report Writer for Acme CRM",
      })
    ).toBeChecked();
  });

  it("shows a selected ready associated skill as active", () => {
    const { container } = render(
      <SkillCard
        item={custom({
          enabled: true,
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: true,
          },
        })}
      />
    );

    expect(screen.getByText("Uses app “Acme CRM”")).toBeInTheDocument();
    expect(screen.getByText("App skill")).toBeInTheDocument();
    expect(screen.queryByText("Custom")).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", {
        name: "Disable Report Writer for Acme CRM",
      })
    ).toBeChecked();
    expect(
      container.querySelector(".card[data-variant='primary']")
    ).toBeInTheDocument();
  });

  it("shows when another skill with the same name is enabled", () => {
    render(
      <SkillCard
        item={custom({
          enabled: false,
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: true,
          },
        })}
        hasEnabledNameConflict
      />
    );

    expect(
      screen.getByText("Another skill with this name is enabled")
    ).toBeInTheDocument();
    const preferenceSwitch = screen.getByRole("switch", {
      name: "Enable Report Writer for Acme CRM",
    });
    expect(preferenceSwitch).not.toBeChecked();
    expect(preferenceSwitch).toBeEnabled();
  });
});
