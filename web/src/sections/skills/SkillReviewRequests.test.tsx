import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
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
    requested_by_email: "author@example.com",
    requested_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

describe("SkillReviewRequests", () => {
  beforeEach(() => {
    mockFetch.mockReset().mockResolvedValue([
      request(),
      request({
        skill_id: "skill-2",
        name: "weekly-report",
        version_id: "version-9",
        version_number: 3,
        published_version_number: 2,
      }),
    ]);
    mockReviewSkillVersion.mockReset().mockResolvedValue({});
    Object.values(mockToast).forEach((fn) => fn.mockReset());
  });

  it("lists each pending request with its kind and requester", async () => {
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    expect(await screen.findByText("report-writer")).toBeVisible();
    expect(screen.getByText("First publish")).toBeVisible();
    expect(screen.getByText("Update from version 2")).toBeVisible();
    expect(screen.getAllByText("author@example.com")).toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledWith("/api/skills/review-requests");
  });

  it("approves a request and refreshes the skills", async () => {
    const user = setupUser();
    const onReviewed = jest.fn();
    render(<SkillReviewRequests onReviewed={onReviewed} />);

    await user.click(
      await screen.findByRole("button", { name: "Approve weekly-report" })
    );

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
  });

  it("shows the server detail when an approve hits a name clash", async () => {
    const user = setupUser();
    mockReviewSkillVersion.mockRejectedValue(
      new Error("A published skill named report-writer already exists.")
    );
    const onReviewed = jest.fn();
    render(<SkillReviewRequests onReviewed={onReviewed} />);

    await user.click(
      await screen.findByRole("button", { name: "Approve report-writer" })
    );

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        "A published skill named report-writer already exists."
      )
    );
    expect(onReviewed).not.toHaveBeenCalled();
  });

  it("denies a request", async () => {
    const user = setupUser();
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    await user.click(
      await screen.findByRole("button", { name: "Deny report-writer" })
    );

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

  it("says when no skills wait for review", async () => {
    mockFetch.mockResolvedValue([]);
    render(<SkillReviewRequests onReviewed={jest.fn()} />);

    expect(
      await screen.findByText("No skills are waiting for review.")
    ).toBeVisible();
  });
});
