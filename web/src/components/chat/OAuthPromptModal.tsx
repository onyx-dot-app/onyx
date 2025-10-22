"use client";

import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { KeyIcon } from "@/components/icons/icons";
import { initiateOAuthFlow } from "@/lib/oauth/api";
import { useState } from "react";
import { useSettingsContext } from "../settings/SettingsProvider";

interface OAuthPromptModalProps {
  oauthConfigId: number;
  oauthConfigName: string;
  providerName?: string;
  onClose: () => void;
}

export function OAuthPromptModal({
  oauthConfigId,
  oauthConfigName,
  providerName,
  onClose,
}: OAuthPromptModalProps) {
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const settings = useSettingsContext();

  const handleAuthenticate = async () => {
    try {
      setIsAuthenticating(true);
      setError(null);
      // Get current path to return to after OAuth flow
      const currentPath = window.location.pathname + window.location.search;
      await initiateOAuthFlow(oauthConfigId, currentPath);
      // initiateOAuthFlow will redirect to OAuth provider
    } catch (err: any) {
      setIsAuthenticating(false);
      setError(err.message || "Failed to initiate authentication");
    }
  };

  const applicationName =
    settings?.enterpriseSettings?.application_name || "Onyx";

  return (
    <Modal
      title="Authentication Required"
      onOutsideClick={onClose}
      width="w-[500px]"
      icon={KeyIcon}
    >
      <div className="space-y-4">
        <Text>
          This tool requires authentication with{" "}
          <span className="font-semibold">
            {providerName || oauthConfigName}
          </span>
          .
        </Text>

        <Text className="text-sm text-subtle">
          To use this tool, you need to authorize {applicationName} to access
          your account. You&apos;ll be redirected to the provider&apos;s login
          page to complete the authentication process.
        </Text>

        {error && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <Text className="text-sm text-red-800 dark:text-red-200">
              {error}
            </Text>
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <Button
            onClick={handleAuthenticate}
            disabled={isAuthenticating}
            primary
            className="flex-1"
          >
            {isAuthenticating ? "Redirecting..." : "Authenticate"}
          </Button>
          <Button
            onClick={onClose}
            disabled={isAuthenticating}
            danger
            className="flex-1"
          >
            Cancel
          </Button>
        </div>
      </div>
    </Modal>
  );
}
