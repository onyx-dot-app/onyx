import { PopupSpec } from "@/components/admin/connectors/Popup";
import { runConnector } from "@/lib/connector";
import { ValidSources } from "@/lib/types";
import { mutate } from "swr";

export function buildCCPairInfoUrl(ccPairId: string | number) {
  return `/api/manage/admin/cc-pair/${ccPairId}`;
}

export function buildSimilarCredentialInfoURL(
  source_type: ValidSources,
  get_editable: boolean = false
) {
  const base = `/api/manage/admin/similar-credentials/${source_type}`;
  return get_editable ? `${base}?get_editable=True` : base;
}

export async function triggerIndexing(
  fromBeginning: boolean,
  connectorId: number,
  credentialId: number,
  ccPairId: number,
  setPopup: (popupSpec: PopupSpec | null) => void
): Promise<{ success: boolean; message: string }> {
  const errorMsg = await runConnector(
    connectorId,
    [credentialId],
    fromBeginning
  );

  mutate(buildCCPairInfoUrl(ccPairId));

  if (errorMsg) {
    return {
      success: false,
      message: errorMsg,
    };
  } else {
    return {
      success: true,
      message: "Triggered connector run",
    };
  }
}

export function getTooltipMessage(
  isInvalid: boolean,
  isDeleting: boolean,
  isIndexing: boolean,
  isDisabled: boolean
): string | undefined {
  if (isInvalid) {
    return "Connector is in an invalid state. Please update the credentials or configuration before re-indexing.";
  }
  if (isDeleting) {
    return "Cannot index while connector is deleting";
  }
  if (isIndexing) {
    return "Indexing is already in progress";
  }
  if (isDisabled) {
    return "Connector must be re-enabled before indexing";
  }
  return undefined;
}
