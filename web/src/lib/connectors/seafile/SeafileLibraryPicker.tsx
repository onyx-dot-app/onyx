"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { TextArrayField } from "@/components/Field";
import type { CredentialValues } from "@/lib/credentials/types";
import { Button, InputCheckbox, Text } from "@opal/components";
import { SvgLoader, SvgRefreshCw } from "@opal/icons";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";

interface FormValues {
  base_url?: string;
  repo_ids?: string[];
}

interface SeafileLibrary {
  id: string;
  name: string;
  owner?: string | null;
}

interface SeafileLibraryPickerProps {
  currentCredential: (CredentialValues & { id?: number }) | null;
  label: string;
  description: string;
}

const librariesEndpoint = "/api/manage/admin/connector/seafile/libraries";

function canonicalSeafileRepoId(repoId: string): string {
  return repoId.split("@", 1)[0] ?? repoId;
}

function dedupeSeafileLibraries(
  libraries: SeafileLibrary[],
  selectedRepoIds: string[]
): SeafileLibrary[] {
  const selectedByCanonicalId = new Map(
    selectedRepoIds.map((repoId) => [canonicalSeafileRepoId(repoId), repoId])
  );
  const librariesByCanonicalId = new Map<string, SeafileLibrary>();

  for (const library of libraries) {
    const canonicalId = canonicalSeafileRepoId(library.id);
    const existingLibrary = librariesByCanonicalId.get(canonicalId);
    if (!existingLibrary) {
      librariesByCanonicalId.set(canonicalId, library);
      continue;
    }

    const selectedRepoId = selectedByCanonicalId.get(canonicalId);
    if (selectedRepoId === library.id) {
      librariesByCanonicalId.set(canonicalId, library);
      continue;
    }

    if (
      selectedRepoId !== existingLibrary.id &&
      existingLibrary.id !== canonicalId &&
      library.id === canonicalId
    ) {
      librariesByCanonicalId.set(canonicalId, library);
    }
  }

  return Array.from(librariesByCanonicalId.values());
}

async function fetchSeafileLibraries(
  baseUrl: string,
  credentialId: number,
  signal?: AbortSignal
): Promise<SeafileLibrary[]> {
  const response = await fetch(librariesEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ base_url: baseUrl, credential_id: credentialId }),
    signal,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || "Unable to fetch Seafile libraries.");
  }

  return response.json();
}

export default function SeafileLibraryPicker({
  currentCredential,
  label,
  description,
}: SeafileLibraryPickerProps) {
  const t = useTranslations("admin.connector.seafile.libraryPicker");
  const { values, setFieldValue } = useFormikContext<FormValues>();
  const [libraries, setLibraries] = useState<SeafileLibrary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baseUrl = typeof values.base_url === "string" ? values.base_url : "";
  const selectedRepoIds = useMemo(
    () => (Array.isArray(values.repo_ids) ? (values.repo_ids as string[]) : []),
    [values.repo_ids]
  );
  const selectedCanonicalRepoIds = useMemo(
    () => new Set(selectedRepoIds.map(canonicalSeafileRepoId)),
    [selectedRepoIds]
  );
  const visibleLibraries = useMemo(
    () => dedupeSeafileLibraries(libraries, selectedRepoIds),
    [libraries, selectedRepoIds]
  );
  const canFetch = Boolean(baseUrl.trim() && currentCredential?.id);

  const loadLibraries = useCallback(
    async (signal?: AbortSignal) => {
      if (!currentCredential?.id || !baseUrl.trim()) {
        setLibraries([]);
        return;
      }

      setIsLoading(true);
      setError(null);
      try {
        const fetchedLibraries = await fetchSeafileLibraries(
          baseUrl,
          currentCredential.id,
          signal
        );
        setLibraries(fetchedLibraries);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setLibraries([]);
        setError(err instanceof Error ? err.message : t("fetchError"));
      } finally {
        setIsLoading(false);
      }
    },
    [baseUrl, currentCredential?.id, t]
  );

  useEffect(() => {
    if (!canFetch) {
      setLibraries([]);
      setError(null);
      return;
    }

    const controller = new AbortController();
    void loadLibraries(controller.signal);
    return () => controller.abort();
  }, [canFetch, loadLibraries]);

  const toggleLibrary = (libraryId: string, checked: boolean) => {
    const canonicalLibraryId = canonicalSeafileRepoId(libraryId);
    const repoIdsWithoutLibrary = selectedRepoIds.filter(
      (repoId) => canonicalSeafileRepoId(repoId) !== canonicalLibraryId
    );
    const nextRepoIds = checked
      ? [...repoIdsWithoutLibrary, libraryId]
      : repoIdsWithoutLibrary;
    setFieldValue("repo_ids", Array.from(new Set(nextRepoIds)));
  };

  const showManualFallback =
    !canFetch || Boolean(error) || visibleLibraries.length === 0;

  return (
    <div className="mb-4 w-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="block font-medium text-base">{label}</div>
          <div className="block text-sm text-text-03 mb-2">{description}</div>
        </div>
        {canFetch && (
          <Button
            type="button"
            prominence="secondary"
            icon={isLoading ? SvgLoader : SvgRefreshCw}
            disabled={isLoading}
            onClick={() => void loadLibraries()}
          >
            {t("refresh")}
          </Button>
        )}
      </div>

      {isLoading && <div className="text-sm text-text-03">{t("loading")}</div>}

      {error && <div className="text-sm text-action-danger-05">{error}</div>}

      {!isLoading && visibleLibraries.length > 0 && (
        <div className="mt-3 space-y-2">
          {visibleLibraries.map((library) => (
            <label
              key={library.id}
              htmlFor={`seafile-library-${library.id}`}
              className="flex items-start gap-3 rounded border border-border bg-background px-3 py-2"
            >
              <InputCheckbox
                id={`seafile-library-${library.id}`}
                checked={selectedCanonicalRepoIds.has(
                  canonicalSeafileRepoId(library.id)
                )}
                onCheckedChange={(checked) =>
                  toggleLibrary(library.id, checked)
                }
              />
              <div className="min-w-0">
                <div>
                  <Text font="main-ui-body">{library.name}</Text>
                </div>
                <div className="break-all">
                  <Text font="secondary-body" color="text-03">
                    {library.id + (library.owner ? ` - ${library.owner}` : "")}
                  </Text>
                </div>
              </div>
            </label>
          ))}
        </div>
      )}

      {showManualFallback && (
        <div className="mt-3">
          <TextArrayField
            name="repo_ids"
            label={t("manualLabel")}
            values={values}
            subtext={t("manualDescription")}
            placeholder={t("manualPlaceholder")}
          />
        </div>
      )}
    </div>
  );
}
