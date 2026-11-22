import { render, screen, waitFor } from "@tests/setup/test-utils";
import SkillLimitUsersBanner from "@/sections/skills/SkillLimitUsersBanner";
import type { SkillLimitUsersResponse } from "@/lib/skills/limits";

const mockFetch = jest.fn();

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockFetch(...args),
}));

const MB = 1024 * 1024;

function response(
  users: SkillLimitUsersResponse["users"]
): SkillLimitUsersResponse {
  return {
    max_bytes: 500 * MB,
    max_files: 5000,
    users,
  };
}

describe("SkillLimitUsersBanner", () => {
  beforeEach(() => mockFetch.mockReset());

  it("lists each user past the limit with size, files and skills not loaded", async () => {
    mockFetch.mockResolvedValue(
      response([
        {
          user_id: "u1",
          email: "big@example.com",
          usage: { bytes: 950 * MB, files: 1200 },
          skills_not_loaded: 2,
        },
        {
          user_id: "u2",
          email: "files@example.com",
          usage: { bytes: 20 * MB, files: 5001 },
          skills_not_loaded: 0,
        },
      ])
    );

    render(<SkillLimitUsersBanner />);

    expect(
      await screen.findByText("2 users are past the skill limit")
    ).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith("/api/skills/users-over-limit");
    expect(
      screen.getByText(
        "Group settings and shares can put a user past 500 MB or 5,000 files of skills. Some of their skills may then not load. Change group settings, or ask users to turn off skills."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "big@example.com: 950 MB, 1,200 files, 2 skills did not load"
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "files@example.com: 20 MB, 5,001 files, 0 skills did not load"
      )
    ).toBeInTheDocument();
  });

  it("names the first ten users and counts the rest", async () => {
    mockFetch.mockResolvedValue(
      response(
        Array.from({ length: 12 }, (_, index) => ({
          user_id: `u${index}`,
          email: `user${index}@example.com`,
          usage: { bytes: 600 * MB, files: 10 },
          skills_not_loaded: 0,
        }))
      )
    );

    render(<SkillLimitUsersBanner />);

    expect(await screen.findByText("And 2 more.")).toBeInTheDocument();
    expect(screen.getByText(/^user9@example.com/)).toBeInTheDocument();
    expect(screen.queryByText(/^user10@example.com/)).not.toBeInTheDocument();
  });

  it("shows nothing when no user is past the limit", async () => {
    mockFetch.mockResolvedValue(response([]));

    const { container } = render(<SkillLimitUsersBanner />);

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
