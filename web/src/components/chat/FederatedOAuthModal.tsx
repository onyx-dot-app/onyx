"use client";

import React, { useContext } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export interface FederatedConnectorOAuthStatus {
  federated_connector_id: number;
  source: string;
  name: string;
  has_oauth_token: boolean;
  oauth_token_expires_at?: string;
  authorize_url?: string;
}

interface FederatedOAuthModalProps {
  connectors: FederatedConnectorOAuthStatus[];
  onClose: () => void;
  onSkip?: () => void;
}

export function FederatedOAuthModal({
  connectors,
  onClose,
  onSkip,
}: FederatedOAuthModalProps) {
  const settings = useContext(SettingsContext);
  const needsAuth = connectors.filter((c) => !c.has_oauth_token);

  if (needsAuth.length === 0) {
    return null;
  }

  const handleAuthorize = (authorizeUrl: string) => {
    // Open OAuth URL in a popup window
    const popup = window.open(
      authorizeUrl,
      "oauth",
      "width=600,height=700,scrollbars=yes,resizable=yes"
    );

    // Listen for the popup to close (OAuth completion)
    const checkClosed = setInterval(() => {
      if (popup?.closed) {
        clearInterval(checkClosed);
        // Reload the page to refresh OAuth status
        window.location.reload();
      }
    }, 1000);
  };

  const applicationName =
    settings?.enterpriseSettings?.application_name || "Onyx";

  return (
    <Modal onOutsideClick={onClose} hideCloseButton={true}>
      <div className="space-y-4 mt-4">
        <p className="text-sm text-muted-foreground">
          Connect your apps to make {applicationName} smarter.
        </p>

        <div className="space-y-3">
          {needsAuth.map((connector) => (
            <div
              key={connector.federated_connector_id}
              className="flex items-center justify-between p-3 rounded-lg border border-border"
            >
              <div className="flex items-center gap-3">
                <SourceIcon
                  sourceType={
                    connector.source
                      .toLowerCase()
                      .replace("federated_", "") as ValidSources
                  }
                  iconSize={20}
                />
                <span className="font-medium">{connector.name}</span>
              </div>
              <Button
                size="sm"
                onClick={() => {
                  if (connector.authorize_url) {
                    handleAuthorize(connector.authorize_url);
                  }
                }}
                disabled={!connector.authorize_url}
              >
                Connect
              </Button>
            </div>
          ))}
        </div>

        <div className="flex justify-end pt-2">
          <Button variant="outline" onClick={onSkip || onClose}>
            Skip
          </Button>
        </div>
      </div>
    </Modal>
  );
}
