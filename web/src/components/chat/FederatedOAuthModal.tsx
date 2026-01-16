"use client";

import { useContext, useState } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { getSourceMetadata } from "@/lib/sources";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import { SvgLink } from "@opal/icons";
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

      if (newSkipCount >= MAX_SKIP_COUNT) {
        // Permanently hide the modal after max skips
        const skipData = {
          skipCount: newSkipCount,
          hideUntil: 0,
          permanentlyHidden: true,
        };

        localStorage.setItem(
          "federatedOAuthModalSkipData",
          JSON.stringify(skipData)
        );

        setOAuthModalState({
          hidden: true,
          skipCount: newSkipCount,
        });
      } else {
        // Hide for 1 hour after first skip
        const oneHourFromNow = Date.now() + 60 * 60 * 1000;

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

  return {
    oAuthModalState,
    handleOAuthModalSkip,
  };
}

export default function FederatedOAuthModal() {
  const settings = useContext(SettingsContext);
  const router = useRouter();

  const {
    oAuthModalState: { hidden },
    handleOAuthModalSkip,
  } = useFederatedOauthModal();

  const { connectors: federatedConnectors, hasUnauthenticatedConnectors } =
    useFederatedOAuthStatus();

  const needsAuth = federatedConnectors.filter((c) => !c.has_oauth_token);

  if (needsAuth.length === 0 || hidden || !hasUnauthenticatedConnectors) {
    return null;
  }

  const handleAuthorize = (authorizeUrl: string) => {
    // Redirect to OAuth URL in the same window
    router.push(authorizeUrl as Route);
  };

  const applicationName =
    settings?.enterpriseSettings?.application_name || "Onyx";

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header
          icon={SvgLink}
          title="Connect Your Apps"
          description={`Improve answer quality by letting ${applicationName} search all your connected data.`}
        />
        <Modal.Body>
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
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleOAuthModalSkip} className="w-full">
            Skip for now
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
