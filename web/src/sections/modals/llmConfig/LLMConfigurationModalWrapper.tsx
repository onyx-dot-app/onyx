import { ReactNode } from "react";
import { Form } from "formik";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgArrowExchange } from "@opal/icons";
import SvgOnyxLogo from "@opal/icons/onyx-logo";
import {
  getProviderIcon,
  getProviderDisplayName,
  getProviderProductName,
} from "@/lib/llmConfig/providers";

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
      <Modal.Content width="md-sm" height="lg">
        <Form className="flex flex-col h-full min-h-0">
          <Modal.Header
            icon={providerIcon}
            moreIcon1={SvgArrowExchange}
            moreIcon2={SvgOnyxLogo}
            title={title}
            description={description}
            onClose={onClose}
          />
          <Modal.Body padding={0.5}>
            <div className="py-2 w-full flex flex-col gap-4">{children}</div>
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose} type="button">
              Cancel
            </Button>
            <Disabled disabled={!isFormValid || isTesting}>
              <Button type="submit">
                {isTesting ? "Connecting..." : "Connect"}
              </Button>
            </Disabled>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}
