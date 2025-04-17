"use client";
import i18n from "@/i18n/init";
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
              .required("Требуются ключевые слова или шаблон")
              .max(255)
              .min(1),
            answer: Yup.string().required("Требуется ответ").min(1),
            categories: Yup.array()
              .required()
              .min(1, "Требуется хотя бы одна категория"),
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
                  ? `${i18n.t(k.ERROR_UPDATING_STANDARD_ANSWER)} ${errorMsg}`
                  : `${i18n.t(k.ERROR_CREATING_STANDARD_ANSWER)} ${errorMsg}`,
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
                  tooltip="Срабатывает, если вопрос соответствует этому шаблону регулярного выражения (используя Python `re.search()`)"
                  placeholder="(?:it|support)\s*ticket"
                />
              ) : values.matchAnyKeywords == "any" ? (
                <TextFormField
                  name="keyword"
                  label="Любые из этих ключевых слов, разделенных пробелами"
                  tooltip="Вопрос должен соответствовать этим ключевым словам, чтобы вызвать ответ."
                  placeholder="проблема с билетом"
                  autoCompleteDisabled={true}
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label="Все эти ключевые слова в любом порядке, разделенные пробелами"
                  tooltip="Вопрос должен соответствовать этим ключевым словам, чтобы вызвать ответ."
                  placeholder="it ticket"
                  autoCompleteDisabled={true}
                />
              )}
              <BooleanFormField
                subtext="Сопоставить шаблон регулярного выражения вместо точного ключевого слова"
                optional
                label="Сопоставить регулярное выражение"
                name="matchRegex"
              />

              {values.matchRegex ? null : (
                <SelectorFormField
                  defaultValue={`all`}
                  label="Стратегия обнаружения ключевых слов"
                  subtext="Выберите, требуется ли, чтобы вопрос пользователя содержал какие-либо или все ключевые слова, указанные выше, для отображения этого ответа."
                  name="matchAnyKeywords"
                  options={[
                    {
                      name: i18n.t(k.ALL_KEYWORDS),
                      value: "all",
                    },
                    {
                      name: i18n.t(k.ANY_KEYWORDS),
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
                  label="Ответ"
                  placeholder="Ответ в Markdown. Пример: если вам нужна помощь от ИТ-отдела, отправьте электронное письмо на адрес internalsupport@company.com"
                />
              </div>
              <div className="w-4/12">
                <MultiSelectDropdown
                  name="categories"
                  label="Категории:"
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
                  {isUpdate ? i18n.t(k.UPDATE1) : i18n.t(k.CREATE)}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
