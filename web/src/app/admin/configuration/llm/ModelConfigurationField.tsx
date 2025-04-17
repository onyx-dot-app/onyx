"use client";

import { ArrayHelpers, FieldArray, FormikProps } from "formik";
import { ModelConfiguration } from "./interfaces";
import { SubLabel, TextFormField } from "@/components/admin/connectors/Field";
import { FiPlus, FiX } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export function ModelConfigurationField({
  name,
  formikProps,
}: {
  name: string;
  formikProps: FormikProps<{ model_configurations: ModelConfiguration[] }>;
}) {
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
            <div className="flex flex-col gap-4 p-4">
              {formikProps.values.model_configurations.map((_, index) => (
                <div key={index} className="flex flex-row w-full gap-4">
                  <div className="flex flex-1">
                    <TextFormField
                      name={`${name}[${index}].name`}
                      label="Model Name"
                      placeholder={`model-name-${index + 1}`}
                    />
                  </div>
                  <div className="flex flex-2">
                    <TextFormField
                      name={`${name}[${index}].max_input_tokens`}
                      label="Max Input Tokens"
                      type="number"
                      min={0}
                      placeholder="No Limit"
                    />
                  </div>
                  <div className="flex items-end">
                    <FiX
                      className="w-10 h-10 cursor-pointer hover:bg-accent-background-hovered rounded p-2"
                      onClick={() => arrayHelpers.remove(index)}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div>
              <Button
                onClick={() => {
                  arrayHelpers.push({ name: "", is_visible: true });
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
