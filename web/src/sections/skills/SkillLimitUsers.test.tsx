import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import SkillLimitUsers from "@/sections/skills/SkillLimitUsers";
import { Permission } from "@/lib/types";
import type { SkillLimitUserUsage } from "@/lib/skills/limits";
import { useSWRConfig } from "swr";
import { revalidateSkillUsage } from "@/lib/skills/hooks";

let mockPermissions: string[] = [];
let mockAdminCapabilities: string[] = [];
let mockUser: { id: string } | null = { id: "admin-id" };

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockUser,
    permissions: mockPermissions,
    adminCapabilities: mockAdminCapabilities,
  }),
}));

const MiB = 1024 * 1024;
const fetchMock = jest.fn();

function usageRow(
  id: string,
  email: string,
  overrides: Partial<SkillLimitUserUsage["usage"]>,
  omitted: number | null
): SkillLimitUserUsage {
  return {
    user: { id, email },
    usage: {
      bytes: 0,
      files: 0,
      unknown_skill_count: 0,
      charged_bytes: 0,
      charged_files: 0,
      max_bytes: 500 * MiB,
      max_files: 5000,
      ...overrides,
    },
    last_delivery_omitted_skill_count: omitted,
  };
}

function respond(body: unknown, status = 200) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(body), { status })
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock;
  mockPermissions = [Permission.MANAGE_SKILLS];
  mockAdminCapabilities = [];
  mockUser = { id: "admin-id" };
});

it("shows each user's measured or estimated usage and last-delivery omissions", async () => {
  respond([
    usageRow(
      "u1",
      "a-very-long-address-that-must-wrap@example.com",
      {
        bytes: 520 * MiB,
        files: 12,
        charged_bytes: 520 * MiB,
        charged_files: 12,
      },
      2
    ),
    usageRow(
      "u2",
      "estimated@example.com",
      {
        bytes: 450 * MiB,
        files: 30,
        unknown_skill_count: 1,
        charged_bytes: 550 * MiB,
        charged_files: 530,
      },
      0
    ),
    usageRow(
      "u3",
      "fresh@example.com",
      { charged_bytes: 10 * MiB, files: 5001, charged_files: 5001 },
      null
    ),
  ]);
  render(<SkillLimitUsers />);

  expect(
    await screen.findByText("3 users are over the skill limit")
  ).toBeInTheDocument();
  expect(
    screen.getByText(/more than 500 MB or 5,000 files of skills/)
  ).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/skills/limit/users");

  const table = screen.getByRole("table", {
    name: "Users over the skill limit",
  });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(rows[0]).toHaveTextContent(
    "a-very-long-address-that-must-wrap@example.com"
  );
  expect(rows[0]).toHaveTextContent("520 MB");
  expect(rows[0]).toHaveTextContent("12");
  expect(rows[0]).toHaveTextContent("2 skills");
  expect(rows[1]).toHaveTextContent(
    "About 550 MB (estimated: 1 skill not measured)"
  );
  expect(rows[1]).toHaveTextContent("About 530 (estimated)");
  expect(rows[1]).not.toHaveTextContent("450 MB");
  expect(rows[1]).toHaveTextContent("0 skills");
  expect(rows[2]).toHaveTextContent("5,001");
  expect(rows[2]).toHaveTextContent("No session yet");
});

it("shows nothing when no user is over the limit", async () => {
  respond([]);
  render(<SkillLimitUsers />);
  expect(screen.getByRole("status")).toHaveTextContent("Checking skill usage…");
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
  );
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByText(/over the skill limit/)).not.toBeInTheDocument();
});

it("offers a retry after a failed load", async () => {
  respond({ detail: "Server error" }, 500);
  const user = setupUser();
  render(<SkillLimitUsers />);
  expect(
    await screen.findByText("Could not load skill usage")
  ).toBeInTheDocument();

  respond([
    usageRow("u1", "over@example.com", { charged_bytes: 600 * MiB }, 1),
  ]);
  await user.click(screen.getByRole("button", { name: "Try Again" }));
  expect(
    await screen.findByText("1 user is over the skill limit")
  ).toBeInTheDocument();
  expect(screen.queryByText("Could not load skill usage")).toBeNull();
});

it.each([
  ["a scoped manager", [], [Permission.MANAGE_SKILLS]],
  ["a member", [], []],
])("never requests admin usage for %s", (_, permissions, capabilities) => {
  mockPermissions = permissions;
  mockAdminCapabilities = capabilities;
  const { container } = render(<SkillLimitUsers />);
  expect(container).toBeEmptyDOMElement();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("drops loaded rows when global authority is lost", async () => {
  respond([
    usageRow("u1", "over@example.com", { charged_bytes: 600 * MiB }, 1),
  ]);
  const { rerender } = render(<SkillLimitUsers />);
  expect(await screen.findByText("over@example.com")).toBeInTheDocument();

  mockPermissions = [];
  mockAdminCapabilities = [Permission.MANAGE_SKILLS];
  rerender(<SkillLimitUsers />);
  expect(screen.queryByText("over@example.com")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it.each([403, 500, 200])(
  "hides prior rows after an unusable %s refetch and allows retry",
  async (status) => {
    function UsageWithRefresh() {
      const { mutate } = useSWRConfig();
      return (
        <>
          <button onClick={() => void revalidateSkillUsage(mutate)}>
            Refresh usage
          </button>
          <SkillLimitUsers />
        </>
      );
    }
    respond([
      usageRow("u1", "prior@example.com", { charged_bytes: 600 * MiB }, 1),
    ]);
    const user = setupUser();
    render(<UsageWithRefresh />);
    expect(await screen.findByText("prior@example.com")).toBeInTheDocument();

    respond({ detail: "Usage unavailable" }, status);
    await user.click(screen.getByRole("button", { name: "Refresh usage" }));
    expect(
      await screen.findByText("Could not load skill usage")
    ).toBeInTheDocument();
    expect(screen.queryByText("prior@example.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    respond([
      usageRow("u2", "current@example.com", { charged_bytes: 550 * MiB }, 0),
    ]);
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("current@example.com")).toBeInTheDocument();
    expect(screen.queryByText("prior@example.com")).not.toBeInTheDocument();
  }
);

it("never shows another signed-in user's cached usage rows", async () => {
  respond([
    usageRow("u1", "prior@example.com", { charged_bytes: 600 * MiB }, 1),
  ]);
  const { rerender } = render(<SkillLimitUsers />);
  expect(await screen.findByText("prior@example.com")).toBeInTheDocument();

  mockUser = { id: "another-admin" };
  respond([
    usageRow("u2", "current@example.com", { charged_bytes: 550 * MiB }, 0),
  ]);
  rerender(<SkillLimitUsers />);
  expect(screen.queryByText("prior@example.com")).not.toBeInTheDocument();
  expect(await screen.findByText("current@example.com")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
