"use client";

import React, { useRef, useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import Text from "@/refresh-components/texts/Text";
import { InputTypeIn } from "@opal/components";
import { updateUserPersonalization } from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { Button } from "@opal/components";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import { cn, clickOnKeyDown } from "@opal/utils";
import { SvgCheckCircle, SvgEdit, SvgUser, SvgX } from "@opal/icons";
import { ContentAction, InputHorizontal, toast } from "@opal/layouts";
import { Hoverable } from "@opal/core";

export default function NonAdminStep() {
  const t = useTranslations("onboarding");
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

  const handleEdit = () => {
    setIsEditing(true);
    setName(savedName);
  };

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
        toast.error(t("nonAdminStep.toasts.saveNameFailed"));
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
          className="flex items-center justify-between w-full min-h-11 py-1 pl-3 pr-2 bg-background-tint-00 rounded-16 shadow-box-01 mb-2"
          aria-label="non-admin-confirmation"
        >
          <ContentAction
            icon={({ className, ...props }) => (
              <SvgCheckCircle
                className={cn(className, "stroke-status-success-05")}
                {...props}
              />
            )}
            title={t("nonAdminStep.confirmation.title")}
            sizePreset="main-ui"
            variant="body"
            color="muted"
            padding={0}
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
          role="group"
          aria-label="non-admin-name-prompt"
        >
          {/* Pointer convenience only — the input is already keyboard reachable. */}
          <div
            role="presentation"
            className="contents"
            onClick={() => inputRef.current?.focus()}
          >
            <InputHorizontal
              responsive
              icon={SvgUser}
              title={t("nameStep.title")}
              description={t("nameStep.description")}
            >
              <div className="flex w-full items-center gap-2">
                <InputTypeIn
                  ref={inputRef}
                  placeholder={t("nameStep.input.placeholder")}
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
                />
                <Button disabled={name === ""} onClick={handleSave}>
                  {t("nonAdminStep.save.label")}
                </Button>
              </div>
            </InputHorizontal>
          </div>
        </div>
      ) : (
        <Hoverable.Root group="nonAdminName" width="full">
          <div
            className={containerClasses}
            aria-label={t("nameStep.edit.ariaLabel")}
            role="button"
            tabIndex={0}
            onClick={handleEdit}
            onKeyDown={clickOnKeyDown(handleEdit)}
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
              <Hoverable.Item group="nonAdminName" variant="appear-on-hover">
                <Button
                  prominence="internal"
                  size="sm"
                  icon={SvgEdit}
                  tooltip={t("nameStep.edit.tooltip")}
                />
              </Hoverable.Item>
              <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
            </div>
          </div>
        </Hoverable.Root>
      )}
    </>
  );
}
