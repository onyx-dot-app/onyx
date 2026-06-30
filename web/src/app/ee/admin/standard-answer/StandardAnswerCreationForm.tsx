"use client";

import { useState } from "react";
import { toast } from "@/hooks/useToast";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import Button from "@/refresh-components/buttons/Button";
import { Form, Formik, ErrorMessage } from "formik";
import { useRouter } from "next/navigation";
import type { Route } from "next";
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
  Label,
} from "@/components/Field";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import { Text } from "@opal/components";

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
  const router = useRouter();
  const [categoryInput, setCategoryInput] = useState("");

  return (
    <div>
      <CardSection>
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
              router.push(`/ee/admin/standard-answer?u=${Date.now()}` as Route);
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              toast.error(
                isUpdate
                  ? `Error updating Standard Answer - ${errorMsg}`
                  : `Error creating Standard Answer - ${errorMsg}`
              );
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
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label="All of these keywords, in any order, separated by spaces"
                  tooltip="A question must match these keywords in order to trigger the answer."
                  placeholder="it ticket"
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
              <div className="w-4/12 flex flex-col gap-2">
                <Label>Categories:</Label>
                <InputChipField
                  placeholder="Type a category and press Enter…"
                  value={categoryInput}
                  onChange={setCategoryInput}
                  chips={values.categories.map((category) => ({
                    id: category.id.toString(),
                    label: category.name,
                  }))}
                  onRemoveChip={(id) =>
                    setFieldValue(
                      "categories",
                      values.categories.filter((c) => c.id.toString() !== id)
                    )
                  }
                  onAdd={async (name) => {
                    setCategoryInput("");

                    // Skip if already selected. This also covers categories
                    // created earlier this session, which won't appear in the
                    // `standardAnswerCategories` prop snapshot — so re-typing
                    // the same name never fires a duplicate create.
                    if (
                      values.categories.some(
                        (c) => c.name.toLowerCase() === name.toLowerCase()
                      )
                    ) {
                      return;
                    }

                    // Reuse an existing category (case-insensitive) rather than
                    // creating a duplicate.
                    const existing = standardAnswerCategories.find(
                      (category) =>
                        category.name.toLowerCase() === name.toLowerCase()
                    );
                    if (existing) {
                      setFieldValue("categories", [
                        ...values.categories,
                        existing,
                      ]);
                      return;
                    }

                    const response = await createStandardAnswerCategory({
                      name,
                    });
                    if (!response.ok) {
                      const responseJson = await response.json();
                      const errorMsg =
                        responseJson.detail || responseJson.message;
                      toast.error(
                        `Error creating category "${name}" - ${errorMsg}`
                      );
                      return;
                    }
                    const newCategory =
                      (await response.json()) as StandardAnswerCategory;
                    setFieldValue("categories", [
                      ...values.categories,
                      newCategory,
                    ]);
                  }}
                />

                <ErrorMessage name="categories" component="div">
                  {(msg) => (
                    <Text as="p" font="secondary-body" color="status-error-05">
                      {msg}
                    </Text>
                  )}
                </ErrorMessage>
              </div>
              <div className="py-4 flex">
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <Button
                  type="submit"
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
