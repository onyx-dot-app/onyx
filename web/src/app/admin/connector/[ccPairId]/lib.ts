import { ValidSources } from "@/lib/types";

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
