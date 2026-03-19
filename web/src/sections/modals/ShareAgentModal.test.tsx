import React, { useEffect } from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import ShareAgentModal, { ShareAgentModalProps } from "./ShareAgentModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";

jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: jest.fn(() => ({ data: [] })),
}));

jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: jest.fn(() => ({ data: [] })),
}));

jest.mock("@/hooks/useAgents", () => ({
  useAgent: jest.fn(() => ({ agent: null })),
}));

jest.mock("@/lib/hooks", () => ({
  useLabels: jest.fn(() => ({
    labels: [],
    createLabel: jest.fn(),
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
    userIds: [],
    groupIds: [],
    isPublic: false,
    isFeatured: false,
    labelIds: [],
    ...overrides,
  };

  return render(<ModalHarness {...props} />);
}

describe("ShareAgentModal", () => {
  it("defaults to Users & Groups when the agent is private", async () => {
    renderShareAgentModal({ isPublic: false });

    await waitFor(() =>
      expect(
        screen.getByRole("tab", { name: "Users & Groups" })
      ).toHaveAttribute("data-state", "active")
    );

    expect(
      screen.getByRole("tab", { name: "Your Organization" })
    ).toHaveAttribute("data-state", "inactive");
  });

  it("defaults to Your Organization when the agent is public", async () => {
    renderShareAgentModal({ isPublic: true });

    await waitFor(() =>
      expect(
        screen.getByRole("tab", { name: "Your Organization" })
      ).toHaveAttribute("data-state", "active")
    );

    expect(screen.getByRole("tab", { name: "Users & Groups" })).toHaveAttribute(
      "data-state",
      "inactive"
    );
  });
});
