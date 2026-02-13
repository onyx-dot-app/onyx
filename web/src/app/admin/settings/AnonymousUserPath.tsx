"use client";

import useSWR from "swr";
import { useContext, useState } from "react";

import { PopupSpec } from "@/components/admin/connectors/Popup";
import Button from "@/refresh-components/buttons/Button";
import { SettingsContext } from "@/providers/SettingsProvider";
import { Card } from "@/refresh-components/cards";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import * as GeneralLayouts from "@/layouts/general-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

export function AnonymousUserPath({
  setPopup,
}: {
  setPopup: (popup: PopupSpec) => void;
}) {
  const settings = useContext(SettingsContext);
  const [customPath, setCustomPath] = useState<string | null>(null);

  const {
    data: anonymousUserPath,
    error,
    mutate,
    isLoading,
  } = useSWR("/api/tenants/anonymous-user-path", (url) =>
    fetch(url)
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        return data.anonymous_user_path;
      })
  );

  if (error) {
    console.error("Failed to fetch anonymous user path:", error);
  }

  async function handleCustomPathUpdate() {
    try {
      // Validate custom path
      if (!customPath || !customPath.trim()) {
        setPopup({
          message: "Custom path cannot be empty",
          type: "error",
        });
        return;
      }

      if (!/^[a-zA-Z0-9-]+$/.test(customPath)) {
        setPopup({
          message: "Custom path can only contain letters, numbers, and hyphens",
          type: "error",
        });
        return;
      }
      const response = await fetch(
        `/api/tenants/anonymous-user-path?anonymous_user_path=${encodeURIComponent(
          customPath
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
      if (!response.ok) {
        const detail = await response.json();
        setPopup({
          message: detail.detail || "Failed to update anonymous user path",
          type: "error",
        });
        return;
      }
      mutate(); // Revalidate the SWR cache
      setPopup({
        message: "Anonymous user path updated successfully!",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: `Failed to update anonymous user path: ${error}`,
        type: "error",
      });
      console.error("Error updating anonymous user path:", error);
    }
  }

  return (
    <div className="max-w-xl">
      <Card gap={0}>
        <GeneralLayouts.Section alignItems="start" gap={0.5}>
          <Text headingH3>Anonymous User Access</Text>
          <Text secondaryBody text03>
            Enable this to allow anonymous users to access all public connectors
            in your workspace. Anonymous users will not be able to access
            private or restricted content.
          </Text>
        </GeneralLayouts.Section>

        {isLoading ? (
          <SimpleLoader className="self-center animate-spin mt-4" />
        ) : (
          <>
            <GeneralLayouts.Section flexDirection="row" gap={0.5}>
              <Text mainContentBody text03>
                {settings?.webDomain}/anonymous/
              </Text>
              <InputTypeIn
                placeholder="your-custom-path"
                value={customPath ?? anonymousUserPath ?? ""}
                onChange={(e) => setCustomPath(e.target.value)}
                showClearButton={false}
              />
            </GeneralLayouts.Section>

            <GeneralLayouts.Section
              flexDirection="row"
              gap={0.5}
              justifyContent="start"
            >
              <Button onClick={handleCustomPathUpdate}>Update Path</Button>
              <CopyIconButton
                getCopyText={() =>
                  `${settings?.webDomain}/anonymous/${anonymousUserPath ?? ""}`
                }
                tooltip="Copy invite link"
                prominence="secondary"
              />
            </GeneralLayouts.Section>
          </>
        )}
      </Card>
    </div>
  );
}
