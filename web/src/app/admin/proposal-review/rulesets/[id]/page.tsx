"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import InputSearch from "@/refresh-components/inputs/InputSearch";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { toast } from "@/hooks/useToast";
import { Button, Text, Tag, Card } from "@opal/components";
import { ContentAction, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClipboard,
  SvgEdit,
  SvgMoreHorizontal,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgPlus,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { markdown } from "@opal/utils";
import RuleEditor from "@/app/admin/proposal-review/components/RuleEditor";
import ImportFlow from "@/app/admin/proposal-review/components/ImportFlow";
import { useImportStatus } from "@/app/admin/proposal-review/hooks/useImportStatus";
import RefinementModal from "@/app/admin/proposal-review/components/RefinementModal";
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
  const [refineTarget, setRefineTarget] = useState<RuleResponse | null>(null);
  const [ruleSearch, setRuleSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Import job tracking — persists across navigation via the hook's SWR polling
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const handledJobRef = useRef<string | null>(null);
  const { importJob, isProcessing, isComplete, isFailed } = useImportStatus(
    rulesetId,
    importJobId
  );

  // When import completes, refresh the ruleset and show toast
  useEffect(() => {
    if (!importJob || handledJobRef.current === importJob.id) return;

    // SWR has picked up the job — safe to drop the eager upload indicator
    setIsUploading(false);

    if (isComplete) {
      handledJobRef.current = importJob.id;
      mutate(apiUrl);
      toast.success(
        `Imported ${importJob.rules_created} rule${
          importJob.rules_created !== 1 ? "s" : ""
        } from "${importJob.source_filename}" as inactive drafts.`
      );
      setImportJobId(null);
    }
    if (isFailed) {
      handledJobRef.current = importJob.id;
      toast.error(
        `Import failed: ${importJob.error_message || "Unknown error"}`
      );
      setImportJobId(null);
    }
  }, [isComplete, isFailed, importJob, apiUrl]);

  async function handleImportFile(file: File) {
    setShowImportFlow(false);
    setIsUploading(true);

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
      setIsUploading(false);
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
        const err = await res.json().catch(() => ({}));
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
        const err = await res.json().catch(() => ({}));
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
      setSelectedRuleIds(new Set());
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

  const categories = useMemo(() => {
    if (!ruleset) return [];
    const cats = new Set(
      ruleset.rules.map((r) => r.category).filter(Boolean) as string[]
    );
    return Array.from(cats).sort();
  }, [ruleset]);

  const filteredRules = useMemo(() => {
    if (!ruleset) return [];
    let rules = ruleset.rules;

    if (ruleSearch) {
      const q = ruleSearch.toLowerCase();
      rules = rules.filter(
        (rule) =>
          rule.name.toLowerCase().includes(q) ||
          (rule.category ?? "").toLowerCase().includes(q) ||
          (rule.description ?? "").toLowerCase().includes(q)
      );
    }

    if (categoryFilter !== "all") {
      rules = rules.filter((r) => r.category === categoryFilter);
    }

    if (statusFilter === "active") {
      rules = rules.filter((r) => r.is_active);
    } else if (statusFilter === "inactive") {
      rules = rules.filter((r) => !r.is_active);
    } else if (statusFilter === "refinement") {
      rules = rules.filter((r) => r.refinement_needed);
    }

    // Sort: refinement-needed first, then by category + name
    const natural = { numeric: true, sensitivity: "base" } as const;
    return [...rules].sort((a, b) => {
      // Refinement-needed rules float to the top
      if (a.refinement_needed !== b.refinement_needed) {
        return a.refinement_needed ? -1 : 1;
      }
      const catCmp = (a.category ?? "").localeCompare(
        b.category ?? "",
        undefined,
        natural
      );
      if (catCmp !== 0) return catCmp;
      return a.name.localeCompare(b.name, undefined, natural);
    });
  }, [ruleset, ruleSearch, categoryFilter, statusFilter]);

  const refinementRules = useMemo(
    () => filteredRules.filter((r) => r.refinement_needed),
    [filteredRules]
  );
  const otherRules = useMemo(
    () => filteredRules.filter((r) => !r.refinement_needed),
    [filteredRules]
  );

  const filteredRuleIds = useMemo(
    () => new Set(filteredRules.map((r) => r.id)),
    [filteredRules]
  );

  // "All selected" means every currently visible (filtered) rule is selected
  const filteredRuleIdArr = Array.from(filteredRuleIds);

  const allSelected =
    filteredRuleIds.size > 0 &&
    filteredRuleIdArr.every((id) => selectedRuleIds.has(id));

  const someSelected =
    !allSelected && filteredRuleIdArr.some((id) => selectedRuleIds.has(id));

  function toggleSelectAll() {
    if (allSelected) {
      // Deselect all visible rules (keep any selected but currently hidden rules)
      setSelectedRuleIds((prev) => {
        const next = new Set(prev);
        filteredRuleIdArr.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      // Select all visible rules
      setSelectedRuleIds((prev) => {
        const next = new Set(prev);
        filteredRuleIdArr.forEach((id) => next.add(id));
        return next;
      });
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
    const isSelected = selectedRuleIds.has(rule.id);

    return (
      <div className="flex items-center gap-3">
        <div onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={isSelected}
            onCheckedChange={() => toggleSelectRule(rule.id)}
            aria-label={`Select ${rule.name}`}
          />
        </div>
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => {
            if (rule.refinement_needed) {
              setRefineTarget(rule);
            } else {
              setEditingRule(rule);
              setShowRuleEditor(true);
            }
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
                  className="flex items-center gap-2 shrink-0"
                  onClick={(e) => e.stopPropagation()}
                >
                  {rule.category && (
                    <SimpleTooltip
                      tooltip={rule.category}
                      side="top"
                      delayDuration={0}
                    >
                      <div className="max-w-[160px] overflow-hidden [&>.opal-auxiliary-tag]:shrink [&>.opal-auxiliary-tag>span]:truncate">
                        <Tag title={rule.category} color="gray" size="sm" />
                      </div>
                    </SimpleTooltip>
                  )}
                  <Tag
                    title={rule.is_active ? "Active" : "Inactive"}
                    color={rule.is_active ? "green" : "gray"}
                    size="sm"
                  />
                  {rule.refinement_needed && (
                    <Tag title="Needs Refinement" color="purple" size="sm" />
                  )}
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
                        {rule.refinement_needed && (
                          <LineItem
                            icon={SvgAlertCircle}
                            onClick={() => setRefineTarget(rule)}
                          >
                            Answer Refinement Question
                          </LineItem>
                        )}
                        <LineItem
                          icon={
                            rule.is_active ? SvgPauseCircle : SvgCheckCircle
                          }
                          onClick={() => handleToggleRuleActive(rule)}
                        >
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
        description={
          ruleset.description
            ? `${ruleset.description} · ${ruleset.rules.length} rule${
                ruleset.rules.length !== 1 ? "s" : ""
              }`
            : `${ruleset.rules.length} rule${
                ruleset.rules.length !== 1 ? "s" : ""
              }`
        }
        backButton
        editable
        onTitleChange={async (newName) => {
          await handleUpdateRuleset({ name: newName });
        }}
        separator
      />
      <SettingsLayouts.Body>
        {/* Import progress bar */}
        {(isUploading || (isProcessing && importJob)) && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-08 bg-background-neutral-02">
            <div className="h-2 flex-1 min-w-[80px] rounded-08 bg-border-02 animate-pulse" />
            <Text font="secondary-body" color="text-03" nowrap>
              {importJob && importJob.rules_created > 0
                ? `${importJob.rules_created} rule${
                    importJob.rules_created !== 1 ? "s" : ""
                  } created`
                : isUploading
                  ? "Uploading..."
                  : `Analyzing "${importJob!.source_filename}"...`}
            </Text>
          </div>
        )}

        {/* Search + action bar */}
        <div className="flex items-center gap-3">
          {ruleset.rules.length > 0 && (
            <Checkbox
              checked={allSelected}
              indeterminate={someSelected}
              onCheckedChange={toggleSelectAll}
              aria-label="Select all rules"
            />
          )}
          <div className="flex-1">
            <InputSearch
              placeholder="Search rules..."
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
            />
          </div>
          {categories.length > 0 && (
            <div className="shrink-0">
              <InputSelect
                value={categoryFilter}
                onValueChange={setCategoryFilter}
              >
                <InputSelect.Trigger placeholder="Category" />
                <InputSelect.Content>
                  <InputSelect.Item value="all">
                    All Categories
                  </InputSelect.Item>
                  {categories.map((cat) => (
                    <InputSelect.Item key={cat} value={cat}>
                      {cat}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </div>
          )}
          <div className="shrink-0">
            <InputSelect value={statusFilter} onValueChange={setStatusFilter}>
              <InputSelect.Trigger placeholder="Status" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All Statuses</InputSelect.Item>
                <InputSelect.Item value="active">Active</InputSelect.Item>
                <InputSelect.Item value="inactive">Inactive</InputSelect.Item>
                <InputSelect.Item value="refinement">
                  Needs Refinement
                </InputSelect.Item>
              </InputSelect.Content>
            </InputSelect>
          </div>
          {selectedRuleIds.size > 0 ? (
            <>
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
            </>
          ) : (
            <>
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
            </>
          )}
        </div>

        {/* Rules list */}
        {ruleset.rules.length === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title="No rules yet"
            description="Add rules manually or import from a checklist."
          />
        ) : filteredRules.length === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title="No matching rules"
            description="Try a different search term."
          />
        ) : (
          <div className="flex flex-col gap-2">
            {refinementRules.map((rule) => (
              <RuleCard key={rule.id} rule={rule} />
            ))}
            {refinementRules.length > 0 && otherRules.length > 0 && (
              <hr className="border-border-02" />
            )}
            {otherRules.map((rule) => (
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

      {/* Rule Refinement Modal */}
      <RefinementModal
        open={!!refineTarget}
        onClose={() => setRefineTarget(null)}
        rule={refineTarget}
        onRefined={() => mutate(apiUrl)}
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
