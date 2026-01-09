"use client";

import { memo, useMemo, type ReactNode, type FunctionComponent } from "react";

import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";

import { SvgArrowExchange, SvgOnyxLogo } from "@opal/icons";
import type { IconProps } from "@opal/types";

export type WebProviderSetupModalProps = {
  isOpen: boolean;
  onClose: () => void;
  providerLabel: string;
  providerLogo: ReactNode;
  description: string;
  apiKeyValue: string;
  onApiKeyChange: (value: string) => void;
  optionalField?: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    description?: ReactNode;
    showFirst?: boolean;
  };
  helperMessage: ReactNode;
  helperClass: string;
  isProcessing: boolean;
  canConnect: boolean;
  onConnect: () => void;
  apiKeyAutoFocus?: boolean;
  hideApiKey?: boolean;
};

export const WebProviderSetupModal = memo(
  ({
    isOpen,
    onClose,
    providerLabel,
    providerLogo,
    description,
    apiKeyValue,
    onApiKeyChange,
    optionalField,
    helperMessage,
    helperClass,
    isProcessing,
    canConnect,
    onConnect,
    apiKeyAutoFocus = true,
    hideApiKey = false,
  }: WebProviderSetupModalProps) => {
    const LogoArrangement = useMemo(() => {
      const Component: FunctionComponent<IconProps> = () => (
        <div className="flex items-center gap-1">
          {providerLogo}
          <div className="flex items-center justify-center size-4 p-0.5 shrink-0">
            <SvgArrowExchange className="size-3 text-text-04" />
          </div>
          <div className="flex items-center justify-center size-7 p-0.5 shrink-0 overflow-clip">
            <SvgOnyxLogo
              width={24}
              height={24}
              className="text-text-04 shrink-0"
            />
          </div>
        </div>
      );
      return Component;
    }, [providerLogo]);

    return (
      <Modal open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <Modal.Content mini preventAccidentalClose>
          <Modal.Header
            icon={LogoArrangement}
            title={`Set up ${providerLabel}`}
            description={description}
            onClose={onClose}
          />
          <Modal.Body>
            {optionalField?.showFirst && (
              <FormField
                name={optionalField.label.toLowerCase().replace(/\s+/g, "_")}
                state="idle"
                className="w-full"
              >
                <FormField.Label>{optionalField.label}</FormField.Label>
                <FormField.Control asChild>
                  <InputTypeIn
                    placeholder={optionalField.placeholder}
                    value={optionalField.value}
                    onChange={(event) =>
                      optionalField.onChange(event.target.value)
                    }
                  />
                </FormField.Control>
                {optionalField.description && (
                  <FormField.Description>
                    {optionalField.description}
                  </FormField.Description>
                )}
              </FormField>
            )}

            {!hideApiKey && (
              <FormField
                name="api_key"
                state={
                  helperClass.includes("status-error") ||
                  helperClass.includes("error")
                    ? "error"
                    : helperClass.includes("green")
                      ? "success"
                      : "idle"
                }
                className="w-full"
              >
                <FormField.Label>API Key</FormField.Label>
                <FormField.Control asChild>
                  <PasswordInputTypeIn
                    placeholder="Enter API key"
                    value={apiKeyValue}
                    autoFocus={apiKeyAutoFocus}
                    onFocus={(e) => {
                      if (apiKeyValue === "••••••••••••••••") {
                        e.target.select();
                      }
                    }}
                    onChange={(event) => onApiKeyChange(event.target.value)}
                    showClearButton={false}
                  />
                </FormField.Control>
                {isProcessing ? (
                  <FormField.APIMessage
                    state="loading"
                    messages={{
                      loading:
                        typeof helperMessage === "string"
                          ? helperMessage
                          : "Validating API key...",
                    }}
                  />
                ) : typeof helperMessage === "string" ? (
                  <FormField.Message
                    messages={{
                      idle:
                        helperClass.includes("status-error") ||
                        helperClass.includes("error")
                          ? ""
                          : helperClass.includes("green")
                            ? ""
                            : helperMessage,
                      error:
                        helperClass.includes("status-error") ||
                        helperClass.includes("error")
                          ? helperMessage
                          : "",
                      success: helperClass.includes("green")
                        ? helperMessage
                        : "",
                    }}
                  />
                ) : (
                  <FormField.Description className={helperClass}>
                    {helperMessage}
                  </FormField.Description>
                )}
              </FormField>
            )}

            {optionalField && !optionalField.showFirst && (
              <FormField
                name={optionalField.label.toLowerCase().replace(/\s+/g, "_")}
                state={
                  hideApiKey &&
                  (helperClass.includes("status-error") ||
                    helperClass.includes("error"))
                    ? "error"
                    : "idle"
                }
                className="w-full"
              >
                <FormField.Label>{optionalField.label}</FormField.Label>
                <FormField.Control asChild>
                  <InputTypeIn
                    placeholder={optionalField.placeholder}
                    value={optionalField.value}
                    onChange={(event) =>
                      optionalField.onChange(event.target.value)
                    }
                  />
                </FormField.Control>
                {optionalField.description && (
                  <FormField.Description>
                    {optionalField.description}
                  </FormField.Description>
                )}

                {hideApiKey && (
                  <>
                    {isProcessing ? (
                      <FormField.APIMessage
                        state="loading"
                        messages={{
                          loading:
                            typeof helperMessage === "string"
                              ? helperMessage
                              : "Testing connection...",
                        }}
                      />
                    ) : typeof helperMessage === "string" ? (
                      <FormField.Message
                        messages={{
                          idle:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? ""
                              : helperClass.includes("green")
                                ? ""
                                : "",
                          error:
                            helperClass.includes("status-error") ||
                            helperClass.includes("error")
                              ? helperMessage
                              : "",
                          success: helperClass.includes("green")
                            ? helperMessage
                            : "",
                        }}
                      />
                    ) : null}
                  </>
                )}
              </FormField>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button type="button" main secondary onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              main
              primary
              disabled={!canConnect || isProcessing}
              onClick={onConnect}
            >
              {isProcessing ? "Connecting..." : "Connect"}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }
);

WebProviderSetupModal.displayName = "WebProviderSetupModal";
