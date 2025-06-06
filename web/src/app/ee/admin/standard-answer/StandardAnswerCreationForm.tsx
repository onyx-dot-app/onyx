"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import { useRouter } from "next/navigation";
import * as Yup from "yup";
import {
  createStandardAnswer,
  createStandardAnswerCategory,
  StandardAnswerCreationRequest,
  updateStandardAnswer,
} from "./lib";
import {
  TextFormField,
  MarkdownFormField,
  BooleanFormField,
  SelectorFormField,
} from "@/components/Field";
import MultiSelectDropdown from "@/components/MultiSelectDropdown";

function mapKeywordSelectToMatchAny(keywordSelect: "any" | "all"): boolean {
  return keywordSelect == "any";
}

function mapMatchAnyToKeywordSelect(matchAny: boolean): "any" | "all" {
  return matchAny ? "any" : "all";
}

export const StandardAnswerCreationForm = ({
  standardAnswerCategories,
  existingStandardAnswer,
}: {
  standardAnswerCategories: StandardAnswerCategory[];
  existingStandardAnswer?: StandardAnswer;
}) => {
  const isUpdate = existingStandardAnswer !== undefined;
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  return (
    <div>
      <CardSection>
        {popup}
        <Formik
          initialValues={{
            keyword: existingStandardAnswer
              ? existingStandardAnswer.keyword
              : "",
            answer: existingStandardAnswer ? existingStandardAnswer.answer : "",
            categories: existingStandardAnswer
              ? existingStandardAnswer.categories
              : [],
            matchRegex: existingStandardAnswer
              ? existingStandardAnswer.match_regex
              : false,
            matchAnyKeywords: existingStandardAnswer
              ? mapMatchAnyToKeywordSelect(
                  existingStandardAnswer.match_any_keywords
                )
              : "all",
          }}
          validationSchema={Yup.object().shape({
            keyword: Yup.string()
              .required("Keywords or pattern is required")
              .max(255)
              .min(1),
            answer: Yup.string().required("Answer is required").min(1),
            categories: Yup.array()
              .required()
              .min(1, "At least one category is required"),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const cleanedValues: StandardAnswerCreationRequest = {
              ...values,
              matchAnyKeywords: mapKeywordSelectToMatchAny(
                values.matchAnyKeywords
              ),
              categories: values.categories.map((category) => category.id),
            };

            let response;
            if (isUpdate) {
              response = await updateStandardAnswer(
                existingStandardAnswer.id,
                cleanedValues
              );
            } else {
              response = await createStandardAnswer(cleanedValues);
            }
            formikHelpers.setSubmitting(false);
            if (response.ok) {
              router.push(`/admin/standard-answer?u=${Date.now()}`);
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: isUpdate
                  ? `Error updating Standard Answer - ${errorMsg}`
                  : `Error creating Standard Answer - ${errorMsg}`,
                type: "error",
              });
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              {values.matchRegex ? (
                <TextFormField
                  name="keyword"
                  label="Regex pattern"
                  isCode
                  tooltip="Triggers if the question matches this regex pattern (using Python `re.search()`)"
                  placeholder="(?:it|support)\s*ticket"
                />
              ) : values.matchAnyKeywords == "any" ? (
                <TextFormField
                  name="keyword"
                  label="Any of these keywords, separated by spaces"
                  tooltip="A question must match these keywords in order to trigger the answer."
                  placeholder="ticket problem issue"
                  autoCompleteDisabled={true}
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label="All of these keywords, in any order, separated by spaces"
                  tooltip="A question must match these keywords in order to trigger the answer."
                  placeholder="it ticket"
                  autoCompleteDisabled={true}
                />
              )}
              <BooleanFormField
                subtext="Match a regex pattern instead of an exact keyword"
                optional
                label="Match regex"
                name="matchRegex"
              />
              {values.matchRegex ? null : (
                <SelectorFormField
                  defaultValue={`all`}
                  label="Keyword detection strategy"
                  subtext="Choose whether to require the user's question to contain any or all of the keywords above to show this answer."
                  name="matchAnyKeywords"
                  options={[
                    {
                      name: "All keywords",
                      value: "all",
                    },
                    {
                      name: "Any keywords",
                      value: "any",
                    },
                  ]}
                  onSelect={(selected) => {
                    setFieldValue("matchAnyKeywords", selected);
                  }}
                />
              )}
              <div className="w-full">
                <MarkdownFormField
                  name="answer"
                  label="Answer"
                  placeholder="The answer in Markdown. Example: If you need any help from the IT team, please email internalsupport@company.com"
                />
              </div>
              <div className="w-4/12">
                <MultiSelectDropdown
                  name="categories"
                  label="Categories:"
                  onChange={(selected_options) => {
                    const selected_categories = selected_options.map(
                      (option) => {
                        return { id: Number(option.value), name: option.label };
                      }
                    );
                    setFieldValue("categories", selected_categories);
                  }}
                  creatable={true}
                  onCreate={async (created_name) => {
                    const response = await createStandardAnswerCategory({
                      name: created_name,
                    });
                    const newCategory = await response.json();
                    return {
                      label: newCategory.name,
                      value: newCategory.id.toString(),
                    };
                  }}
                  options={standardAnswerCategories.map((category) => ({
                    label: category.name,
                    value: category.id.toString(),
                  }))}
                  initialSelectedOptions={values.categories.map((category) => ({
                    label: category.name,
                    value: category.id.toString(),
                  }))}
                />
              </div>
              <div className="py-4 flex">
                <Button
                  type="submit"
                  variant="submit"
                  disabled={isSubmitting}
                  className="mx-auto w-64"
                >
                  {isUpdate ? "Update!" : "Create!"}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
