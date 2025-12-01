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
import SvgActions from "@/icons/actions";
import { FormField } from "@/refresh-components/form/FormField";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Separator from "@/refresh-components/Separator";
import { useCallback, useEffect, useMemo, useState } from "react";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgBracketCurly from "@/icons/bracket-curly";
import { MethodSpec } from "@/lib/tools/types";
import { validateToolDefinition } from "@/lib/tools/openApiService";
import ToolItem from "@/sections/actions/ToolItem";
import debounce from "lodash/debounce";
import { useModal } from "@/refresh-components/contexts/ModalContext";
interface AddOpenAPIActionModalProps {
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
    <div className="flex flex-col">
      <CopyIconButton
        tertiary
        getCopyText={() => definition}
        tooltip="Copy definition"
      />
      <IconButton
        tertiary
        icon={SvgBracketCurly}
        tooltip="Format definition"
        onClick={onFormat}
      />
    </div>
  );
}
export default function AddOpenAPIActionModal({
  skipOverlay = false,
}: AddOpenAPIActionModalProps) {
  const { isOpen, toggle } = useModal();
  const handleClose = useCallback(() => {
    toggle(false);
  }, [toggle]);
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
          handleClose();
        }
      }}
    >
      <Modal.Content tall skipOverlay={skipOverlay}>
        <Modal.Header
          icon={SvgActions}
          title="Add OpenAPI action"
          description="Add OpenAPI schema to add custom actions."
          onClose={handleClose}
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
                rows={14}
                placeholder="Enter your OpenAPI schema here"
                className="text-text-04 font-main-ui-mono"
                action={
                  definition.trim() ? (
                    <SchemaActions
                      definition={definition}
                      onFormat={handleFormat}
                    />
                  ) : null
                }
              />
            </FormField.Control>
            <FormField.Description>
              Specify an OpenAPI schema that defines the APIs you want to make
              available as part of this action. Learn more about{" "}
              <span className="inline-flex">
                <SimpleTooltip
                  tooltip="Open https://docs.onyx.app/admins/actions/openapi"
                  side="top"
                >
                  <Link
                    href="https://docs.onyx.app/admins/actions/openapi"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    OpenAPI actions
                  </Link>
                </SimpleTooltip>
              </span>
              .
            </FormField.Description>
            <FormField.Message messages={{ error: definitionError }} />
          </FormField>

          <Separator className="my-0 py-0" />
          {methodSpecs && methodSpecs.length > 0 ? (
            <div className="flex flex-col gap-2">
              {methodSpecs.map((method) => (
                <ToolItem
                  key={`${method.method}-${method.path}-${method.name}`}
                  name={method.name}
                  description={method.summary || "No summary provided"}
                  variant="openapi"
                  openApiMetadata={{
                    method: method.method,
                    path: method.path,
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="flex flex-row gap-3 items-start p-1.5 rounded-08 border border-border-01 border-dashed">
              <div className="rounded-08 bg-background-tint-01 p-1 flex items-center justify-center">
                <SvgActions className="size-4 stroke-text-03" />
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
        </Modal.Body>

        <Modal.Footer className="p-4 gap-2 bg-background-tint-00">
          <Button main secondary type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button main primary type="button">
            Add Action
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
