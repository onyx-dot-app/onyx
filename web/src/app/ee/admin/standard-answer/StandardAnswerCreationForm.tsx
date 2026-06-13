"use client";

import { toast } from "@/hooks/useToast";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import Button from "@/refresh-components/buttons/Button";
import { Form, Formik } from "formik";
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
  const router = useRouter();

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
              .required("请输入关键词或匹配模式")
              .max(255)
              .min(1),
            answer: Yup.string().required("请输入答案").min(1),
            categories: Yup.array()
              .required()
              .min(1, "请至少选择一个分类"),
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
                  ? `更新标准答案失败 - ${errorMsg}`
                  : `创建标准答案失败 - ${errorMsg}`
              );
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form>
              {values.matchRegex ? (
                <TextFormField
                  name="keyword"
                  label="Regex 模式"
                  isCode
                  tooltip="当问题匹配此 Regex 模式时触发（使用 Python `re.search()`）"
                  placeholder="(?:it|support)\s*ticket"
                />
              ) : values.matchAnyKeywords == "any" ? (
                <TextFormField
                  name="keyword"
                  label="任意关键词，用空格分隔"
                  tooltip="问题匹配这些关键词后才会触发此答案。"
                  placeholder="ticket problem issue"
                />
              ) : (
                <TextFormField
                  name="keyword"
                  label="全部关键词，顺序不限，用空格分隔"
                  tooltip="问题匹配这些关键词后才会触发此答案。"
                  placeholder="it ticket"
                />
              )}
              <BooleanFormField
                subtext="使用 Regex 模式匹配，而不是精确关键词"
                optional
                label="匹配 Regex"
                name="matchRegex"
              />
              {values.matchRegex ? null : (
                <SelectorFormField
                  defaultValue={`all`}
                  label="关键词检测策略"
                  subtext="选择用户问题需要包含上方任意关键词还是全部关键词，才显示此答案。"
                  name="matchAnyKeywords"
                  options={[
                    {
                      name: "全部关键词",
                      value: "all",
                    },
                    {
                      name: "任意关键词",
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
                  label="答案"
                  placeholder="使用 Markdown 编写答案。例如：如果需要 IT 团队帮助，请发送邮件到 internalsupport@company.com"
                />
              </div>
              <div className="w-4/12">
                <MultiSelectDropdown
                  name="categories"
                  label="分类："
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
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="mx-auto w-64"
                >
                  {isUpdate ? "更新" : "创建"}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardSection>
    </div>
  );
};
