/**
 * Add OpenAPI Action Modal
 *
 * Pure UI implementation based on the Figma spec referenced in the task.
 */
"use client";

import Link from "next/link";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Text from "@/refresh-components/texts/Text";
import SvgLinkedDots from "@/icons/linked-dots";
import { FormField } from "@/refresh-components/form/FormField";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Separator from "@/refresh-components/Separator";
import { useCallback, useEffect, useMemo, useState } from "react";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgBracketCurly from "@/icons/bracket-curly";
import { MethodSpec } from "@/lib/tools/types";
import { validateToolDefinition } from "@/lib/tools/openApiService";
import debounce from "lodash/debounce";

interface AddOpenAPIActionModalProps {
  isOpen: boolean;
  onClose: () => void;
  skipOverlay?: boolean;
}

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

interface SchemaActionsProps {
  definition: string;
  onFormat: () => void;
}

function SchemaActions({ definition, onFormat }: SchemaActionsProps) {
  return (
    <div className="flex flex-row gap-2">
      <CopyIconButton
        getCopyText={() => definition}
        tooltip="Copy definition"
      />
      <IconButton
        icon={SvgBracketCurly}
        tooltip="Format definition"
        onClick={onFormat}
      />
    </div>
  );
}
export default function AddOpenAPIActionModal({
  isOpen,
  onClose,
  skipOverlay = false,
}: AddOpenAPIActionModalProps) {
  const [definition, setDefinition] = useState("");
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [methodSpecs, setMethodSpecs] = useState<MethodSpec[] | null>(null);

  const handleFormat = useCallback(() => {
    if (!definition.trim()) {
      return;
    }

    try {
      const formatted = prettifyDefinition(
        parseJsonWithTrailingCommas(definition)
      );
      setDefinition(formatted);
      setDefinitionError(null);
    } catch {
      setDefinitionError("Invalid JSON format");
    }
  }, [definition]);

  const validateDefinition = useCallback(async (rawDefinition: string) => {
    if (!rawDefinition.trim()) {
      setMethodSpecs(null);
      setDefinitionError(null);
      return;
    }

    try {
      const parsedDefinition = parseJsonWithTrailingCommas(rawDefinition);
      const response = await validateToolDefinition({
        definition: parsedDefinition,
      });

      if (response.error) {
        setMethodSpecs(null);
        setDefinitionError(response.error);
      } else {
        setMethodSpecs(response.data ?? []);
        setDefinitionError(null);
      }
    } catch {
      setMethodSpecs(null);
      setDefinitionError("Invalid JSON format");
    }
  }, []);

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

  useEffect(() => {
    if (!definition.trim()) {
      setMethodSpecs(null);
      setDefinitionError(null);
      debouncedValidateDefinition.cancel();
      return () => {
        debouncedValidateDefinition.cancel();
      };
    }

    debouncedValidateDefinition(definition);
    return () => {
      debouncedValidateDefinition.cancel();
    };
  }, [definition, debouncedValidateDefinition]);

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <Modal.Content mini skipOverlay={skipOverlay}>
        <Modal.Header
          icon={SvgLinkedDots}
          title="Add OpenAPI action"
          description="Add OpenAPI schema to add custom actions."
          onClose={onClose}
          className="p-4"
        />

        <Modal.Body className="bg-background-tint-01 p-4 flex flex-col gap-4 overflow-y-auto">
          <FormField
            id="openapi-schema"
            name="definition"
            className="gap-2"
            state={definitionError ? "error" : "idle"}
          >
            <FormField.Label className="tracking-tight">
              OpenAPI Schema Definition
            </FormField.Label>
            <FormField.Control asChild>
              <InputTextArea
                value={definition}
                onChange={(e) => setDefinition(e.target.value)}
                rows={8}
                placeholder="Enter your OpenAPI schema here"
                className="text-text-04 font-main-ui-mono"
                action={
                  <SchemaActions
                    definition={definition}
                    onFormat={handleFormat}
                  />
                }
              />
            </FormField.Control>
            <FormField.Description>
              Specify an OpenAPI schema that defines the APIs you want to make
              available as part of this action. Learn more about{" "}
              <SimpleTooltip
                tooltip="Open https://docs.onyx.app/admins/actions/openapi"
                side="top"
              >
                <Link
                  href="https://docs.onyx.app/admins/actions/openapi"
                  target="_blank"
                  rel="noreferrer"
                  className="text-action-text-link-05 underline underline-offset-2"
                >
                  OpenAPI actions
                </Link>
              </SimpleTooltip>
              .
            </FormField.Description>
            <FormField.Message messages={{ error: definitionError }} />
          </FormField>

          <Separator />

          <section className="border border-border-01 border-dashed rounded-08 p-4 flex flex-col gap-3">
            {methodSpecs && methodSpecs.length > 0 ? (
              <div className="flex flex-col gap-3">
                {methodSpecs.map((method) => (
                  <div
                    key={`${method.method}-${method.path}-${method.name}`}
                    className="rounded-08 border border-border-01 bg-background-tint-00 p-3 flex flex-col gap-1"
                  >
                    <div className="flex items-center justify-between">
                      <Text mainUiAction text03 className="font-semibold">
                        {method.name}
                      </Text>
                      <Text className="font-main-ui-mono uppercase text-text-03">
                        {method.method}
                      </Text>
                    </div>
                    {method.summary && (
                      <Text secondaryBody text03>
                        {method.summary}
                      </Text>
                    )}
                    <Text className="font-main-ui-mono text-text-04">
                      {method.path}
                    </Text>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-row gap-3 items-start">
                <div className="rounded-08 border border-border-01 bg-background-tint-01 p-1.5 flex items-center justify-center">
                  <SvgLinkedDots className="size-4 stroke-text-03" />
                </div>
                <div className="flex flex-col gap-1">
                  <Text mainUiAction text03>
                    No actions found
                  </Text>
                  <Text secondaryBody text03>
                    Provide OpenAPI schema to preview actions here.
                  </Text>
                </div>
              </div>
            )}
          </section>
        </Modal.Body>

        <Modal.Footer className="p-4 gap-2 bg-background-tint-00">
          <Button main secondary type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button main primary type="button">
            Add Server
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
