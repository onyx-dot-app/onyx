"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Formik, Form, Field, ErrorMessage } from "formik";
import * as Yup from "yup";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/interfaces";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Button, Divider } from "@tremor/react";
import {
  createCustomTool,
  updateCustomTool,
  validateToolDefinition,
} from "@/lib/tools/edit";
import { usePopup } from "@/components/admin/connectors/Popup";
import debounce from "lodash/debounce";

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

  const debouncedValidateDefinition = useCallback(
    debounce(async (definition: string) => {
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
    }, 300),
    []
  );

  useEffect(() => {
    if (values.definition) {
      debouncedValidateDefinition(values.definition);
    }
  }, [values.definition, debouncedValidateDefinition]);

  return (
    <Form>
      <div className="relative">
        <TextFormField
          name="definition"
          label="Definition"
          subtext="Specify an OpenAPI schema that defines the APIs you want to make available as part of this tool."
          placeholder="Enter your OpenAPI schema here"
          isTextArea={true}
          defaultHeight="h-96"
          fontSize="text-sm"
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
        className="text-error text-sm"
      />

      {methodSpecs && methodSpecs.length > 0 && (
        <div className="mt-4">
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

      <Divider />
      <div className="flex">
        <Button
          className="mx-auto"
          color="green"
          size="md"
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
}

const ToolSchema = Yup.object().shape({
  definition: Yup.string().required("Tool definition is required"),
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
