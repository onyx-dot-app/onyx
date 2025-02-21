"use client";

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
          message: "Custom path cannot be empty",
          type: "error",
        });
        return;
      }
      // Validate custom path
      if (!customPath.trim()) {
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
    <div className="mt-4 ml-6 max-w-xl p-6 bg-white shadow-lg border border-background-200 rounded-lg">
      <h4 className="font-semibold text-lg text-text-800 mb-3">
        Anonymous User Access
      </h4>
      <p className="text-text-600 text-sm mb-4">
        Enable this to allow non-authenticated users to access all documents
        indexed by public connectors in your workspace.
        {anonymousUserPath
          ? "Customize the access path for anonymous users."
          : "Set a custom access path for anonymous users."}{" "}
        Anonymous users will only be able to view and search public documents,
        but cannot access private or restricted content. The path will always
        start with &quot;/anonymous/&quot;.
      </p>
      {isLoading ? (
        <ThreeDotsLoader />
      ) : (
        <div className="flex flex-col gap-2 justify-center items-start">
          <div className="w-full flex-grow  flex items-center rounded-md shadow-sm">
            <span className="inline-flex items-center rounded-l-md border border-r-0 border-background-300 bg-background-50 px-3 text-text-500 sm:text-sm h-10">
              {settings?.webDomain}/anonymous/
            </span>
            <Input
              type="text"
              className="block w-full flex-grow flex-1 rounded-none rounded-r-md border-background-300 focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm h-10"
              placeholder="your-custom-path"
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
              Update Path
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
                  message: "Invite link copied!",
                  type: "success",
                });
              }}
            >
              <ClipboardIcon className="h-4 w-4" />
              Copy
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
