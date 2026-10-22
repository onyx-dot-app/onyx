// The banner promises a slow re-embed only when the port re-embeds.
import { render, screen } from "@tests/setup/test-utils";
import type { ReindexProgress } from "@/lib/searchSettings/types";
import ReindexProgressBanner from "@/views/admin/IndexSettingsPage/ReindexProgressBanner";

const mockUseReindexProgress = jest.fn();

jest.mock("@/lib/searchSettings/hooks", () => ({
  useReindexProgress: () => mockUseReindexProgress(),
}));

function progress(reembeds: boolean): { data: ReindexProgress } {
  return {
    data: {
      total: 3,
      waiting: 1,
      in_progress: 1,
      completed: 1,
      failed: 0,
      paused: 0,
      reembeds,
    },
  };
}

describe("ReindexProgressBanner", () => {
  it("warns about re-embedding when the port re-embeds", () => {
    mockUseReindexProgress.mockReturnValue(progress(true));

    render(<ReindexProgressBanner secondaryModelName="intfloat/e5-base-v2" />);

    expect(screen.getByText("Re-indexing in progress…")).toBeVisible();
    expect(screen.getByText(/hours or days/)).toBeVisible();
    expect(screen.queryByText("Rebuilding the index…")).toBeNull();
  });

  it("keeps the re-index text when the flag is missing", () => {
    const { reembeds: _omitted, ...counts } = progress(true).data;
    mockUseReindexProgress.mockReturnValue({ data: counts });

    render(<ReindexProgressBanner secondaryModelName="intfloat/e5-base-v2" />);

    expect(screen.getByText("Re-indexing in progress…")).toBeVisible();
    expect(screen.queryByText("Rebuilding the index…")).toBeNull();
  });

  it("says the index is rebuilt without re-embedding when the port copies", () => {
    mockUseReindexProgress.mockReturnValue(progress(false));

    render(<ReindexProgressBanner secondaryModelName="intfloat/e5-base-v2" />);

    expect(screen.getByText("Rebuilding the index…")).toBeVisible();
    expect(screen.getByText(/without re-embedding/)).toBeVisible();
    expect(screen.queryByText(/hours or days/)).toBeNull();
    expect(screen.queryByText("Re-indexing in progress…")).toBeNull();
  });
});
