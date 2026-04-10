"use client";

import React, { useState, useRef } from "react";
import { Text, Tag } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { toast } from "@/hooks/useToast";
import type { RuleResponse } from "@/app/admin/proposal-review/interfaces";
import { RULE_TYPE_LABELS } from "@/app/admin/proposal-review/interfaces";

interface ImportFlowProps {
  open: boolean;
  onClose: () => void;
  rulesetId: string;
  onImportComplete: () => void;
}

type ImportStep = "upload" | "processing" | "review";

function ImportFlow({
  open,
  onClose,
  rulesetId,
  onImportComplete,
}: ImportFlowProps) {
  const [step, setStep] = useState<ImportStep>("upload");
  const [importedRules, setImportedRules] = useState<RuleResponse[]>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<Set<string>>(
    new Set()
  );
  const [expandedRuleId, setExpandedRuleId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleReset() {
    setStep("upload");
    setImportedRules([]);
    setSelectedRuleIds(new Set());
    setExpandedRuleId(null);
    setSaving(false);
  }

  function handleClose() {
    handleReset();
    onClose();
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setStep("processing");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(
        `/api/proposal-review/rulesets/${rulesetId}/import`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to import checklist");
      }

      const data = await res.json();
      setImportedRules(data.rules);
      setSelectedRuleIds(new Set(data.rules.map((r: RuleResponse) => r.id)));
      setStep("review");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
      setStep("upload");
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function toggleRule(ruleId: string) {
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

  function handleSelectAll() {
    setSelectedRuleIds(new Set(importedRules.map((r) => r.id)));
  }

  function handleDeselectAll() {
    setSelectedRuleIds(new Set());
  }

  async function handleAccept() {
    if (selectedRuleIds.size === 0) return;

    setSaving(true);
    try {
      const unselectedIds = importedRules
        .filter((r) => !selectedRuleIds.has(r.id))
        .map((r) => r.id);

      // Activate selected rules
      const activateRes = await fetch(
        `/api/proposal-review/rulesets/${rulesetId}/rules/bulk-update`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "activate",
            rule_ids: Array.from(selectedRuleIds),
          }),
        }
      );
      if (!activateRes.ok) {
        const err = await activateRes.json();
        throw new Error(err.detail || "Failed to activate rules");
      }

      // Delete unselected rules
      if (unselectedIds.length > 0) {
        const deleteRes = await fetch(
          `/api/proposal-review/rulesets/${rulesetId}/rules/bulk-update`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "delete",
              rule_ids: unselectedIds,
            }),
          }
        );
        if (!deleteRes.ok) {
          const err = await deleteRes.json();
          throw new Error(err.detail || "Failed to clean up unselected rules");
        }
      }

      toast.success(
        `${selectedRuleIds.size} rule${
          selectedRuleIds.size === 1 ? "" : "s"
        } imported.`
      );
      onImportComplete();
      handleClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save rules");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Import from Checklist"
          description="Upload a checklist document to generate rules automatically."
          onClose={handleClose}
        />

        <Modal.Body>
          {step === "upload" && (
            <div className="flex flex-col items-center gap-4 py-8">
              <div className="flex flex-col items-center gap-2">
                <SvgUploadCloud className="h-12 w-12 text-text-03" />
                <Text font="main-ui-body" color="text-02">
                  Upload a checklist document (.xlsx, .docx, or .pdf)
                </Text>
                <Text font="secondary-body" color="text-04">
                  The document will be analyzed to extract review rules.
                </Text>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.docx,.pdf"
                onChange={handleFileUpload}
                className="hidden"
              />

              <Button
                icon={SvgUploadCloud}
                onClick={() => fileInputRef.current?.click()}
              >
                Choose File
              </Button>
            </div>
          )}

          {step === "processing" && (
            <div className="flex flex-col items-center gap-4 py-12">
              <SimpleLoader />
              <Text font="main-ui-body" color="text-02">
                Analyzing document and generating rules...
              </Text>
              <Text font="secondary-body" color="text-04">
                This may take up to a minute.
              </Text>
            </div>
          )}

          {step === "review" && (
            <div className="flex flex-col gap-4">
              {importedRules.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8">
                  <Text font="main-ui-body" color="text-03">
                    No rules were generated from the uploaded document.
                  </Text>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between">
                    <Text font="main-ui-body" color="text-02">
                      {`${importedRules.length} rules generated - ${selectedRuleIds.size} selected`}
                    </Text>
                    <div className="flex gap-2">
                      <Button
                        prominence="tertiary"
                        size="sm"
                        onClick={handleSelectAll}
                      >
                        Select All
                      </Button>
                      <Button
                        prominence="tertiary"
                        size="sm"
                        onClick={handleDeselectAll}
                      >
                        Deselect All
                      </Button>
                    </div>
                  </div>

                  <div className="flex flex-col border border-border-02 rounded-08 overflow-hidden">
                    {/* Header row */}
                    <div className="flex items-center gap-3 px-4 py-2 bg-background-tint-01 border-b border-border-02">
                      <div className="w-6" />
                      <div className="flex-1">
                        <Text font="main-ui-action" color="text-03">
                          Name
                        </Text>
                      </div>
                      <div className="w-32">
                        <Text font="main-ui-action" color="text-03">
                          Type
                        </Text>
                      </div>
                      <div className="w-40">
                        <Text font="main-ui-action" color="text-03">
                          Category
                        </Text>
                      </div>
                    </div>

                    {/* Rule rows */}
                    <div className="max-h-[400px] overflow-y-auto">
                      {importedRules.map((rule) => (
                        <React.Fragment key={rule.id}>
                          <div
                            className="flex items-center gap-3 px-4 py-3 border-b border-border-01 cursor-pointer hover:bg-background-tint-01"
                            onClick={() =>
                              setExpandedRuleId(
                                expandedRuleId === rule.id ? null : rule.id
                              )
                            }
                          >
                            <div
                              className="w-6"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Checkbox
                                checked={selectedRuleIds.has(rule.id)}
                                onCheckedChange={() => toggleRule(rule.id)}
                              />
                            </div>
                            <div className="flex-1">
                              <Text font="main-ui-body" color="text-01">
                                {rule.name}
                              </Text>
                            </div>
                            <div className="w-32">
                              <Tag
                                title={RULE_TYPE_LABELS[rule.rule_type]}
                                color="gray"
                              />
                            </div>
                            <div className="w-40">
                              <Text font="secondary-body" color="text-03">
                                {rule.category || "-"}
                              </Text>
                            </div>
                          </div>
                          {expandedRuleId === rule.id && (
                            <div className="flex flex-col gap-2 px-4 py-3 bg-background-neutral-01 border-b border-border-01">
                              {rule.description && (
                                <div>
                                  <Text font="main-ui-action" color="text-02">
                                    Description
                                  </Text>
                                  <Text
                                    font="secondary-body"
                                    color="text-03"
                                    as="p"
                                  >
                                    {rule.description}
                                  </Text>
                                </div>
                              )}
                              <div>
                                <Text font="main-ui-action" color="text-02">
                                  Prompt Template
                                </Text>
                                <pre className="p-2 bg-background-neutral-02 rounded-08 text-sm font-mono text-text-02 whitespace-pre-wrap overflow-x-auto">
                                  {rule.prompt_template}
                                </pre>
                              </div>
                            </div>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </Modal.Body>

        {step === "review" && importedRules.length > 0 && (
          <Modal.Footer>
            <Button
              prominence="secondary"
              onClick={handleClose}
              disabled={saving}
            >
              Discard
            </Button>
            <Button
              onClick={handleAccept}
              disabled={saving || selectedRuleIds.size === 0}
            >
              {saving
                ? "Saving..."
                : `Accept ${selectedRuleIds.size} Rule${
                    selectedRuleIds.size === 1 ? "" : "s"
                  }`}
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}

export default ImportFlow;
