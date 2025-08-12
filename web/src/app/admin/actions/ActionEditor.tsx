"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Formik, Form, Field, ErrorMessage, FieldArray } from "formik";
import * as Yup from "yup";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/interfaces";
import { TextFormField } from "@/components/Field";
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuthType } from "@/lib/hooks";
import { InfoIcon } from "lucide-react";

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

function ActionForm({
  existingTool,
  values,
  setFieldValue,
  isSubmitting,
  definitionErrorState,
  methodSpecsState,
}: {
  existingTool?: ToolSnapshot;
  values: ToolFormValues;
  setFieldValue: <T = any>(
    field: string,
    value: T,
    shouldValidate?: boolean
  ) => void;
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
  const authType = useAuthType();
  const isOAuthEnabled = authType === "oidc" || authType === "google_oauth";

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
        } catch {
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
          subtext="Specify an OpenAPI schema that defines the APIs you want to make available as part of this action."
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
            hover:bg-accent-background
          "
          onClick={() => {
            const definition = values.definition;
            if (definition) {
              try {
                const formatted = prettifyDefinition(
                  parseJsonWithTrailingCommas(definition)
                );
                setFieldValue("definition", formatted);
              } catch {
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
      <div className="mt-4 text-sm bg-blue-50 text-blue-700 dark:text-blue-300 dark:bg-blue-900 p-4 rounded-md border border-blue-200 dark:border-blue-800">
        <Link
          href="https://docs.onyx.app/actions/custom#custom-actions"
          className="text-link hover:underline flex items-center"
          target="_blank"
          rel="noopener noreferrer"
        >
          <InfoIcon className="w-4 h-4 mr-2 " />
          Learn more about actions in our documentation
        </Link>
      </div>

      {methodSpecs && methodSpecs.length > 0 && (
        <div className="my-4">
          <h3 className="text-base font-semibold mb-2">Available methods</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full bg-white border border-background-200">
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
          <p className="text-sm mb-6 text-text-600 italic">
            Specify custom headers for each request to this action&apos;s API.
          </p>
          <FieldArray
            name="customHeaders"
            render={(arrayHelpers) => (
              <div>
                <div className="space-y-2">
                  {values.customHeaders.map(
                    (header: { key: string; value: string }, index: number) => (
                      <div
                        key={index}
                        className="flex items-center space-x-2 bg-background-50 p-3 rounded-lg shadow-sm"
                      >
                        <Field
                          name={`customHeaders.${index}.key`}
                          placeholder="Header Key"
                          className="flex-1 p-2 border border-background-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        />
                        <Field
                          name={`customHeaders.${index}.value`}
                          placeholder="Header Value"
                          className="flex-1 p-2 border border-background-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent"
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

          <div className="mt-6">
            <h3 className="text-xl font-bold mb-2 text-primary-600">
              Authentication
            </h3>
            {isOAuthEnabled ? (
              <div className="flex flex-col gap-y-2">
                <div className="flex items-center space-x-2">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger>
                        <div
                          className={
                            values.customHeaders.some(
                              (header) =>
                                header.key.toLowerCase() === "authorization"
                            )
                              ? "opacity-50"
                              : ""
                          }
                        >
                          <Checkbox
                            id="passthrough_auth"
                            size="sm"
                            checked={values.passthrough_auth}
                            disabled={values.customHeaders.some(
                              (header) =>
                                header.key.toLowerCase() === "authorization" &&
                                !values.passthrough_auth
                            )}
                            onCheckedChange={(checked) => {
                              setFieldValue("passthrough_auth", checked, true);
                            }}
                          />
                        </div>
                      </TooltipTrigger>
                      {values.customHeaders.some(
                        (header) => header.key.toLowerCase() === "authorization"
                      ) && (
                        <TooltipContent side="top" align="center">
                          <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                            Cannot enable OAuth passthrough when an
                            Authorization header is already set
                          </p>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </TooltipProvider>
                  <div className="flex flex-col">
                    <label
                      htmlFor="passthrough_auth"
                      className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                    >
                      Pass through user&apos;s OAuth token
                    </label>
                    <p className="text-xs text-subtle mt-1">
                      When enabled, the user&apos;s OAuth token will be passed
                      as the Authorization header for all API calls
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-subtle">
                OAuth passthrough is only available when OIDC or OAuth
                authentication is enabled
              </p>
            )}
          </div>
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
          {existingTool ? "Update Action" : "Create Action"}
        </Button>
      </div>
    </Form>
  );
}

interface ToolFormValues {
  definition: string;
  customHeaders: { key: string; value: string }[];
  passthrough_auth: boolean;
}

const ToolSchema = Yup.object().shape({
  definition: Yup.string().required("Action definition is required"),
  customHeaders: Yup.array()
    .of(
      Yup.object().shape({
        key: Yup.string().required("Header key is required"),
        value: Yup.string().required("Header value is required"),
      })
    )
    .default([]),
  passthrough_auth: Yup.boolean().default(false),
});

export function ActionEditor({ tool }: { tool?: ToolSnapshot }) {
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
          passthrough_auth: tool?.passthrough_auth ?? false,
        }}
        validationSchema={ToolSchema}
        onSubmit={async (values: ToolFormValues) => {
          const hasAuthHeader = values.customHeaders?.some(
            (header) => header.key.toLowerCase() === "authorization"
          );
          if (hasAuthHeader && values.passthrough_auth) {
            setPopup({
              message:
                "Cannot enable passthrough auth when Authorization " +
                "headers are present. Please remove any Authorization " +
                "headers first.",
              type: "error",
            });
            console.log(
              "Cannot enable passthrough auth when Authorization headers are present. Please remove any Authorization headers first."
            );
            return;
          }

          let definition: any;
          try {
            definition = parseJsonWithTrailingCommas(values.definition);
          } catch {
            setDefinitionError("Invalid JSON in action definition");
            return;
          }

          const name = definition?.info?.title;
          const description = definition?.info?.description;
          const toolData = {
            name: name,
            description: description || "",
            definition: definition,
            custom_headers: values.customHeaders,
            passthrough_auth: values.passthrough_auth,
          };
          let response;
          if (tool) {
            response = await updateCustomTool(tool.id, toolData);
          } else {
            response = await createCustomTool(toolData);
          }
          if (response.error) {
            setPopup({
              message: "Failed to create action - " + response.error,
              type: "error",
            });
            return;
          }
          router.push(`/admin/actions?u=${Date.now()}`);
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => {
          return (
            <ActionForm
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
