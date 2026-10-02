"use client";

import { useEffect, useMemo, useRef, type RefObject } from "react";
import { useFormikContext } from "formik";
import { ConnectorsCheckCard } from "@/lib/connectors/checks/ConnectorsCheckCard";
import type {
  DraftCheckRunInput,
  UseDraftConnectorChecksResult,
} from "@/lib/connectors/checks/hooks";
import type {
  ConnectionConfiguration,
  ConnectorValueField,
  TabOption,
} from "@/lib/connectors/types";
import type { Credential } from "@/lib/credentials/types";

/** Wait this long after the last trigger before starting a run. */
const RUN_DEBOUNCE_MS = 400;

export interface DraftConnectorChecksProps<FormValues> {
  checks: UseDraftConnectorChecksResult;
  /** The draft-run input for the form values, as the create request sends them. */
  inputFor: (values: FormValues) => DraftCheckRunInput;
  configuration: ConnectionConfiguration;
  currentCredential: Credential<unknown> | null;
  /**
   * The containers of the connector-config fields (the credential-bound
   * fields above the credential and the config below it). Leaving any field
   * in them starts a run.
   */
  fieldContainerRefs: RefObject<HTMLElement | null>[];
  /** A change of this key starts a run, e.g. the credential-bound values. */
  runOnChangeKey?: string;
  highlighted?: boolean;
}

function fieldLabelsOf(
  fields: (ConnectorValueField | TabOption)[],
  credential: Credential<unknown> | null
): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const field of fields) {
    labels[field.name] =
      typeof field.label === "function" ? field.label(credential) : field.label;
    if (field.type === "tab") {
      for (const tab of field.tabs) {
        Object.assign(labels, fieldLabelsOf(tab.fields, credential));
      }
    }
  }
  return labels;
}

/**
 * The checks card of the create form. It runs the capability checks when a
 * credential is selected, when the access type changes, and when the admin
 * leaves a connector-config field. Its re-run button runs them again for the
 * current input.
 */
export function DraftConnectorChecks<FormValues>({
  checks,
  inputFor,
  configuration,
  currentCredential,
  fieldContainerRefs,
  runOnChangeKey,
  highlighted,
}: DraftConnectorChecksProps<FormValues>) {
  const { values } = useFormikContext<FormValues>();
  const input = inputFor(values);
  const accessType = input.accessType;

  // The timer reads the latest form and `run` when it fires, not when the
  // trigger happened.
  const latestRef = useRef({ input, run: checks.run });
  useEffect(() => {
    latestRef.current = { input, run: checks.run };
  });

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleRef = useRef(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      const latest = latestRef.current;
      void latest.run(latest.input);
    }, RUN_DEBOUNCE_MS);
  });

  useEffect(
    () => () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    },
    []
  );

  // A credential change remounts this card, so this also covers selection.
  useEffect(() => {
    scheduleRef.current();
  }, [accessType]);

  // A text field runs the checks when the admin leaves it, so a partial
  // value is not checked while they type. Tabs and checkboxes run at once.
  useEffect(() => {
    if (runOnChangeKey === undefined) return;
    const active = document.activeElement;
    const typing =
      active instanceof HTMLTextAreaElement ||
      (active instanceof HTMLInputElement && active.type !== "checkbox");
    if (!typing) scheduleRef.current();
  }, [runOnChangeKey]);

  useEffect(() => {
    const containers = fieldContainerRefs
      .map((ref) => ref.current)
      .filter((container): container is HTMLElement => container !== null);
    const schedule = () => scheduleRef.current();
    const listeners = new AbortController();
    for (const container of containers) {
      container.addEventListener("focusout", schedule, {
        signal: listeners.signal,
      });
    }
    return () => listeners.abort();
  }, [fieldContainerRefs]);

  const fieldLabels = useMemo(
    () =>
      fieldLabelsOf(
        [...configuration.values, ...configuration.advanced_values],
        currentCredential
      ),
    [configuration, currentCredential]
  );

  // Runs the checks for the current input again. Failed results run again
  // and passed ones come from the cache; indeterminate ones are never cached.
  const rerun = () => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
    const latest = latestRef.current;
    void latest.run(latest.input, { force: true, rerunFailed: true });
  };

  // A failed request hides the card; creation then runs the checks itself.
  if (checks.error) return null;

  return (
    <ConnectorsCheckCard
      draft={checks.snapshot}
      running={checks.running}
      onRerun={rerun}
      highlighted={highlighted}
      fieldLabels={fieldLabels}
    />
  );
}
