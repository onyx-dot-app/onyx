import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { Modal } from "@opal/components";
import { markdown } from "@opal/utils";
import SkillPreviewModal, {
  SkillPreviewContent,
} from "@/sections/modals/SkillPreviewModal";
import type { SkillPreview } from "@/lib/skills/types";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const fetchMock = jest.fn<
  Promise<Response>,
  [RequestInfo | URL, RequestInit?]
>();
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
const response = (data: unknown) => new Response(JSON.stringify(data));
beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async (url) => {
    if (String(url).endsWith("/preview")) return response(preview());
    if (String(url).endsWith("/versions"))
      return response([
        {
          id: "v1",
          version_number: 1,
          created_at: "2026-11-08T12:00:00Z",
          created_by: null,
          is_current: true,
          has_bundle: true,
          marketplace_revision: "abc123",
        },
      ]);
    throw new Error(`Unexpected request: ${url}`);
  });
  global.fetch = fetchMock;
});

describe("SkillPreviewModal", () => {
  it("loads the preview only while the modal is open", async () => {
    const { rerender } = render(
      <SkillPreviewModal open={false} skillId="skill-id" onClose={jest.fn()} />
    );
    expect(fetchMock).not.toHaveBeenCalled();
    rerender(<SkillPreviewModal open skillId="skill-id" onClose={jest.fn()} />);
    expect(await screen.findByText("CRM lookup")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith("/api/skills/skill-id/preview");
  });

  it.each([false, true])(
    "shows app connection warnings only when needed (ready: %s)",
    async (ready) => {
      fetchMock.mockResolvedValue(
        response(
          preview({
            external_app: {
              external_app_id: 42,
              name: "Acme CRM",
              enabled: true,
              ready,
            },
          })
        )
      );
      render(<SkillPreviewModal open skillId="skill-id" onClose={jest.fn()} />);
      await screen.findByText("Look up the requested record.");
      if (ready)
        expect(screen.queryByText("Skill unavailable")).not.toBeInTheDocument();
      else
        expect(
          screen.getByText(
            "Connect app “Acme CRM” from the Apps page to use this skill."
          )
        ).toBeVisible();
    }
  );

  it.each([false, true])(
    "lets a synced editor read history without sharing authority (personal: %s)",
    async (personal) => {
      const skill = customFixture({
        id: "skill-id",
        user_permission: "EDITOR",
        marketplace: {
          id: "market",
          name: "Source",
          personal,
          folder: null,
          follows_access: true,
          can_share: false,
        },
      });
      render(
        <SkillPreviewModal
          open
          skillId={skill.id}
          historySkill={skill}
          onClose={jest.fn()}
        />
      );
      const user = setupUser();
      await screen.findByText("Look up the requested record.");
      expect(
        screen.queryByRole("tab", { name: "Sharing" })
      ).not.toBeInTheDocument();
      await user.click(screen.getByRole("tab", { name: "Versions" }));
      expect(await screen.findByText("Synced revision abc123")).toBeVisible();
      expect(
        screen.queryByRole("button", { name: /Restore/ })
      ).not.toBeInTheDocument();
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      expect(
        fetchMock.mock.calls.every(([url]) => !String(url).endsWith("/share"))
      ).toBe(true);
    }
  );

  it.each(["viewer", "builtin", "retired"] as const)(
    "keeps %s previews accessible without share or history requests",
    async (kind) => {
      fetchMock.mockResolvedValue(
        response(preview({ source: kind === "builtin" ? "builtin" : "custom" }))
      );
      const historySkill =
        kind === "builtin"
          ? undefined
          : customFixture({
              user_permission: kind === "retired" ? "OWNER" : "VIEWER",
              retired_at: kind === "retired" ? "2026-11-08T12:00:00Z" : null,
            });
      render(
        <SkillPreviewModal
          open
          skillId="skill-id"
          historySkill={historySkill}
          onClose={jest.fn()}
        />
      );
      await screen.findByText("Look up the requested record.");
      expect(
        screen.queryByRole("tab", { name: "Versions" })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("tab", { name: "Sharing" })
      ).not.toBeInTheDocument();
      expect(
        fetchMock.mock.calls.every(([url]) => String(url).endsWith("/preview"))
      ).toBe(true);
    }
  );

  it("preserves formatted custom close labels", async () => {
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
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Back to skills" })
          .querySelector("strong")
      ).toHaveTextContent("Back")
    );
  });
});
