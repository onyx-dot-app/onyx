"use client";

import React from "react";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import { LoadingAnimation } from "@/components/Loading";
import type { IconProps } from "@opal/types";

/**
 * LLMFormLayout - A compound component for LLM provider configuration forms
 *
 * Provides a complete modal form structure with:
 * - Modal: The modal wrapper with header (icon, title, close button)
 * - Body: Form content area
 * - Footer: Cancel and Connect/Update buttons
 *
 * @example
 * ```tsx
 * <LLMFormLayout.Modal
 *   icon={OpenAIIcon}
 *   displayName="OpenAI"
 *   providerName="openai"
 *   onClose={handleClose}
 *   isEditing={false}
 * >
 *   <Formik ...>
 *     {(formikProps) => (
 *       <Form>
 *         <LLMFormLayout.Body>
 *           <InputField name="api_key" label="API Key" />
 *         </LLMFormLayout.Body>
 *         <LLMFormLayout.Footer
 *           onCancel={handleClose}
 *           isSubmitting={isSubmitting}
 *         />
 *       </Form>
 *     )}
 *   </Formik>
 * </LLMFormLayout.Modal>
 * ```
 */

// ============================================================================
// Modal (Root)
// ============================================================================

interface LLMFormModalProps {
  children: React.ReactNode;
  /** Icon component for the provider */
  icon: React.FunctionComponent<IconProps>;
  /** Display name shown in the modal title */
  displayName: string;
  /** Whether editing an existing provider (changes title) */
  isEditing?: boolean;
  /** Custom name of the existing provider (shown in title when editing) */
  existingName?: string;
  /** Handler for closing the modal */
  onClose: () => void;
}

function LLMFormModal({
  children,
  icon: Icon,
  displayName,
  isEditing = false,
  existingName,
  onClose,
}: LLMFormModalProps) {
  const title = isEditing
    ? `Configure ${existingName ? `"${existingName}"` : displayName}`
    : `Setup up ${displayName}`;

  const description = isEditing
    ? ""
    : `Connect to  ${displayName}  to set up your ${displayName} models.`;

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md-sm">
        <Modal.Header
          icon={Icon}
          title={title}
          description={description}
          onClose={onClose}
        />
        <Modal.Body alignItems="stretch">{children}</Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

// ============================================================================
// Body
// ============================================================================

interface LLMFormBodyProps {
  children: React.ReactNode;
}

function LLMFormBody({ children }: LLMFormBodyProps) {
  return <>{children}</>;
}

// ============================================================================
// Footer
// ============================================================================

interface LLMFormFooterProps {
  /** Handler for cancel button */
  onCancel: () => void;
  /** Label for the cancel button. Default: "Cancel" */
  cancelLabel?: string;
  /** Label for the submit button. Default: "Connect" */
  submitLabel?: string;
  /** Text to show while submitting. Default: "Testing" */
  submittingLabel?: string;
  /** Whether the form is currently submitting */
  isSubmitting?: boolean;
  /** Whether the submit button should be disabled */
  isSubmitDisabled?: boolean;
  /** Optional left-side content (e.g., delete button) */
  leftChildren?: React.ReactNode;
  /** Error message to display */
  error?: string;
}

function LLMFormFooter({
  onCancel,
  cancelLabel = "Cancel",
  submitLabel = "Connect",
  submittingLabel = "Testing",
  isSubmitting = false,
  isSubmitDisabled = false,
  leftChildren,
  error,
}: LLMFormFooterProps) {
  return (
    <Section alignItems="stretch" gap={0.5}>
      {error && (
        <Text as="p" className="text-error">
          {error}
        </Text>
      )}
      <Section flexDirection="row" justifyContent="between" gap={0.5}>
        <Section
          width="fit"
          flexDirection="row"
          justifyContent="start"
          gap={0.5}
        >
          {leftChildren}
        </Section>
        <Section width="fit" flexDirection="row" justifyContent="end" gap={0.5}>
          <Button secondary onClick={onCancel} disabled={isSubmitting}>
            {cancelLabel}
          </Button>
          <Button type="submit" disabled={isSubmitting || isSubmitDisabled}>
            {isSubmitting ? (
              <Text as="span" inverted>
                <LoadingAnimation text={submittingLabel} />
              </Text>
            ) : (
              submitLabel
            )}
          </Button>
        </Section>
      </Section>
    </Section>
  );
}

// ============================================================================
// Export
// ============================================================================

const LLMFormLayout = {
  Modal: LLMFormModal,
  Body: LLMFormBody,
  Footer: LLMFormFooter,
};

export default LLMFormLayout;
