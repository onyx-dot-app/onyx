import {
  ChatSession,
  ChatSessionSharedStatus,
} from "@/app/app/interfaces";
import {
  persistHideMoveCustomAgentModal,
  shouldHideMoveCustomAgentModal,
  shouldShowMoveModal,
} from "@/sections/sidebar/sidebarUtils";

function createChatSession(personaId: number): ChatSession {
  return {
    id: "chat-1",
    name: "Chat",
    persona_id: personaId,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    project_id: null,
    current_alternate_model: "",
    current_temperature_override: null,
  };
}

describe("sidebarUtils localStorage migration", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("migrates the legacy hide-move-modal key to the activa prefix", () => {
    localStorage.setItem("onyx:hideMoveCustomAgentModal", "true");

    expect(shouldHideMoveCustomAgentModal()).toBe(true);
    expect(localStorage.getItem("activa:hideMoveCustomAgentModal")).toBe(
      "true"
    );
    expect(localStorage.getItem("onyx:hideMoveCustomAgentModal")).toBeNull();
  });

  it("persists the hide-move-modal preference with the activa prefix", () => {
    persistHideMoveCustomAgentModal();

    expect(localStorage.getItem("activa:hideMoveCustomAgentModal")).toBe(
      "true"
    );
    expect(localStorage.getItem("onyx:hideMoveCustomAgentModal")).toBeNull();
  });

  it("suppresses the move modal when the migrated preference exists", () => {
    localStorage.setItem("onyx:hideMoveCustomAgentModal", "true");

    expect(shouldShowMoveModal(createChatSession(2))).toBe(false);
  });
});
