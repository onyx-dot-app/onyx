import { render, screen } from "@tests/setup/test-utils";
import { useSandboxStatus } from "@/lib/sandbox-status/hooks";
import type { SandboxStatus } from "@/lib/sandbox-status/types";
import SandboxStatusPage from "@/views/admin/SandboxStatusPage/SandboxStatusPage";

jest.mock("@/lib/sandbox-status/hooks", () => ({
  useSandboxStatus: jest.fn(),
}));

const mockUseSandboxStatus = useSandboxStatus as jest.MockedFunction<
  typeof useSandboxStatus
>;

function mockStatus(data: SandboxStatus): void {
  mockUseSandboxStatus.mockReturnValue({
    data,
    error: undefined,
    isLoading: false,
    isValidating: false,
    mutate: jest.fn(),
  });
}

describe("SandboxStatusPage", () => {
  it("shows why tools are off when no node is registered", () => {
    mockStatus({
      runtime: "auto",
      template: "craft-fc-abc1234",
      tools_offered: false,
      tools_off_reason: "NO_REGISTERED_NODE",
      nodes: [],
    });
    render(<SandboxStatusPage />);

    expect(screen.getByText("Chat Sandbox Tools Are Off")).toBeInTheDocument();
    expect(
      screen.getByText(/No sandbox node is registered\. Add KVM nodes/)
    ).toBeInTheDocument();
    expect(screen.getByText("Runtime: auto")).toBeInTheDocument();
    expect(screen.queryAllByTestId("sandbox-status-node")).toHaveLength(0);
  });

  it("lists nodes with their template and report state", () => {
    mockStatus({
      runtime: "auto",
      template: "craft-fc-abc1234",
      tools_offered: true,
      tools_off_reason: null,
      nodes: [
        {
          node_id: "node-a",
          live: true,
          draining: false,
          has_template: true,
          last_report_age_seconds: 7,
          agent_version: "0.8.0",
          templates: ["craft-fc-abc1234-0123456789ab"],
          vm_count: 2,
          max_vms: 10,
        },
        {
          node_id: "node-b",
          live: false,
          draining: false,
          has_template: false,
          last_report_age_seconds: null,
          agent_version: null,
          templates: [],
          vm_count: null,
          max_vms: null,
        },
      ],
    });
    render(<SandboxStatusPage />);

    expect(screen.getByText("Chat Sandbox Tools Are On")).toBeInTheDocument();
    expect(screen.getAllByTestId("sandbox-status-node")).toHaveLength(2);
    expect(screen.getByText("Last report 7 seconds ago")).toBeInTheDocument();
    expect(screen.getByText("2 VMs of 10")).toBeInTheDocument();
    expect(screen.getByText("Agent version: 0.8.0")).toBeInTheDocument();
    expect(screen.getByText("No report yet")).toBeInTheDocument();
    expect(screen.getByText("Not Reporting")).toBeInTheDocument();
  });
});
