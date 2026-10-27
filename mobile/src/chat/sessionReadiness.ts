import { getChatSessionStatus } from "@/api/chat/sessions";

// Delivery can end before saving completes. Only the server can confirm readiness.
export async function waitForSessionIdle(
  sessionId: string,
  stillOurs: () => boolean,
  onUnconfirmed: () => void,
): Promise<boolean> {
  while (stillOurs()) {
    try {
      const status = await getChatSessionStatus(sessionId);
      if (!stillOurs()) return false;
      if (status.is_processing === false) return true;
      if (status.is_processing !== true) onUnconfirmed();
    } catch {
      if (!stillOurs()) return false;
      onUnconfirmed();
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}
