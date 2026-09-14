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
  ccPairId: number
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
