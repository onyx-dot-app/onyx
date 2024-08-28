import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";

export async function setCCPairStatus(
  ccPairId: number,
  ccPairStatus: ConnectorCredentialPairStatus,
  setPopup?: (popupSpec: PopupSpec | null) => void,
  onUpdate?: () => void
) {
  try {
    const response = await fetch(
      `/api/manage/admin/cc-pair/${ccPairId}/status`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ status: ccPairStatus }),
      }
    );

    if (!response.ok) {
      const { detail } = await response.json();
      setPopup?.({
        message: `Failed to update connector status - ${detail}`,
        type: "error",
      });
      return;
    }

    setPopup?.({
      message:
        ccPairStatus === ConnectorCredentialPairStatus.ACTIVE
          ? "Enabled connector!"
          : "Paused connector!",
      type: "success",
    });

    onUpdate && onUpdate();
  } catch (error) {
    console.error("Error updating CC pair status:", error);
    setPopup &&
      setPopup({
        message: "Failed to update connector status",
        type: "error",
      });
  }
}
