"use client";

import React, { useContext, useState } from "react";
import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { getSourceMetadata } from "@/lib/sources";
import { useRouter } from "next/navigation";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import Text from "@/refresh-components/texts/Text";

export interface FederatedConnectorOAuthStatus {
  federated_connector_id: number;
  source: string;
  name: string;
  has_oauth_token: boolean;
  oauth_token_expires_at?: string;
  authorize_url?: string;
}

const MAX_SKIP_COUNT = 2;

function useFederatedOauthModal() {
  // Check localStorage for previous skip preference and count
  const [oAuthModalState, setOAuthModalState] = useState<{
    hidden: boolean;
    skipCount: number;
  }>(() => {
    if (typeof window !== "undefined") {
      const skipData = localStorage.getItem("federatedOAuthModalSkipData");
      if (skipData) {
        try {
          const parsed = JSON.parse(skipData);
          // Check if we're still within the hide duration (1 hour)
          const now = Date.now();
          const hideUntil = parsed.hideUntil || 0;
          const isWithinHideDuration = now < hideUntil;

          return {
            hidden: parsed.permanentlyHidden || isWithinHideDuration,
            skipCount: parsed.skipCount || 0,
          };
        } catch {
          return { hidden: false, skipCount: 0 };
        }
      }
    }
    return { hidden: false, skipCount: 0 };
  });

  const handleOAuthModalSkip = () => {
    if (typeof window !== "undefined") {
      const newSkipCount = oAuthModalState.skipCount + 1;

      // If we've reached the max skip count, show the "No problem!" modal first
      if (newSkipCount >= MAX_SKIP_COUNT) {
        // Don't hide immediately - let the "No problem!" modal show
        setOAuthModalState({
          hidden: false,
          skipCount: newSkipCount,
        });
      } else {
        // For first skip, hide after a delay to show "No problem!" modal
        const oneHourFromNow = Date.now() + 60 * 60 * 1000; // 1 hour in milliseconds

        const skipData = {
          skipCount: newSkipCount,
          hideUntil: oneHourFromNow,
          permanentlyHidden: false,
        };

        localStorage.setItem(
          "federatedOAuthModalSkipData",
          JSON.stringify(skipData)
        );

        setOAuthModalState({
          hidden: true,
          skipCount: newSkipCount,
        });
      }
    }
  };

  // Handle the final dismissal of the "No problem!" modal
  const handleOAuthModalFinalDismiss = () => {
    if (typeof window !== "undefined") {
      const oneHourFromNow = Date.now() + 60 * 60 * 1000; // 1 hour in milliseconds

      const skipData = {
        skipCount: oAuthModalState.skipCount,
        hideUntil: oneHourFromNow,
        permanentlyHidden: false,
      };

      localStorage.setItem(
        "federatedOAuthModalSkipData",
        JSON.stringify(skipData)
      );

      setOAuthModalState({
        hidden: true,
        skipCount: oAuthModalState.skipCount,
      });
    }
  };

  return {
    oAuthModalState,
    handleOAuthModalSkip,
    handleOAuthModalFinalDismiss,
  };
}

export function FederatedOAuthModal() {
  const settings = useContext(SettingsContext);
  const router = useRouter();

  const {
    oAuthModalState: { skipCount, hidden },
    handleOAuthModalSkip,
    handleOAuthModalFinalDismiss,
  } = useFederatedOauthModal();

  const onSkip =
    skipCount >= MAX_SKIP_COUNT
      ? handleOAuthModalFinalDismiss
      : handleOAuthModalSkip;

  const { connectors: federatedConnectors, hasUnauthenticatedConnectors } =
    useFederatedOAuthStatus();

  const needsAuth = federatedConnectors.filter((c) => !c.has_oauth_token);

  if (needsAuth.length === 0 || hidden || !hasUnauthenticatedConnectors) {
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
            <Text headingH3>Heads Up!</Text>
            <Text>
              You can always connect your apps later by going to the{" "}
              <strong>User Settings</strong> menu (click your profile icon) and
              selecting <strong>Connectors</strong>.
            </Text>
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
        <Text>
          Improve answer quality by letting {applicationName} search all your
          connected data.
        </Text>

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
            <Button onClick={onSkip}>Skip for now</Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
