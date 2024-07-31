import { ValidSources } from "@/lib/types";

export function buildCCPairInfoUrl(ccPairId: string | number) {
  return `/api/manage/admin/cc-pair/${ccPairId}`;
}

export function buildSimilarCredentialInfoURL(source_type: ValidSources) {
  return `/api/manage/admin/similar-credentials/${source_type}`;
}
