"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

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
} from "@/components/admin/connectors/Field";
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
  const { t } = useTranslation();
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
              .required(t(k.KEYWORDS_OR_PATTERN_REQUIRED))
              .max(255)
              .min(1),
            answer: Yup.string().required(t(k.ANSWER_REQUIRED)).min(1),
            categories: Yup.array()
              .required()
              .min(1, t(k.AT_LEAST_ONE_CATEGORY_REQUIRED)),
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
                  ? `${t(k.ERROR_UPDATING_STANDARD_ANSWER)} ${errorMsg}`
                  : `${t(k.ERROR_CREATING_STANDARD_ANSWER)} ${errorMsg}`,
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
                  tooltip={t(k.REGEX_TOOLTIP)}
                  placeholder="(?:it|support)\s*ticket"
                />
              ) : values.matchAnyKeywords == "any" ? (
                <TextFormField
                  name="keyword"
                  label={t(k.ANY_KEYWORDS_LABEL)}
                  tooltip={t(k.ANY_KEYWORDS_TOOLTIP)}
                  placeholder={t(k.ANY_KEYWORDS_PLACEHOLDER)}
                  autoCompleteDisabled={true}
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label={t(k.ALL_KEYWORDS_LABEL)}
                  tooltip={t(k.ALL_KEYWORDS_TOOLTIP)}
                  placeholder="it ticket"
                  autoCompleteDisabled={true}
                />
              )}
              <BooleanFormField
                subtext={t(k.MATCH_REGEX_SUBTEXT)}
                optional
                label={t(k.MATCH_REGEX_LABEL)}
                name="matchRegex"
              />

              {values.matchRegex ? null : (
                <SelectorFormField
                  defaultValue={`all`}
                  label={t(k.KEYWORD_DETECTION_STRATEGY)}
                  subtext={t(k.KEYWORD_DETECTION_SUBTEXT)}
                  name="matchAnyKeywords"
                  options={[
                    {
                      name: t(k.ALL_KEYWORDS),
                      value: "all",
                    },
                    {
                      name: t(k.ANY_KEYWORDS),
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
                  label={t(k.ANSWER_LABEL)}
                  placeholder={t(k.ANSWER_PLACEHOLDER)}
                />
              </div>
              <div className="w-4/12">
                <MultiSelectDropdown
                  name="categories"
                  label={t(k.CATEGORIES_LABEL)}
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
                  {isUpdate ? t(k.UPDATE1) : t(k.CREATE)}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
