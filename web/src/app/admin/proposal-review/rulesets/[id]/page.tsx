"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { toast } from "@/hooks/useToast";
import { Button, Text, Tag, Table } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { createTableColumns } from "@opal/components/table/columns";
import {
  SvgCheckSquare,
  SvgEdit,
  SvgMoreHorizontal,
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
import type {
  RulesetResponse,
  RulesetUpdate,
  RuleResponse,
  RuleCreate,
  RuleUpdate,
  BulkRuleUpdateRequest,
  RuleIntent,
} from "@/app/admin/proposal-review/interfaces";
import {
  RULE_TYPE_LABELS,
  RULE_INTENT_LABELS,
} from "@/app/admin/proposal-review/interfaces";
import type { TagColor } from "@opal/components";

const tc = createTableColumns<RuleResponse>();

function intentColor(intent: RuleIntent): TagColor {
  return intent === "CHECK" ? "green" : "purple";
}

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

  // Batch selection
  const [selectedRuleIds, setSelectedRuleIds] = useState<Set<string>>(
    new Set()
  );
  const [batchSaving, setBatchSaving] = useState(false);

  // Toggle handlers
  async function handleToggleActive() {
    if (!ruleset) return;
    try {
      const body: RulesetUpdate = { is_active: !ruleset.is_active };
      const res = await fetch(apiUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to toggle active status");
      }
      await mutate(apiUrl);
      toast.success(
        ruleset.is_active ? "Ruleset deactivated." : "Ruleset activated."
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to toggle active status"
      );
    }
  }

  async function handleToggleDefault() {
    if (!ruleset) return;
    try {
      const body: RulesetUpdate = { is_default: !ruleset.is_default };
      const res = await fetch(apiUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to toggle default status");
      }
      await mutate(apiUrl);
      toast.success(
        ruleset.is_default
          ? "Removed default status."
          : "Set as default ruleset."
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to toggle default status"
      );
    }
  }

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

  // Group rules by category
  const groupedRules = useMemo(() => {
    if (!ruleset?.rules) return {};
    const groups: Record<string, RuleResponse[]> = {};
    for (const rule of ruleset.rules) {
      const cat = rule.category || "Uncategorized";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(rule);
    }
    return groups;
  }, [ruleset?.rules]);

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

  const ruleColumns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgCheckSquare,
      }),
      tc.column("name", {
        header: "Name",
        weight: 25,
        cell: (value, row) =>
          row.description ? (
            <Content
              title={value}
              description={row.description}
              sizePreset="main-ui"
              variant="section"
            />
          ) : (
            <Content title={value} sizePreset="main-ui" variant="body" />
          ),
      }),
      tc.column("rule_type", {
        header: "Type",
        weight: 15,
        cell: (value) => <Tag title={RULE_TYPE_LABELS[value]} color="gray" />,
      }),
      tc.column("rule_intent", {
        header: "Intent",
        weight: 10,
        cell: (value) => (
          <Tag title={RULE_INTENT_LABELS[value]} color={intentColor(value)} />
        ),
      }),
      tc.displayColumn({
        id: "source",
        header: "Source",
        width: { weight: 10, minWidth: 80 },
        cell: (row) => (
          <Tag
            title={row.source === "IMPORTED" ? "Imported" : "Manual"}
            color={row.source === "IMPORTED" ? "blue" : "gray"}
          />
        ),
      }),
      tc.displayColumn({
        id: "hard_stop",
        header: "Hard Stop",
        width: { weight: 10, minWidth: 80 },
        cell: (row) =>
          row.is_hard_stop ? <Tag title="Hard Stop" color="amber" /> : null,
      }),
      tc.displayColumn({
        id: "active",
        header: "Active",
        width: { weight: 8, minWidth: 60 },
        cell: (row) => (
          <Tag
            title={row.is_active ? "Yes" : "No"}
            color={row.is_active ? "green" : "gray"}
          />
        ),
      }),
      tc.actions({
        cell: (row) => (
          <div className="flex flex-row gap-1">
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
                      setEditingRule(row);
                      setShowRuleEditor(true);
                    }}
                  >
                    Edit Rule
                  </LineItem>
                  <LineItem onClick={() => handleToggleRuleActive(row)}>
                    {row.is_active ? "Deactivate" : "Activate"}
                  </LineItem>
                  <LineItem
                    icon={SvgTrash}
                    danger
                    onClick={() => setDeleteTarget(row)}
                  >
                    Delete Rule
                  </LineItem>
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        ),
      }),
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  if (isLoading) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgCheckSquare}
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
          icon={SvgCheckSquare}
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
        icon={SvgCheckSquare}
        title={ruleset.name}
        description={ruleset.description || undefined}
        backButton
        rightChildren={
          <div className="flex items-center gap-2">
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
        }
        separator
      />
      <SettingsLayouts.Body>
        {/* Ruleset toggles */}
        <div className="flex items-center gap-4 pb-2">
          <Button
            prominence={ruleset.is_active ? "primary" : "secondary"}
            size="sm"
            onClick={handleToggleActive}
          >
            {ruleset.is_active ? "Active" : "Inactive"}
          </Button>
          <Button
            prominence={ruleset.is_default ? "primary" : "secondary"}
            size="sm"
            onClick={handleToggleDefault}
          >
            {ruleset.is_default ? "Default Ruleset" : "Not Default"}
          </Button>
        </div>

        {/* Batch action bar */}
        {selectedRuleIds.size > 0 && (
          <div className="flex items-center gap-3 p-3 bg-background-neutral-02 rounded-08">
            <Text font="main-ui-action" color="text-02">
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

        {/* Rules table grouped by category */}
        {ruleset.rules.length === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title="No rules yet"
            description="Add rules manually or import from a checklist."
          />
        ) : (
          Object.entries(groupedRules).map(([category, rules]) => (
            <div key={category} className="flex flex-col gap-2">
              <Text font="main-ui-action" color="text-02">
                {category}
              </Text>
              <Table
                data={rules}
                getRowId={(row) => row.id}
                columns={ruleColumns}
              />
            </div>
          ))
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
        rulesetId={rulesetId}
        onImportComplete={() => mutate(apiUrl)}
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
