"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Formik,
  Form,
  Field,
  ErrorMessage,
  FieldArray,
  ArrayHelpers,
} from "formik";
import * as Yup from "yup";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/interfaces";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Button } from "@/components/ui/button";
import {
  createCustomTool,
  updateCustomTool,
  validateToolDefinition,
} from "@/lib/tools/edit";
import { usePopup } from "@/components/admin/connectors/Popup";
import debounce from "lodash/debounce";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import Link from "next/link";
import { Separator } from "@/components/ui/separator";

function parseJsonWithTrailingCommas(jsonString: string) {
  // Regular expression to remove trailing commas before } or ]
  let cleanedJsonString = jsonString.replace(/,\s*([}\]])/g, "$1");
  // Replace True with true, False with false, and None with null
  cleanedJsonString = cleanedJsonString
    .replace(/\bTrue\b/g, "true")
    .replace(/\bFalse\b/g, "false")
    .replace(/\bNone\b/g, "null");
  // Now parse the cleaned JSON string
  return JSON.parse(cleanedJsonString);
}

function prettifyDefinition(definition: any) {
  return JSON.stringify(definition, null, 2);
}

function ToolForm({
  existingTool,
  values,
  setFieldValue,
  isSubmitting,
  definitionErrorState,
  methodSpecsState,
}: {
  existingTool?: ToolSnapshot;
  values: ToolFormValues;
  setFieldValue: (field: string, value: string) => void;
  isSubmitting: boolean;
  definitionErrorState: [
    string | null,
    React.Dispatch<React.SetStateAction<string | null>>,
  ];
  methodSpecsState: [
    MethodSpec[] | null,
    React.Dispatch<React.SetStateAction<MethodSpec[] | null>>,
  ];
}) {
  const [definitionError, setDefinitionError] = definitionErrorState;
  const [methodSpecs, setMethodSpecs] = methodSpecsState;
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const debouncedValidateDefinition = useCallback(
    (definition: string) => {
      const validateDefinition = async () => {
        try {
          const parsedDefinition = parseJsonWithTrailingCommas(definition);
          const response = await validateToolDefinition({
            definition: parsedDefinition,
          });
          if (response.error) {
            setMethodSpecs(null);
            setDefinitionError(response.error);
          } else {
            setMethodSpecs(response.data);
            setDefinitionError(null);
          }
        } catch (error) {
          console.log(error);
          setMethodSpecs(null);
          setDefinitionError("Invalid JSON format");
        }
      };

      debounce(validateDefinition, 300)();
    },
    [setMethodSpecs, setDefinitionError]
  );

  useEffect(() => {
    if (values.definition) {
      debouncedValidateDefinition(values.definition);
    }
  }, [values.definition, debouncedValidateDefinition]);

  return (
    <Form className="max-w-4xl">
      <div className="relative w-full">
        <TextFormField
          name="definition"
          label="Definition"
          subtext="Specify an OpenAPI schema that defines the APIs you want to make available as part of this tool."
          placeholder="Enter your OpenAPI schema here"
          isTextArea={true}
          defaultHeight="h-96"
          fontSize="sm"
          isCode
          hideError
        />
        <button
          type="button"
          className="
            absolute 
            bottom-4 
            right-4
            border-border
            border
            bg-background
            rounded
            py-1 
            px-3 
            text-sm
            hover:bg-hover-light
          "
          onClick={() => {
            const definition = values.definition;
            if (definition) {
              try {
                const formatted = prettifyDefinition(
                  parseJsonWithTrailingCommas(definition)
                );
                setFieldValue("definition", formatted);
              } catch (error) {
                alert("Invalid JSON format");
              }
            }
          }}
        >
          Format
        </button>
      </div>
      {definitionError && (
        <div className="text-error text-sm">{definitionError}</div>
      )}
      <ErrorMessage
        name="definition"
        component="div"
        className="mb-4 text-error text-sm"
      />
      <div className="mt-4 text-sm bg-blue-50 p-4 rounded-md border border-blue-200">
        <Link
          href="https://docs.danswer.dev/tools/custom"
          className="text-link hover:underline flex items-center"
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5 mr-2"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
              clipRule="evenodd"
            />
          </svg>
          Learn more about tool calling in our documentation
        </Link>
      </div>

      {methodSpecs && methodSpecs.length > 0 && (
        <div className="my-4">
          <h3 className="text-base font-semibold mb-2">Available methods</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full bg-white border border-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-2 border-b">Name</th>
                  <th className="px-4 py-2 border-b">Summary</th>
                  <th className="px-4 py-2 border-b">Method</th>
                  <th className="px-4 py-2 border-b">Path</th>
                </tr>
              </thead>
              <tbody>
                {methodSpecs?.map((method: MethodSpec, index: number) => (
                  <tr key={index} className="text-sm">
                    <td className="px-4 py-2 border-b">{method.name}</td>
                    <td className="px-4 py-2 border-b">{method.summary}</td>
                    <td className="px-4 py-2 border-b">
                      {method.method.toUpperCase()}
                    </td>
                    <td className="px-4 py-2 border-b">{method.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <AdvancedOptionsToggle
        showAdvancedOptions={showAdvancedOptions}
        setShowAdvancedOptions={setShowAdvancedOptions}
      />
      {showAdvancedOptions && (
        <div>
          <h3 className="text-xl font-bold mb-2 text-primary-600">
            Custom Headers
          </h3>
          <p className="text-sm mb-6 text-gray-600 italic">
            Specify custom headers for each request to this tool&apos;s API.
          </p>
          <FieldArray
            name="customHeaders"
            render={(arrayHelpers: ArrayHelpers) => (
              <div className="space-y-4">
                {values.customHeaders && values.customHeaders.length > 0 && (
                  <div className="space-y-3">
                    {values.customHeaders.map(
                      (
                        header: { key: string; value: string },
                        index: number
                      ) => (
                        <div
                          key={index}
                          className="flex items-center space-x-2 bg-gray-50 p-3 rounded-lg shadow-sm"
                        >
                          <Field
                            name={`customHeaders.${index}.key`}
                            placeholder="Header Key"
                            className="flex-1 p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          />
                          <Field
                            name={`customHeaders.${index}.value`}
                            placeholder="Header Value"
                            className="flex-1 p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          />
                          <Button
                            type="button"
                            onClick={() => arrayHelpers.remove(index)}
                            variant="destructive"
                            size="sm"
                            className="transition-colors duration-200 hover:bg-red-600"
                          >
                            Remove
                          </Button>
                        </div>
                      )
                    )}
                  </div>
                )}

                <Button
                  type="button"
                  onClick={() => arrayHelpers.push({ key: "", value: "" })}
                  variant="secondary"
                  size="sm"
                  className="transition-colors duration-200"
                >
                  Add New Header
                </Button>
              </div>
            )}
          />
        </div>
      )}

      <Separator />

      <div className="flex">
        <Button
          className="mx-auto"
          variant="submit"
          size="sm"
          type="submit"
          disabled={isSubmitting || !!definitionError}
        >
          {existingTool ? "Update Tool" : "Create Tool"}
        </Button>
      </div>
    </Form>
  );
}

interface ToolFormValues {
  definition: string;
  customHeaders: { key: string; value: string }[];
}

const ToolSchema = Yup.object().shape({
  definition: Yup.string().required("Tool definition is required"),
  customHeaders: Yup.array()
    .of(
      Yup.object().shape({
        key: Yup.string().required("Header key is required"),
        value: Yup.string().required("Header value is required"),
      })
    )
    .default([]),
});

export function ToolEditor({ tool }: { tool?: ToolSnapshot }) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [methodSpecs, setMethodSpecs] = useState<MethodSpec[] | null>(null);

  const prettifiedDefinition = tool?.definition
    ? prettifyDefinition(tool.definition)
    : "";

  return (
    <div>
      {popup}
      <Formik
        initialValues={{
          definition: prettifiedDefinition,
          customHeaders:
            tool?.custom_headers?.map((header) => ({
              key: header.key,
              value: header.value,
            })) ?? [],
        }}
        validationSchema={ToolSchema}
        onSubmit={async (values: ToolFormValues) => {
          let definition: any;
          try {
            definition = parseJsonWithTrailingCommas(values.definition);
          } catch (error) {
            setDefinitionError("Invalid JSON in tool definition");
            return;
          }

          const name = definition?.info?.title;
          const description = definition?.info?.description;
          const toolData = {
            name: name,
            description: description || "",
            definition: definition,
            custom_headers: values.customHeaders,
          };
          let response;
          if (tool) {
            response = await updateCustomTool(tool.id, toolData);
          } else {
            response = await createCustomTool(toolData);
          }
          if (response.error) {
            setPopup({
              message: "Failed to create tool - " + response.error,
              type: "error",
            });
            return;
          }
          router.push(`/admin/tools?u=${Date.now()}`);
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => {
          return (
            <ToolForm
              existingTool={tool}
              values={values}
              setFieldValue={setFieldValue}
              isSubmitting={isSubmitting}
              definitionErrorState={[definitionError, setDefinitionError]}
              methodSpecsState={[methodSpecs, setMethodSpecs]}
            />
          );
        }}
      </Formik>
    </div>
  );
}
