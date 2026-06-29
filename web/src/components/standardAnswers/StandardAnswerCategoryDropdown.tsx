import { FC } from "react";
import { StandardAnswerCategoryResponse } from "./getStandardAnswerCategoriesIfEE";
import { Label } from "@/components/Field";
import { InputComboBoxMulti } from "@/refresh-components/inputs/InputComboBox";
import { StandardAnswerCategory } from "@/lib/types";
import { ErrorCallout } from "../ErrorCallout";
import { LoadingAnimation } from "../Loading";

interface StandardAnswerCategoryDropdownFieldProps {
  standardAnswerCategoryResponse: StandardAnswerCategoryResponse;
  categories: StandardAnswerCategory[];
  setCategories: (categories: StandardAnswerCategory[]) => void;
}

export const StandardAnswerCategoryDropdownField: FC<
  StandardAnswerCategoryDropdownFieldProps
> = ({ standardAnswerCategoryResponse, categories, setCategories }) => {
  if (!standardAnswerCategoryResponse.paidEnterpriseFeaturesEnabled) {
    return null;
  }

  if (standardAnswerCategoryResponse.error != null) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answer categories - ${standardAnswerCategoryResponse.error.message}`}
      />
    );
  }

  if (standardAnswerCategoryResponse.categories == null) {
    return <LoadingAnimation />;
  }

  return (
    <>
      <div>
        <Label>Standard Answer Categories</Label>
        <div className="w-64">
          <InputComboBoxMulti
            name="standard_answer_categories"
            placeholder="Select categories"
            onChange={(selectedOptions) => {
              const selectedCategories = selectedOptions.map((option) => ({
                id: Number(option.value),
                name: option.label,
              }));
              setCategories(selectedCategories);
            }}
            options={standardAnswerCategoryResponse.categories.map(
              (category) => ({
                label: category.name,
                value: category.id.toString(),
              })
            )}
            selected={categories.map((category) => ({
              label: category.name,
              value: category.id.toString(),
            }))}
          />
        </div>
      </div>
    </>
  );
};
