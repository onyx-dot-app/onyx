"use client";

import { Form, Formik } from "formik";
import { Text } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import { SvgEdit, SvgPlus } from "@opal/icons";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { toast } from "@/hooks/useToast";
import { FormikField } from "@/refresh-components/form/FormikField";
import Modal from "@/refresh-components/Modal";
import { Vertical as VerticalInput } from "@/layouts/input-layouts";
import type {
  RuleResponse,
  RuleCreate,
  RuleUpdate,
  RuleType,
  RuleIntent,
  RuleAuthority,
} from "@/app/admin/proposal-review/interfaces";
import {
  RULE_TYPE_LABELS,
  RULE_INTENT_LABELS,
  RULE_AUTHORITY_LABELS,
} from "@/app/admin/proposal-review/interfaces";

interface RuleEditorProps {
  open: boolean;
  onClose: () => void;
  onSave: (rule: RuleCreate | RuleUpdate) => Promise<void>;
  existingRule?: RuleResponse | null;
}

interface RuleFormValues {
  name: string;
  description: string;
  category: string;
  rule_type: RuleType;
  rule_intent: RuleIntent;
  authority: RuleAuthority | "none";
  is_hard_stop: string;
  prompt_template: string;
}

function RuleEditor({ open, onClose, onSave, existingRule }: RuleEditorProps) {
  if (!open) return null;

  const initialValues: RuleFormValues = existingRule
    ? {
        name: existingRule.name,
        description: existingRule.description || "",
        category: existingRule.category || "",
        rule_type: existingRule.rule_type,
        rule_intent: existingRule.rule_intent,
        authority: existingRule.authority || "none",
        is_hard_stop: existingRule.is_hard_stop ? "yes" : "no",
        prompt_template: existingRule.prompt_template,
      }
    : {
        name: "",
        description: "",
        category: "",
        rule_type: "DOCUMENT_CHECK" as RuleType,
        rule_intent: "CHECK" as RuleIntent,
        authority: "none" as const,
        is_hard_stop: "no",
        prompt_template: "",
      };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          icon={existingRule ? SvgEdit : SvgPlus}
          title={existingRule ? "Edit Rule" : "Add Rule"}
          description={
            existingRule
              ? "Update the rule configuration."
              : "Define a new rule for this ruleset."
          }
          onClose={onClose}
        />

        <Formik
          initialValues={initialValues}
          onSubmit={async (values, { setSubmitting }) => {
            setSubmitting(true);
            try {
              const ruleData = {
                name: values.name.trim(),
                description: values.description.trim() || undefined,
                category: values.category.trim() || undefined,
                rule_type: values.rule_type,
                rule_intent: values.rule_intent,
                prompt_template: values.prompt_template,
                authority:
                  values.authority === "none"
                    ? null
                    : (values.authority as RuleAuthority),
                is_hard_stop: values.is_hard_stop === "yes",
              };
              await onSave(ruleData);
              onClose();
            } catch (err) {
              toast.error(
                err instanceof Error ? err.message : "Failed to save rule"
              );
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, values }) => (
            <Form className="w-full overflow-visible">
              <Modal.Body>
                <VerticalInput
                  name="name"
                  title="Name"
                  nonInteractive
                  sizePreset="main-ui"
                >
                  <FormikField<string>
                    name="name"
                    render={(field, helper) => (
                      <InputTypeIn
                        {...field}
                        placeholder="Rule name"
                        onClear={() => helper.setValue("")}
                        showClearButton={false}
                      />
                    )}
                  />
                </VerticalInput>

                <VerticalInput
                  name="description"
                  title="Description"
                  nonInteractive
                  sizePreset="main-ui"
                >
                  <FormikField<string>
                    name="description"
                    render={(field, helper) => (
                      <InputTypeIn
                        {...field}
                        placeholder="Brief description of what this rule checks"
                        onClear={() => helper.setValue("")}
                        showClearButton={false}
                      />
                    )}
                  />
                </VerticalInput>

                <VerticalInput
                  name="category"
                  title="Category"
                  nonInteractive
                  sizePreset="main-ui"
                >
                  <FormikField<string>
                    name="category"
                    render={(field, helper) => (
                      <InputTypeIn
                        {...field}
                        placeholder="e.g., IR-2: Regulatory Compliance"
                        onClear={() => helper.setValue("")}
                        showClearButton={false}
                      />
                    )}
                  />
                </VerticalInput>

                <div className="flex gap-4">
                  <div className="flex-1">
                    <VerticalInput
                      name="rule_type"
                      title="Rule Type"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="rule_type"
                        render={(field, helper) => (
                          <InputSelect
                            value={field.value}
                            onValueChange={(v) => helper.setValue(v)}
                          >
                            <InputSelect.Trigger placeholder="Select type" />
                            <InputSelect.Content>
                              {Object.entries(RULE_TYPE_LABELS).map(
                                ([key, label]) => (
                                  <InputSelect.Item key={key} value={key}>
                                    {label}
                                  </InputSelect.Item>
                                )
                              )}
                            </InputSelect.Content>
                          </InputSelect>
                        )}
                      />
                    </VerticalInput>
                  </div>

                  <div className="flex-1">
                    <VerticalInput
                      name="rule_intent"
                      title="Intent"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="rule_intent"
                        render={(field, helper) => (
                          <InputSelect
                            value={field.value}
                            onValueChange={(v) => helper.setValue(v)}
                          >
                            <InputSelect.Trigger placeholder="Select intent" />
                            <InputSelect.Content>
                              {Object.entries(RULE_INTENT_LABELS).map(
                                ([key, label]) => (
                                  <InputSelect.Item key={key} value={key}>
                                    {label}
                                  </InputSelect.Item>
                                )
                              )}
                            </InputSelect.Content>
                          </InputSelect>
                        )}
                      />
                    </VerticalInput>
                  </div>
                </div>

                <div className="flex gap-4">
                  <div className="flex-1">
                    <VerticalInput
                      name="authority"
                      title="Authority"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="authority"
                        render={(field, helper) => (
                          <InputSelect
                            value={field.value}
                            onValueChange={(v) => helper.setValue(v)}
                          >
                            <InputSelect.Trigger placeholder="Select authority" />
                            <InputSelect.Content>
                              <InputSelect.Item value="none">
                                None
                              </InputSelect.Item>
                              {Object.entries(RULE_AUTHORITY_LABELS).map(
                                ([key, label]) => (
                                  <InputSelect.Item key={key} value={key}>
                                    {label}
                                  </InputSelect.Item>
                                )
                              )}
                            </InputSelect.Content>
                          </InputSelect>
                        )}
                      />
                    </VerticalInput>
                  </div>

                  <div className="flex-1">
                    <VerticalInput
                      name="is_hard_stop"
                      title="Hard Stop"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="is_hard_stop"
                        render={(field, helper) => (
                          <InputSelect
                            value={field.value}
                            onValueChange={(v) => helper.setValue(v)}
                          >
                            <InputSelect.Trigger />
                            <InputSelect.Content>
                              <InputSelect.Item value="no">No</InputSelect.Item>
                              <InputSelect.Item value="yes">
                                Yes - Fail stops entire review
                              </InputSelect.Item>
                            </InputSelect.Content>
                          </InputSelect>
                        )}
                      />
                    </VerticalInput>
                  </div>
                </div>

                <VerticalInput
                  name="prompt_template"
                  title="Prompt Template"
                  nonInteractive
                  sizePreset="main-ui"
                >
                  <Text font="secondary-body" color="text-04">
                    {
                      "Available variables: {{proposal_text}}, {{metadata}}, {{foa_text}}"
                    }
                  </Text>
                  <FormikField<string>
                    name="prompt_template"
                    render={(field, helper) => (
                      <InputTextArea
                        value={field.value}
                        onChange={(e) => helper.setValue(e.target.value)}
                        placeholder="Enter the LLM prompt template for evaluating this rule..."
                        rows={8}
                      />
                    )}
                  />
                </VerticalInput>
              </Modal.Body>

              <Modal.Footer>
                <Button
                  prominence="secondary"
                  type="button"
                  onClick={onClose}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={
                    isSubmitting ||
                    !values.name.trim() ||
                    !values.prompt_template.trim()
                  }
                >
                  {isSubmitting
                    ? "Saving..."
                    : existingRule
                      ? "Update Rule"
                      : "Add Rule"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}

export default RuleEditor;
