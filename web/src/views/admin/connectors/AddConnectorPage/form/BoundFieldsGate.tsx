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
import type {
  Credential,
  CredentialRef,
  CredentialValues,
  DraftCredential,
} from "@/lib/credentials/types";
import { isDraftCredential } from "@/lib/credentials/utils";
import type { ValidSources } from "@/lib/connectors/types/source";

type ConnectorField = ConnectionConfiguration["values"][number];

export interface BoundFieldsGateProps<FormValues> {
  source: ValidSources;
  /** The saved credential or draft the binding is checked against. */
  credential: CredentialRef | null;
  credentialSelected: boolean;
  currentCredential: Credential<unknown> | DraftCredential | null;
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
  credential: CredentialValues | null
): string {
  return typeof field.label === "function"
    ? field.label(credential)
    : (field.label ?? field.name);
}

/**
 * Runs `useBoundFieldsGate` inside the Formik context and reports the gate to
 * the create page, which locks the configuration with it. Renders nothing.
 */
export function BoundFieldsGate<FormValues extends Record<string, unknown>>({
  source,
  credential,
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
    credential,
    // New values are a new credential reference, so a draft needs no time.
    credentialUpdatedAt:
      currentCredential === null || isDraftCredential(currentCredential)
        ? null
        : currentCredential.time_updated,
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
