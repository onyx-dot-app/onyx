import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { BuildMessageAttachment } from "@/app/craft/types/streamingTypes";

describe("Craft queued messages", () => {
  beforeEach(() => {
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  });

  it("keeps attachments associated with their message across FIFO removal", () => {
    const sessionId = "session-1";
    const imageAttachments: BuildMessageAttachment[] = [
      {
        name: "reference.png",
        path: "attachments/reference.png",
        mimeType: "image/png",
      },
    ];
    const documentAttachments: BuildMessageAttachment[] = [
      {
        name: "brief.docx",
        path: "attachments/brief.docx",
        mimeType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    ];

    useBuildSessionStore.getState().createSession(sessionId);
    useBuildSessionStore
      .getState()
      .enqueueMessage(sessionId, "Inspect this image", imageAttachments);
    useBuildSessionStore
      .getState()
      .enqueueMessage(sessionId, "Summarize this brief", documentAttachments);
    useBuildSessionStore.getState().removeQueuedMessage(sessionId, 0);

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toEqual([
      {
        id: expect.any(Number),
        text: "Summarize this brief",
        attachments: documentAttachments,
      },
    ]);
  });
});
