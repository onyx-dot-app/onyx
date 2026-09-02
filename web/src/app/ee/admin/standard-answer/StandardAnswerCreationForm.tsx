"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
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
import { Button, Text } from "@opal/components";

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
  const t = useTranslations("admin.standardAnswers");
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
              .required(t("form.validation.keywordRequired"))
              .max(255)
              .min(1),
            answer: Yup.string()
              .required(t("form.validation.answerRequired"))
              .min(1),
            categories: Yup.array()
              .required()
              .min(1, t("form.validation.categoryRequired")),
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
                  ? t("form.toasts.updateFailed.message", { error: errorMsg })
                  : t("form.toasts.createFailed.message", { error: errorMsg })
              );
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              {values.matchRegex ? (
                <TextFormField
                  name="keyword"
                  label={t("form.regexPattern.label")}
                  isCode
                  tooltip={t("form.regexPattern.tooltip")}
                  placeholder="(?:it|support)\s*ticket"
                />
              ) : values.matchAnyKeywords == "any" ? (
                <TextFormField
                  name="keyword"
                  label={t("form.anyKeywords.label")}
                  tooltip={t("form.keywords.tooltip")}
                  placeholder={t("form.anyKeywords.placeholder")}
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label={t("form.allKeywords.label")}
                  tooltip={t("form.keywords.tooltip")}
                  placeholder={t("form.allKeywords.placeholder")}
                />
              )}
              <BooleanFormField
                subtext={t("form.matchRegex.description")}
                optional
                label={t("form.matchRegex.label")}
                name="matchRegex"
              />
              {values.matchRegex ? null : (
                <SelectorFormField
                  defaultValue={`all`}
                  label={t("form.strategy.label")}
                  subtext={t("form.strategy.description")}
                  name="matchAnyKeywords"
                  options={[
                    {
                      name: t("form.strategy.all.label"),
                      value: "all",
                    },
                    {
                      name: t("form.strategy.any.label"),
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
                  label={t("form.answer.label")}
                  placeholder={t("form.answer.placeholder")}
                />
              </div>
              <div className="w-4/12 flex flex-col gap-2">
                <Label>{t("form.categories.label")}</Label>
                <InputChipField
                  placeholder={t("form.categories.placeholder")}
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
                        t("form.toasts.categoryCreateFailed.message", {
                          name,
                          error: errorMsg,
                        })
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
              <div className="py-4 mx-auto w-64">
                <Button type="submit" disabled={isSubmitting} width="full">
                  {isUpdate
                    ? t("form.updateButton.label")
                    : t("form.createButton.label")}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
