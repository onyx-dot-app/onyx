"use client";

import { useEffect } from "react";
import { useFormikContext } from "formik";
import {
  isEmptyField,
  type BindingGate,
  type BoundFieldState,
} from "@/lib/connectors/bindingGate";
import {
  useBoundFieldsGate,
  type UseBoundFieldsGateResult,
} from "@/lib/connectors/hooks";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { Credential } from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";

type ConnectorField = ConnectionConfiguration["values"][number];

export interface BoundFieldsGateProps<FormValues> {
  source: ValidSources;
  credentialId: number | null;
  credentialSelected: boolean;
  currentCredential: Credential<unknown> | null;
  /** Every credential-bound field of the source. */
  allBoundFields: ConnectorField[];
  /** The bound fields the form shows now. */
  visibleBoundFields: ConnectorField[];
  /** One more condition for the form values, applied after the binding passes. */
  extraFor?: (values: FormValues) => BindingGate | undefined;
  onChange: (gate: UseBoundFieldsGateResult) => void;
}

function labelOf(
  field: ConnectorField,
  credential: Credential<unknown> | null
): string {
  return typeof field.label === "function"
    ? field.label(credential)
    : field.label;
}

/**
 * Runs `useBoundFieldsGate` inside the Formik context and reports the gate to
 * the create page, which locks the configuration with it. Renders nothing.
 */
export function BoundFieldsGate<FormValues extends Record<string, unknown>>({
  source,
  credentialId,
  credentialSelected,
  currentCredential,
  allBoundFields,
  visibleBoundFields,
  extraFor,
  onChange,
}: BoundFieldsGateProps<FormValues>) {
  const { values, errors } = useFormikContext<FormValues>();
  const fieldErrors: Record<string, unknown> = errors;
  const boundFields: BoundFieldState[] = visibleBoundFields.map((field) => {
    const missing = !field.optional && isEmptyField(values, field.name);
    return {
      name: field.name,
      label: labelOf(field, currentCredential),
      missing,
      invalid: !missing && Boolean(fieldErrors[field.name]),
    };
  });
  const gate = useBoundFieldsGate({
    source,
    credentialId,
    credentialUpdatedAt: currentCredential?.time_updated ?? null,
    credentialSelected,
    boundFieldNames: allBoundFields.map((field) => field.name),
    boundFields,
    values,
    extra: extraFor?.(values),
  });

  const reported = JSON.stringify({
    status: gate.status,
    reason: gate.reason,
    fieldErrors: gate.fieldErrors,
  });
  // `reported` and `requestCheck` hold everything the page reads, so an equal
  // gate is not reported again.
  useEffect(() => {
    onChange(gate);
  }, [reported, onChange, gate.requestCheck]);

  return null;
}
