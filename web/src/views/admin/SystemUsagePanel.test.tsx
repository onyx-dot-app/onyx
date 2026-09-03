import { render, screen } from "@tests/setup/test-utils";
import SystemUsagePanel from "@/views/admin/SystemUsagePanel";
import { useSystemUsage } from "@/lib/usage/systemUsage";

jest.mock("@/lib/usage/systemUsage", () => ({
  useSystemUsage: jest.fn(),
}));

const mockUseSystemUsage = useSystemUsage as jest.MockedFunction<
  typeof useSystemUsage
>;

test("shows system and unattributed spend by category", () => {
  mockUseSystemUsage.mockReturnValue({
    usage: {
      start: "2026-09-01",
      end: "2026-09-02",
      categories: [
        {
          category: "image_summarization",
          totals: {
            input_tokens: 100,
            output_tokens: 20,
            cache_read_tokens: 0,
            cache_creation_tokens: 0,
            cost_cents: 200,
          },
          records: [
            {
              attribution: "ATTRIBUTED",
              model: "claude-sonnet",
              flow: "image_summarization",
              provider: "anthropic",
              day: "2026-09-01",
              input_tokens: 100,
              output_tokens: 20,
              cache_read_tokens: 0,
              cache_creation_tokens: 0,
              cost_cents: 200,
            },
          ],
        },
        {
          category: "unattributed",
          totals: {
            input_tokens: 50,
            output_tokens: 10,
            cache_read_tokens: 0,
            cache_creation_tokens: 0,
            cost_cents: 100,
          },
          records: [
            {
              attribution: "UNATTRIBUTED",
              model: "gpt-5",
              flow: "untagged_invoke",
              provider: "openai",
              day: "2026-09-01",
              input_tokens: 50,
              output_tokens: 10,
              cache_read_tokens: 0,
              cache_creation_tokens: 0,
              cost_cents: 100,
            },
          ],
        },
      ],
    },
    isLoading: false,
    error: undefined,
    refetch: jest.fn(),
  });

  render(<SystemUsagePanel />);

  expect(screen.getByText("System usage")).toBeInTheDocument();
  expect(screen.getByText("Image summarization")).toBeInTheDocument();
  expect(screen.getAllByText("Unattributed").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("columnheader", { name: "Spend" })
  ).toBeInTheDocument();
  expect(screen.queryByText(/@/)).not.toBeInTheDocument();
});
