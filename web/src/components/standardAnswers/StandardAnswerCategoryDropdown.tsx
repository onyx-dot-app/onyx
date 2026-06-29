import { FC } from "react";
import { StandardAnswerCategoryResponse } from "./getStandardAnswerCategoriesIfEE";
import { Label } from "@/components/Field";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import Chip from "@/refresh-components/Chip";
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

  const allCategories = standardAnswerCategoryResponse.categories;
  const selectedIds = new Set(categories.map((category) => category.id));

  return (
    <div>
      <Label>Standard Answer Categories</Label>
      <div className="w-64 flex flex-col gap-2">
        <InputComboBox
          placeholder="Search categories..."
          value=""
          onChange={() => {}}
          onValueChange={(value) => {
            const category = allCategories.find(
              (candidate) => candidate.id.toString() === value
            );
            if (category && !selectedIds.has(category.id)) {
              setCategories([...categories, category]);
            }
          }}
          options={allCategories
            .filter((category) => !selectedIds.has(category.id))
            .map((category) => ({
              label: category.name,
              value: category.id.toString(),
            }))}
          strict
          searchIcon
        />

        {categories.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {categories.map((category) => (
              <Chip
                key={category.id}
                onRemove={() =>
                  setCategories(categories.filter((c) => c.id !== category.id))
                }
              >
                {category.name}
              </Chip>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
