"use client";

import React, { useContext } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { getSourceMetadata } from "@/lib/sources";
import { useRouter } from "next/navigation";

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
  onSkip: () => void;
  skipCount?: number;
}

const MAX_SKIP_COUNT = 2;

export function FederatedOAuthModal({
  connectors,
  onSkip,
  skipCount = 0,
}: FederatedOAuthModalProps) {
  const settings = useContext(SettingsContext);
  const needsAuth = connectors.filter((c) => !c.has_oauth_token);
  const router = useRouter();

  if (needsAuth.length === 0) {
    return null;
  }

  const handleAuthorize = (authorizeUrl: string) => {
    // Redirect to OAuth URL in the same window
    router.push(authorizeUrl);
  };

  const applicationName =
    settings?.enterpriseSettings?.application_name || "Onyx";

  if (skipCount >= MAX_SKIP_COUNT) {
    return (
      <Modal
        onOutsideClick={() => {}}
        hideCloseButton={true}
        width="w-full max-w-xl"
      >
        <div className="space-y-4 mt-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold mb-2">Heads Up!</h3>
            <p className="text-sm text-muted-foreground">
              You can always connect your apps later by going to the{" "}
              <strong>User Settings</strong> menu (click your profile icon) and
              selecting <strong>Connectors</strong>.
            </p>
          </div>

          <div className="flex justify-center pt-2">
            <Button onClick={onSkip}>Got it</Button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal hideCloseButton={true} width="w-full max-w-xl">
      <div className="space-y-4 mt-4">
        <p className="text-sm text-muted-foreground">
          Improve answer quality by letting {applicationName} search all your
          connected data.
        </p>

        <div className="space-y-3">
          {needsAuth.map((connector) => {
            const sourceMetadata = getSourceMetadata(
              connector.source as ValidSources
            );

            return (
              <div
                key={connector.federated_connector_id}
                className="flex items-center justify-between p-3 rounded-lg border border-border"
              >
                <div className="flex items-center gap-3">
                  <SourceIcon
                    sourceType={sourceMetadata.internalName}
                    iconSize={20}
                  />
                  <span className="font-medium">
                    {sourceMetadata.displayName}
                  </span>
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
            );
          })}
        </div>

        {/* Add visual separation and center modal actions */}
        <div className="pt-4 mt-2">
          <div className="flex justify-center gap-3">
            <Button variant="outline" onClick={onSkip}>
              Skip for now
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
