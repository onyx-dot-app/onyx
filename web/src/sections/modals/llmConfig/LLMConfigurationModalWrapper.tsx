import { ReactNode } from "react";
import { Form } from "formik";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import SvgOnyxLogo from "@opal/icons/onyx-logo";
import {
  getProviderIcon,
  getProviderDisplayName,
  getProviderProductName,
} from "@/lib/llmConfig/providers";
import { Section } from "@/layouts/general-layouts";

interface LLMConfigurationModalWrapperProps {
  providerEndpoint: string;
  providerName?: string;
  existingProviderName?: string;
  onClose: () => void;
  isFormValid: boolean;
  isTesting?: boolean;
  children: ReactNode;
}

export function LLMConfigurationModalWrapper({
  providerEndpoint,
  providerName,
  existingProviderName,
  onClose,
  isFormValid,
  isTesting,
  children,
}: LLMConfigurationModalWrapperProps) {
  const providerIcon = getProviderIcon(providerEndpoint);
  const providerDisplayName =
    providerName ?? getProviderDisplayName(providerEndpoint);
  const providerProductName = getProviderProductName(providerEndpoint);

  const title = existingProviderName
    ? `Configure "${existingProviderName}"`
    : `Set up ${providerProductName}`;
  const description = `Connect to ${providerDisplayName} and set up your ${providerProductName} models.`;

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content height="lg">
        <Form className="flex flex-col h-full min-h-0">
          <Modal.Header
            icon={providerIcon}
            moreIcon1={SvgArrowExchange}
            moreIcon2={SvgOnyxLogo}
            title={title}
            description={description}
            onClose={onClose}
          />
          <Modal.Body>
            <Section alignItems="start">{children}</Section>
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button type="submit" disabled={!isFormValid || isTesting}>
              {isTesting ? "Connecting..." : "Connect"}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}
