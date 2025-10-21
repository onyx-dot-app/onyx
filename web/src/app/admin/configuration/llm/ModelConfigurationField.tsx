"use client";

import { ArrayHelpers, FieldArray, FormikProps, useField } from "formik";
import { ModelConfiguration } from "./interfaces";
import {
  ManualErrorMessage,
  SubLabel,
  TextFormField,
} from "@/components/Field";
import { FiPlus, FiX } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useEffect, useState } from "react";

function ModelConfigurationRow({
  name,
  index,
  arrayHelpers,
  formikProps,
  setError,
}: {
  name: string;
  index: number;
  arrayHelpers: ArrayHelpers;
  formikProps: FormikProps<{ model_configurations: ModelConfiguration[] }>;
  setError: (value: string | null) => void;
}) {
  const [, input] = useField(`${name}[${index}]`);
  useEffect(() => {
    if (!input.touched) return;
    setError((input.error as { name: string } | undefined)?.name ?? null);
  }, [input.touched, input.error]);

  return (
    <div key={index} className="flex flex-row w-full gap-4">
      <div
        className={`flex flex-[2] ${
          input.touched && input.error ? "border-2 border-error rounded-lg" : ""
        }`}
      >
        <TextFormField
          name={`${name}[${index}].name`}
          label=""
          placeholder={`model-name-${index + 1}`}
          removeLabel
          hideError
        />
      </div>
      <div className="flex flex-[1]">
        <TextFormField
          name={`${name}[${index}].max_input_tokens`}
          label=""
          placeholder="Default"
          removeLabel
          hideError
          type="number"
          min={1}
        />
      </div>
      <div className="flex items-end">
        <div
          className={`${
            formikProps.values.model_configurations.length >= 2
              ? ""
              : "opacity-20"
          }`}
        >
          <FiX
            className="w-10 h-10 cursor-pointer hover:bg-accent-background-hovered rounded p-2"
            onClick={() => {
              if (formikProps.values.model_configurations.length > 1) {
                setError(null);
                arrayHelpers.remove(index);
              }
            }}
          />
        </div>
      </div>
    </div>
  );
}

export function ModelConfigurationField({
  name,
  formikProps,
}: {
  name: string;
  formikProps: FormikProps<{ model_configurations: ModelConfiguration[] }>;
}) {
  const [errorMap, setErrorMap] = useState<{ [index: number]: string }>({});
  const [finalError, setFinalError] = useState<string | undefined>();

  return (
    <div className="pb-5 flex flex-col w-full">
      <div className="flex flex-col">
        <Label className="text-md">Model Configurations</Label>
        <SubLabel>
          Add models and customize the number of input tokens that they accept.
        </SubLabel>
      </div>
      <FieldArray
        name={name}
        render={(arrayHelpers: ArrayHelpers) => (
          <div className="flex flex-col">
            <div className="flex flex-col gap-4 py-4">
              <div className="flex">
                <Label className="flex flex-[2]">Model Name</Label>
                <Label className="flex flex-[1]">Max Input Tokens</Label>
                <div className="w-10" />
              </div>
              {formikProps.values.model_configurations.map((_, index) => (
                <ModelConfigurationRow
                  key={index}
                  name={name}
                  formikProps={formikProps}
                  arrayHelpers={arrayHelpers}
                  index={index}
                  setError={(message: string | null) => {
                    const newErrors = { ...errorMap };
                    if (message) {
                      newErrors[index] = message;
                    } else {
                      delete newErrors[index];
                      for (const key in newErrors) {
                        const numKey = Number(key);
                        if (numKey > index) {
                          const errorValue = newErrors[key];
                          if (errorValue !== undefined) {
                            // Ensure the value is not undefined
                            newErrors[numKey - 1] = errorValue;
                            delete newErrors[numKey];
                          }
                        }
                      }
                    }
                    setErrorMap(newErrors);
                    setFinalError(
                      Object.values(newErrors).filter((item) => item)[0]
                    );
                  }}
                />
              ))}
            </div>
            {finalError && (
              <ManualErrorMessage>{finalError}</ManualErrorMessage>
            )}
            <div>
              <Button
                onClick={() => {
                  arrayHelpers.push({
                    name: "",
                    is_visible: true,
                    // Use null so Yup.number().nullable() accepts empty inputs
                    max_input_tokens: null,
                  });
                }}
                className="mt-3"
                variant="next"
                type="button"
                icon={FiPlus}
              >
                Add New
              </Button>
            </div>
          </div>
        )}
      />
    </div>
  );
}
