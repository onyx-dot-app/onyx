import { render, screen } from "@tests/setup/test-utils";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import type { SkillPreview } from "@/lib/skills/types";

const mockUseSWR = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

function preview(overrides: Partial<SkillPreview> = {}): SkillPreview {
  return {
    source: "custom",
    id: "skill-id",
    name: "CRM lookup",
    description: "Looks up CRM records",
    author_email: "owner@example.com",
    instructions_markdown: "Look up the requested record.",
    external_app: null,
    ...overrides,
  };
}

describe("SkillPreviewModal", () => {
  it("explains when the associated external app must be connected", () => {
    mockUseSWR.mockReturnValue({
      data: preview({
        external_app: {
          external_app_id: 42,
          name: "Acme CRM",
          enabled: true,
          ready: false,
        },
      }),
      error: undefined,
      isLoading: false,
    });

    render(<SkillPreviewModal open skillId="skill-id" onClose={jest.fn()} />);

    expect(screen.getByText("Skill unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Connect app “Acme CRM” from the Apps page to use this skill."
      )
    ).toBeInTheDocument();
  });

  it("does not warn when the associated external app is ready", () => {
    mockUseSWR.mockReturnValue({
      data: preview({
        external_app: {
          external_app_id: 42,
          name: "Acme CRM",
          enabled: true,
          ready: true,
        },
      }),
      error: undefined,
      isLoading: false,
    });

    render(<SkillPreviewModal open skillId="skill-id" onClose={jest.fn()} />);

    expect(screen.queryByText("Skill unavailable")).not.toBeInTheDocument();
  });
});
