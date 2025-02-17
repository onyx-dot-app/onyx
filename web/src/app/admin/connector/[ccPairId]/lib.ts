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
) {
  const errorMsg = await runConnector(
    connectorId,
    [credentialId],
    fromBeginning
  );
  if (errorMsg) {
    setPopup({
      message: errorMsg,
      type: "error",
    });
  } else {
    setPopup({
      message: "Triggered connector run",
      type: "success",
    });
  }
  mutate(buildCCPairInfoUrl(ccPairId));
}
