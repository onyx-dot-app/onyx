"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import { Button, Card } from "@tremor/react";
import { Form, Formik } from "formik";
import { useRouter } from "next/navigation";
import * as Yup from "yup";
import {
  createStandardAnswer,
  createStandardAnswerCategory,
  updateStandardAnswer,
} from "./lib";
import {
  TextFormField,
  MarkdownFormField,
} from "@/components/admin/connectors/Field";
import MultiSelectDropdown from "@/components/MultiSelectDropdown";

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
      <Card>
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
          }}
          validationSchema={Yup.object().shape({
            keyword: Yup.string()
              .required("Keyword or phrase is required")
              .max(255)
              .min(1),
            answer: Yup.string().required("Answer is required").min(1),
            categories: Yup.array()
              .required()
              .min(1, "At least one category is required"),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const cleanedValues = {
              ...values,
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
              <TextFormField
                name="keyword"
                label="Keywords"
                tooltip="If all specified keywords are in the question, then we will respond with the answer below"
                placeholder="e.g. Wifi Password"
                autoCompleteDisabled={true}
              />
              <MarkdownFormField
                name="answer"
                label="Answer"
                placeholder="The answer in markdown"
              />
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
              <div className="p-4 flex">
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
      </Card>
    </div>
  );
};
