import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";
import { StandardAnswerCategory } from "@/lib/types";
import { fetchSS } from "@/lib/utilsSS";

export type StandardAnswerCategoryResponse =
  | EEStandardAnswerCategoryResponse
  | NoEEAvailable;

interface NoEEAvailable {
  paidEnterpriseFeaturesEnabled: false;
}

interface EEStandardAnswerCategoryResponse {
  paidEnterpriseFeaturesEnabled: true;
  error?: {
    message: string;
  };
  categories?: StandardAnswerCategory[];
}

export async function getStandardAnswerCategoriesIfEE(): Promise<StandardAnswerCategoryResponse> {
  if (!SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    return {
      paidEnterpriseFeaturesEnabled: false,
    };
  }

  const standardAnswerCategoriesResponse = await fetchSS(
    "/manage/admin/standard-answer/category"
  );
  if (!standardAnswerCategoriesResponse.ok) {
    return {
      paidEnterpriseFeaturesEnabled: true,
      error: {
        message: await standardAnswerCategoriesResponse.text(),
      },
    };
  }

  const categories =
    (await standardAnswerCategoriesResponse.json()) as StandardAnswerCategory[];

  return {
    paidEnterpriseFeaturesEnabled: true,
    categories,
  };
}
