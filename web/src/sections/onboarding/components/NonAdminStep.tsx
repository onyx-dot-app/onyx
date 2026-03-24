"use client";

import React, { useRef, useState, useEffect } from "react";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useUser } from "@/providers/UserProvider";
import { toast } from "@/hooks/useToast";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import { cn } from "@/lib/utils";
import { SvgCheckCircle, SvgEdit, SvgUser, SvgX } from "@opal/icons";
import { ContentAction } from "@opal/layouts";

export default function NonAdminStep() {
  const inputRef = useRef<HTMLInputElement>(null);
  const { user, refreshUser } = useUser();
  const [name, setName] = useState("");
  const [showHeader, setShowHeader] = useState(false);
  const [isEditing, setIsEditing] = useState(true);
  const [savedName, setSavedName] = useState("");

  // Initialize name from user if available
  useEffect(() => {
    if (user?.personalization?.name && !savedName) {
      setSavedName(user.personalization.name);
      setIsEditing(false);
    }
  }, [user?.personalization?.name, savedName]);

  const containerClasses = cn(
    "flex items-center justify-between w-full p-3 bg-background-tint-00 rounded-16 border border-border-01 mb-4"
  );

  const handleSave = () => {
    updateUserPersonalization({ name })
      .then(() => {
        setSavedName(name);
        setShowHeader(true);
        setIsEditing(false);
        // Don't call refreshUser() here — it would cause OnboardingFlow to
        // unmount this component (since user.personalization.name becomes set),
        // hiding the confirmation banner before the user sees it.
        // refreshUser() is called in handleDismissConfirmation instead.
      })
      .catch((error) => {
        toast.error("Failed to save name. Please try again.");
        console.error(error);
      });
  };

  const handleDismissConfirmation = () => {
    setShowHeader(false);
    refreshUser();
  };

  return (
    <>
      {showHeader && (
        <div
          className="flex items-center justify-between w-full min-h-11 py-1 pl-3 pr-2 bg-background-tint-00 rounded-16 shadow-01 mb-2"
          aria-label="non-admin-confirmation"
        >
          <ContentAction
            icon={({ className, ...props }) => (
              <SvgCheckCircle
                className={cn(className, "stroke-status-success-05")}
                {...props}
              />
            )}
            title="You're all set!"
            sizePreset="main-ui"
            variant="body"
            prominence="muted"
            paddingVariant="fit"
            rightChildren={
              <Button
                prominence="tertiary"
                size="sm"
                icon={SvgX}
                onClick={handleDismissConfirmation}
              />
            }
          />
        </div>
      )}
      {isEditing ? (
        <div
          className={containerClasses}
          onClick={() => inputRef.current?.focus()}
          role="group"
          aria-label="non-admin-name-prompt"
        >
          <ContentAction
            icon={SvgUser}
            title="What should PrivateGPT call you?"
            description="We will display this name in the app."
            sizePreset="main-ui"
            variant="section"
            paddingVariant="fit"
            rightChildren={
              <div className="flex items-center justify-end gap-2">
                <InputTypeIn
                  ref={inputRef}
                  placeholder="Your name"
                  value={name || ""}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    setName(e.target.value)
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && name && name.trim().length > 0) {
                      e.preventDefault();
                      handleSave();
                    }
                  }}
                  className="w-[26%] min-w-40"
                />
                <Disabled disabled={name === ""}>
                  <Button onClick={handleSave}>Save</Button>
                </Disabled>
              </div>
            }
          />
        </div>
      ) : (
        <div
          className={cn(containerClasses, "group")}
          aria-label="Edit display name"
          role="button"
          tabIndex={0}
          onClick={() => {
            setIsEditing(true);
            setName(savedName);
          }}
        >
          <div className="flex items-center gap-1">
            <InputAvatar
              className={cn(
                "flex items-center justify-center bg-background-neutral-inverted-00",
                "w-5 h-5"
              )}
            >
              <Text as="p" inverted secondaryBody>
                {savedName?.[0]?.toUpperCase()}
              </Text>
            </InputAvatar>
            <Text as="p" text04 mainUiAction>
              {savedName}
            </Text>
          </div>
          <div className="p-1 flex items-center gap-1">
            {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
            <IconButton
              internal
              icon={SvgEdit}
              tooltip="Edit"
              className="opacity-0 group-hover:opacity-100 transition-opacity"
            />
            <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
          </div>
        </div>
      )}
    </>
  );
}
