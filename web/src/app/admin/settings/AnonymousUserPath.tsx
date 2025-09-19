"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";

import useSWR from "swr";
import { useContext, useState } from "react";

import { PopupSpec } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import { ClipboardIcon } from "@/components/icons/icons";
import { Input } from "@/components/ui/input";
import { ThreeDotsLoader } from "@/components/Loading";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export function AnonymousUserPath({
  setPopup,
}: {
  setPopup: (popup: PopupSpec) => void;
}) {
  const { t } = useTranslation();
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
      if (!customPath) {
        setPopup({
          message: t(k.CUSTOM_PATH_CANNOT_BE_EMPTY),
          type: "error",
        });
        return;
      }
      // Validate custom path
      if (!customPath.trim()) {
        setPopup({
          message: t(k.CUSTOM_PATH_CANNOT_BE_EMPTY),
          type: "error",
        });
        return;
      }

      if (!/^[a-zA-Z0-9-]+$/.test(customPath)) {
        setPopup({
          message: t(k.CUSTOM_PATH_CAN_ONLY_CONTAIN_L),
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
          message: detail.detail || t(k.FAILED_TO_UPDATE_ANONYMOUS_PATH),
          type: "error",
        });
        return;
      }
      mutate(); // Revalidate the SWR cache
      setPopup({
        message: t(k.ANONYMOUS_USER_PATH_UPDATED_SU),
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: `${t(k.FAILED_TO_UPDATE_ANONYMOUS_PATH)} ${error}`,
        type: "error",
      });
      console.error("Error updating anonymous user path:", error);
    }
  }

  return (
    <div className="mt-4 ml-6 max-w-xl p-6 bg-white shadow-lg border border-background-200 rounded-lg">
      <h4 className="font-semibold text-lg text-text-800 mb-3">
        {t(k.ANONYMOUS_USER_ACCESS)}
      </h4>
      <p className="text-text-600 text-sm mb-4">
        {t(k.ENABLE_THIS_TO_ALLOW_NON_AUTHE)}
        {anonymousUserPath
          ? t(k.CUSTOMIZE_THE_ACCESS_PATH_FOR)
          : t(k.SET_A_CUSTOM_ACCESS_PATH_FOR_A)}{" "}
        {t(k.ANONYMOUS_USERS_WILL_ONLY_BE_A)}
      </p>
      {isLoading ? (
        <ThreeDotsLoader />
      ) : (
        <div className="flex flex-col gap-2 justify-center items-start">
          <div className="w-full flex-grow  flex items-center rounded-md shadow-sm">
            <span className="inline-flex items-center rounded-l-md border border-r-0 border-background-300 bg-background-50 px-3 text-text-500 sm:text-sm h-10">
              {settings?.webDomain}
              {t(k.ANONYMOUS)}
            </span>
            <Input
              type="text"
              className="block w-full flex-grow flex-1 rounded-none rounded-r-md border-background-300 focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm h-10"
              placeholder={t(k.YOUR_PATH_PLACEHOLDER)}
              value={customPath ?? anonymousUserPath ?? ""}
              onChange={(e) => setCustomPath(e.target.value)}
            />
          </div>
          <div className="flex flex-row gap-2">
            <Button
              onClick={handleCustomPathUpdate}
              variant="default"
              size="sm"
              className="h-10 px-4"
            >
              {t(k.UPDATE_PATH)}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-10 px-4"
              onClick={() => {
                navigator.clipboard.writeText(
                  `${settings?.webDomain}/anonymous/${anonymousUserPath}`
                );
                setPopup({
                  message: t(k.INVITE_LINK_COPIED),
                  type: "success",
                });
              }}
            >
              <ClipboardIcon className="h-4 w-4" />
              {t(k.COPY)}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
