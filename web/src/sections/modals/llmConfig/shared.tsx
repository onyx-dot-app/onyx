import { ReactNode } from "react";
import { Form } from "formik";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
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
  testError?: string;
  children: ReactNode;
}

export function LLMConfigurationModalWrapper({
  providerEndpoint,
  providerName,
  existingProviderName,
  onClose,
  isFormValid,
  isTesting,
  testError,
  children,
}: LLMConfigurationModalWrapperProps) {
  const providerIcon = getProviderIcon(providerEndpoint);
  const providerDisplayName =
    providerName ?? getProviderDisplayName(providerEndpoint);
  const providerProductName = getProviderProductName(providerEndpoint);

  const title = existingProviderName
    ? `Configure "${existingProviderName}"`
    : `Set up ${providerDisplayName}`;
  const description = `Connect to ${providerDisplayName} and set up your ${providerProductName} models.`;

  return (
    <Form>
      <Modal.Header
        icon={providerIcon}
        moreIcon1={SvgArrowExchange}
        moreIcon2={SvgOnyxLogo}
        title={title}
        description={description}
        onClose={onClose}
      />
      <Modal.Body>{children}</Modal.Body>
      {testError && (
        <Text as="p" className="text-status-error-05 px-4">
          {testError}
        </Text>
      )}
      <Modal.Footer>
        <Button prominence="secondary" onClick={onClose} type="button">
          Cancel
        </Button>
        <Button type="submit" disabled={!isFormValid || isTesting}>
          {isTesting ? "Connecting..." : "Connect"}
        </Button>
      </Modal.Footer>
    </Form>
  );
}
