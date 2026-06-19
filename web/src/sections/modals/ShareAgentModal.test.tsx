import React, { useEffect } from "react";
import { render, screen } from "@tests/setup/test-utils";
import ShareAgentModal, { ShareAgentModalProps } from "./ShareAgentModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";

jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: jest.fn(() => ({
    data: [
      {
        email: "owner@example.com",
        id: "owner-id",
      },
    ],
  })),
}));

jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: jest.fn(() => ({ data: [] })),
}));

jest.mock("@/lib/agents/hooks", () => ({
  useAgent: jest.fn(() => ({
    agent: {
      admin_count: 1,
      attached_document_count: 0,
      builtin_persona: false,
      datetime_aware: false,
      default_model_configuration_id: null,
      description: "Test agent",
      display_priority: null,
      document_sets: [],
      group_shares: [],
      groups: [],
      hierarchy_node_count: 0,
      id: 101,
      is_featured: false,
      is_listed: true,
      is_public: false,
      labels: [],
      name: "Demo Agent",
      owner: {
        email: "owner@example.com",
        id: "owner-id",
      },
      owner_group: null,
      ownership_vacant: false,
      public_permission: "VIEWER",
      replace_base_system_prompt: false,
      search_start_date: null,
      sharing_status: "PRIVATE",
      starter_messages: null,
      system_prompt: null,
      task_prompt: null,
      tool_ids: [],
      tools: [],
      uploaded_image_id: undefined,
      user_file_ids: [],
      user_permission: "OWNER",
      user_shares: [],
      users: [],
    },
  })),
  useLabels: jest.fn(() => ({
    createLabel: jest.fn(),
    labels: [],
  })),
}));

function ModalHarness(props: ShareAgentModalProps) {
  const modal = useCreateModal();

  useEffect(() => {
    modal.toggle(true);
  }, [modal]);

  return (
    <modal.Provider>
      <ShareAgentModal {...props} />
    </modal.Provider>
  );
}

function renderShareAgentModal(overrides: Partial<ShareAgentModalProps> = {}) {
  const props: ShareAgentModalProps = {
    agentId: 101,
    groupIds: [],
    isFeatured: false,
    isPublic: false,
    labelIds: [],
    userIds: [],
    ...overrides,
  };

  return render(<ModalHarness {...props} />);
}

describe("ShareAgentModal", () => {
  it("renders the new share view", async () => {
    renderShareAgentModal();

    expect(await screen.findByText(/Share/)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Add users, groups, and accounts")
    ).toBeInTheDocument();
    expect(screen.getByText("Admins")).toBeInTheDocument();
    expect(screen.getByText("Only those invited")).toBeInTheDocument();
  });
});
