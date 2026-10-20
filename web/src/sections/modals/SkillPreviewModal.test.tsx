import { render, screen } from "@tests/setup/test-utils";
import { Modal } from "@opal/components";
import { markdown } from "@opal/utils";
import SkillPreviewModal, {
  SkillPreviewContent,
} from "@/sections/modals/SkillPreviewModal";
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
  it("loads the preview only while the modal is open", () => {
    mockUseSWR.mockClear();
    mockUseSWR.mockReturnValue({
      data: preview(),
      error: undefined,
      isLoading: false,
    });
    const { rerender } = render(
      <SkillPreviewModal open={false} skillId="skill-id" onClose={jest.fn()} />
    );
    expect(mockUseSWR).not.toHaveBeenCalled();
    rerender(<SkillPreviewModal open skillId="skill-id" onClose={jest.fn()} />);
    expect(mockUseSWR).toHaveBeenCalled();
    expect(screen.getByText("CRM lookup")).toBeVisible();
  });

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

it("preserves formatted custom close labels", () => {
  mockUseSWR.mockReturnValue({ data: preview(), isLoading: false });
  render(
    <Modal open>
      <Modal.Content>
        <SkillPreviewContent
          skillId="skill-id"
          onClose={jest.fn()}
          closeLabel={markdown("**Back** to skills")}
        />
      </Modal.Content>
    </Modal>
  );
  const button = screen.getByRole("button", { name: "Back to skills" });
  expect(button.querySelector("strong")).toHaveTextContent("Back");
});
