import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import SkillReviewRequests from "@/sections/skills/SkillReviewRequests";
import type { SkillReviewRequest } from "@/lib/skills/types";

const mockFetch = jest.fn();
const mockReviewSkillVersion = jest.fn();
const mockToast = { success: jest.fn(), info: jest.fn(), error: jest.fn() };

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockFetch(...args),
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  reviewSkillVersion: (...args: unknown[]) => mockReviewSkillVersion(...args),
}));

jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToast.success(...args),
    info: (...args: unknown[]) => mockToast.info(...args),
    error: (...args: unknown[]) => mockToast.error(...args),
  },
}));

function request(
  overrides: Partial<SkillReviewRequest> = {}
): SkillReviewRequest {
  return {
    skill_id: "skill-1",
    name: "report-writer",
    version_id: "version-1",
    version_number: 1,
    published_version_number: null,
    author_email: "author@example.com",
    version_created_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

describe("SkillReviewRequests", () => {
  beforeEach(() => {
    mockFetch.mockReset().mockImplementation(async (url: string) => {
      if (url === "/api/skills/review-requests") {
        return [
          request(),
          request({
            skill_id: "skill-2",
            name: "weekly-report",
            version_id: "version-9",
            version_number: 3,
            published_version_number: 2,
          }),
        ];
      }
      if (url === "/api/skills/custom/skill-1/versions/version-1") {
        return {
          description: "Writes reports.",
          instructions_markdown: "Report writer instructions.",
        };
      }
      if (url === "/api/skills/custom/skill-2/versions/version-9") {
        return {
          description: "Writes the weekly report.",
          instructions_markdown: "Weekly report instructions.",
        };
      }
      throw new Error(`unexpected ${url}`);
    });
    mockReviewSkillVersion.mockReset().mockResolvedValue({});
    Object.values(mockToast).forEach((fn) => fn.mockReset());
  });

  it("lists each pending request with its version and author", async () => {
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    expect(await screen.findByText("report-writer")).toBeVisible();
    expect(screen.getByText("v1 · First publish")).toBeVisible();
    expect(screen.getByText("v3 · Update from v2")).toBeVisible();
    expect(screen.getAllByText("author@example.com")).toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledWith("/api/skills/review-requests");
  });

  it("opens a review with the version content before any decision", async () => {
    const user = setupUser();
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    await user.click(
      await screen.findByRole("button", { name: "Review weekly-report" })
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAccessibleName(/^weekly-report/);
    expect(dialog).toHaveAccessibleDescription("v3 · Update from v2");
    expect(
      await within(dialog).findByText("Weekly report instructions.")
    ).toBeVisible();
    expect(within(dialog).getByText("Writes the weekly report.")).toBeVisible();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/skills/custom/skill-2/versions/version-9"
    );
    expect(mockReviewSkillVersion).not.toHaveBeenCalled();
  });

  it("approves a request from the review and refreshes the skills", async () => {
    const user = setupUser();
    const onReviewed = jest.fn();
    render(<SkillReviewRequests onReviewed={onReviewed} />);

    await user.click(
      await screen.findByRole("button", { name: "Review weekly-report" })
    );
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Weekly report instructions.");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(mockReviewSkillVersion).toHaveBeenCalledWith(
        "skill-2",
        "version-9",
        "approve"
      )
    );
    expect(mockToast.success).toHaveBeenCalledWith(
      "Published version 3 of weekly-report."
    );
    expect(onReviewed).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    );
  });

  it("keeps Approve off while the version content cannot load", async () => {
    const user = setupUser();
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/api/skills/review-requests") return [request()];
      throw new Error("boom");
    });
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    await user.click(
      await screen.findByRole("button", { name: "Review report-writer" })
    );
    const dialog = await screen.findByRole("dialog");

    expect(
      await within(dialog).findByText("Couldn't load this version")
    ).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: "Approve" })
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("shows the server detail when an approve hits a name clash", async () => {
    const user = setupUser();
    mockReviewSkillVersion.mockRejectedValue(
      new Error("A published skill named report-writer already exists.")
    );
    const onReviewed = jest.fn();
    render(<SkillReviewRequests onReviewed={onReviewed} />);

    await user.click(
      await screen.findByRole("button", { name: "Review report-writer" })
    );
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Report writer instructions.");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        "A published skill named report-writer already exists."
      )
    );
    expect(onReviewed).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("denies a request from the review", async () => {
    const user = setupUser();
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    await user.click(
      await screen.findByRole("button", { name: "Review report-writer" })
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Deny" }));

    await waitFor(() =>
      expect(mockReviewSkillVersion).toHaveBeenCalledWith(
        "skill-1",
        "version-1",
        "deny"
      )
    );
    expect(mockToast.success).toHaveBeenCalledWith(
      "Denied version 1 of report-writer."
    );
  });

  it("renders nothing when no skills wait for review", async () => {
    mockFetch.mockResolvedValue([]);
    const { container } = render(
      <SkillReviewRequests onReviewed={jest.fn()} />
    );

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the list fails to load", async () => {
    mockFetch.mockRejectedValue(new Error("boom"));
    const { container } = render(
      <SkillReviewRequests onReviewed={jest.fn()} />
    );

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
