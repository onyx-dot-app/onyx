import { StandardAnswerCategory } from "@/lib/types";

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
