"use client";

import { useState, useMemo, useEffect } from "react";
import { useParams } from "next/navigation";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import InputSearch from "@/refresh-components/inputs/InputSearch";
import { toast } from "@/hooks/useToast";
import { Button, Text, Tag, Card } from "@opal/components";
import { ContentAction, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgClipboard,
  SvgEdit,
  SvgMoreHorizontal,
  SvgPlayCircle,
  SvgPlus,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { markdown } from "@opal/utils";
import RuleEditor from "@/app/admin/proposal-review/components/RuleEditor";
import ImportFlow from "@/app/admin/proposal-review/components/ImportFlow";
import { useImportStatus } from "@/app/admin/proposal-review/hooks/useImportStatus";
import RuleTestModal from "@/app/admin/proposal-review/components/RuleTestModal";
import type {
  RulesetResponse,
  RulesetUpdate,
  RuleResponse,
  RuleCreate,
  RuleUpdate,
  BulkRuleUpdateRequest,
} from "@/app/admin/proposal-review/interfaces";

function RulesetDetailPage() {
  const params = useParams();
  const rulesetId = params.id as string;
  const apiUrl = `/api/proposal-review/rulesets/${rulesetId}`;

  const {
    data: ruleset,
    isLoading,
    error,
  } = useSWR<RulesetResponse>(apiUrl, errorHandlingFetcher);

  // Modal states
  const [showRuleEditor, setShowRuleEditor] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleResponse | null>(null);
  const [showImportFlow, setShowImportFlow] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<RuleResponse | null>(null);
  const [testTarget, setTestTarget] = useState<RuleResponse | null>(null);
  const [ruleSearch, setRuleSearch] = useState("");

  // Import job tracking — persists across navigation via the hook's SWR polling
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const { importJob, isProcessing, isComplete, isFailed } = useImportStatus(
    rulesetId,
    importJobId
  );

  // When import completes, refresh the ruleset and show toast
  useEffect(() => {
    if (isComplete && importJob) {
      mutate(apiUrl);
      toast.success(
        `Imported ${importJob.rules_created} rule${
          importJob.rules_created !== 1 ? "s" : ""
        } from "${importJob.source_filename}" as inactive drafts.`
      );
      setImportJobId(null);
    }
    if (isFailed && importJob) {
      toast.error(
        `Import failed: ${importJob.error_message || "Unknown error"}`
      );
      setImportJobId(null);
    }
  }, [isComplete, isFailed, importJob]);

  async function handleImportFile(file: File) {
    setShowImportFlow(false);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(
        `/api/proposal-review/rulesets/${rulesetId}/import`,
        { method: "POST", body: formData }
      );

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to import checklist");
      }

      const data = await res.json();
      setImportJobId(data.import_job_id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
    }
  }

  // Batch selection
  const [selectedRuleIds, setSelectedRuleIds] = useState<Set<string>>(
    new Set()
  );
  const [batchSaving, setBatchSaving] = useState(false);

  // Update ruleset metadata (name, description)
  async function handleUpdateRuleset(updates: Partial<RulesetUpdate>) {
    try {
      const res = await fetch(apiUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!res.ok) throw new Error("Failed to update ruleset");
      await mutate(apiUrl);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update ruleset"
      );
    }
  }

  // Toggle handlers (for individual rule active/inactive)
  async function handleToggleRuleActive(rule: RuleResponse) {
    try {
      const update: RuleUpdate = { is_active: !rule.is_active };
      const res = await fetch(`/api/proposal-review/rules/${rule.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to toggle rule active status");
      }
      await mutate(apiUrl);
      toast.success(rule.is_active ? "Rule deactivated." : "Rule activated.");
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Failed to toggle rule active status"
      );
    }
  }

  // Rule CRUD
  async function handleSaveRule(ruleData: RuleCreate | RuleUpdate) {
    if (editingRule) {
      const res = await fetch(`/api/proposal-review/rules/${editingRule.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ruleData),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to update rule");
      }
      toast.success("Rule updated.");
    } else {
      const res = await fetch(
        `/api/proposal-review/rulesets/${rulesetId}/rules`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ruleData),
        }
      );
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to create rule");
      }
      toast.success("Rule created.");
    }
    await mutate(apiUrl);
  }

  async function handleDeleteRule(rule: RuleResponse) {
    try {
      const res = await fetch(`/api/proposal-review/rules/${rule.id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to delete rule");
      }
      setSelectedRuleIds((prev) => {
        const next = new Set(prev);
        next.delete(rule.id);
        return next;
      });
      await mutate(apiUrl);
      toast.success("Rule deleted.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete rule");
    }
  }

  // Batch operations
  async function handleBulkAction(action: BulkRuleUpdateRequest["action"]) {
    if (selectedRuleIds.size === 0) return;
    setBatchSaving(true);
    try {
      const body: BulkRuleUpdateRequest = {
        action,
        rule_ids: Array.from(selectedRuleIds),
      };
      const res = await fetch(
        `/api/proposal-review/rulesets/${rulesetId}/rules/bulk-update`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Bulk operation failed");
      }
      if (action === "delete") {
        setSelectedRuleIds(new Set());
      }
      await mutate(apiUrl);
      toast.success(
        `Bulk ${action} completed for ${selectedRuleIds.size} rule${
          selectedRuleIds.size === 1 ? "" : "s"
        }.`
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Bulk operation failed");
    } finally {
      setBatchSaving(false);
    }
  }

  const allRuleIds = useMemo(
    () => new Set(ruleset?.rules.map((r) => r.id) || []),
    [ruleset?.rules]
  );

  const allSelected =
    allRuleIds.size > 0 && selectedRuleIds.size === allRuleIds.size;

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedRuleIds(new Set());
    } else {
      setSelectedRuleIds(new Set(allRuleIds));
    }
  }

  function toggleSelectRule(ruleId: string) {
    setSelectedRuleIds((prev) => {
      const next = new Set(prev);
      if (next.has(ruleId)) {
        next.delete(ruleId);
      } else {
        next.add(ruleId);
      }
      return next;
    });
  }

  function RuleCard({ rule }: { rule: RuleResponse }) {
    return (
      <div
        className="cursor-pointer"
        onClick={() => {
          setEditingRule(rule);
          setShowRuleEditor(true);
        }}
      >
        <Card padding="md" border="solid" background="light">
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            title={rule.name}
            description={rule.description || rule.category || undefined}
            rightChildren={
              <div
                className="flex items-center gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                {rule.category && (
                  <Tag title={rule.category} color="gray" size="sm" />
                )}
                <Tag
                  title={rule.is_active ? "Active" : "Inactive"}
                  color={rule.is_active ? "green" : "gray"}
                  size="sm"
                />
                {rule.is_hard_stop && (
                  <Tag title="Hard Stop" color="amber" size="sm" />
                )}
                <Popover>
                  <Popover.Trigger asChild>
                    <Button
                      icon={SvgMoreHorizontal}
                      prominence="tertiary"
                      tooltip="More"
                    />
                  </Popover.Trigger>
                  <Popover.Content side="bottom" align="end" width="md">
                    <PopoverMenu>
                      <LineItem
                        icon={SvgEdit}
                        onClick={() => {
                          setEditingRule(rule);
                          setShowRuleEditor(true);
                        }}
                      >
                        Edit Rule
                      </LineItem>
                      <LineItem
                        icon={SvgPlayCircle}
                        onClick={() => setTestTarget(rule)}
                      >
                        Test Rule
                      </LineItem>
                      <LineItem onClick={() => handleToggleRuleActive(rule)}>
                        {rule.is_active ? "Deactivate" : "Activate"}
                      </LineItem>
                      <LineItem
                        icon={SvgTrash}
                        danger
                        onClick={() => setDeleteTarget(rule)}
                      >
                        Delete Rule
                      </LineItem>
                    </PopoverMenu>
                  </Popover.Content>
                </Popover>
              </div>
            }
          />
        </Card>
      </div>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgClipboard}
          title="Loading..."
          backButton
          separator
        />
        <SettingsLayouts.Body>
          <SimpleLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (error || !ruleset) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgClipboard}
          title="Ruleset"
          backButton
          separator
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="Failed to load ruleset."
            description={
              error?.info?.message ||
              error?.info?.detail ||
              "Ruleset not found."
            }
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClipboard}
        title={ruleset.name}
        description={ruleset.description || undefined}
        backButton
        editable
        onTitleChange={async (newName) => {
          await handleUpdateRuleset({ name: newName });
        }}
        separator
      />
      <SettingsLayouts.Body>
        {/* Import status banner */}
        {isProcessing && importJob && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-08 bg-background-neutral-02">
            <SimpleLoader className="h-4 w-4" />
            <Text font="main-ui-body" color="text-04">
              {`Analyzing "${importJob.source_filename}"...`}
            </Text>
          </div>
        )}

        {/* Search + action bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <InputSearch
              placeholder="Search rules..."
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
            />
          </div>
          <Button
            prominence="secondary"
            icon={SvgUploadCloud}
            onClick={() => setShowImportFlow(true)}
          >
            Import
          </Button>
          <Button
            icon={SvgPlus}
            onClick={() => {
              setEditingRule(null);
              setShowRuleEditor(true);
            }}
          >
            Add Rule
          </Button>
        </div>

        {/* Batch action bar */}
        {selectedRuleIds.size > 0 && (
          <div className="flex items-center gap-3 p-3 bg-background-neutral-02 rounded-08">
            <Text font="main-ui-action" color="text-03">
              {`${selectedRuleIds.size} selected`}
            </Text>
            <Button
              prominence="secondary"
              size="sm"
              onClick={() => handleBulkAction("activate")}
              disabled={batchSaving}
            >
              Activate
            </Button>
            <Button
              prominence="secondary"
              size="sm"
              onClick={() => handleBulkAction("deactivate")}
              disabled={batchSaving}
            >
              Deactivate
            </Button>
            <Button
              variant="danger"
              prominence="secondary"
              size="sm"
              onClick={() => handleBulkAction("delete")}
              disabled={batchSaving}
            >
              Delete
            </Button>
          </div>
        )}

        {/* Rules list */}
        {ruleset.rules.length === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title="No rules yet"
            description="Add rules manually or import from a checklist."
          />
        ) : (
          <div className="flex flex-col gap-2">
            {ruleset.rules
              .filter((rule) => {
                if (!ruleSearch) return true;
                const q = ruleSearch.toLowerCase();
                return (
                  rule.name.toLowerCase().includes(q) ||
                  (rule.category ?? "").toLowerCase().includes(q) ||
                  (rule.description ?? "").toLowerCase().includes(q)
                );
              })
              .map((rule) => (
                <RuleCard key={rule.id} rule={rule} />
              ))}
          </div>
        )}
      </SettingsLayouts.Body>

      {/* Rule Editor Modal */}
      <RuleEditor
        open={showRuleEditor}
        onClose={() => {
          setShowRuleEditor(false);
          setEditingRule(null);
        }}
        onSave={handleSaveRule}
        existingRule={editingRule}
      />

      {/* Import Flow Modal */}
      <ImportFlow
        open={showImportFlow}
        onClose={() => setShowImportFlow(false)}
        onFileSelected={handleImportFile}
      />

      {/* Rule Test Modal */}
      <RuleTestModal
        open={!!testTarget}
        onClose={() => setTestTarget(null)}
        rule={testTarget}
      />

      {/* Delete Rule Confirmation */}
      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Rule"
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                const target = deleteTarget;
                setDeleteTarget(null);
                await handleDeleteRule(target);
              }}
            >
              Delete
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              `Are you sure you want to delete *${deleteTarget.name}*? This action cannot be undone.`
            )}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}

export default function Page() {
  return <RulesetDetailPage />;
}
