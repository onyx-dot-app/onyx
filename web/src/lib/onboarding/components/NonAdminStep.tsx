"use client";

import React, { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn, SelectCard, Text } from "@opal/components";
import { updateUserPersonalization } from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { Button } from "@opal/components";
import { InputAvatar } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgCheckCircle, SvgEdit, SvgUser, SvgX } from "@opal/icons";
import {
  Content,
  ContentAction,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { useSettings } from "@/lib/settings/hooks";

export default function NonAdminStep() {
  const t = useTranslations("onboarding");
  const { appName } = useSettings();
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
          className="flex items-center justify-between w-full min-h-11 py-1 ps-3 pe-2 bg-background-tint-00 rounded-16 shadow-box-01 mb-2"
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
          <InputHorizontal
            withLabel
            fillInput
            icon={SvgUser}
            title={t("nameStep.title", { appName })}
            description={t("nameStep.description")}
          >
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={2}
              height="auto"
            >
              <InputTypeIn
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
            </Section>
          </InputHorizontal>
        </div>
      ) : (
        <Hoverable.Root group="nonAdminName" width="full">
          <SelectCard
            state="empty"
            padding={2}
            rounding={4}
            onClick={handleEdit}
            aria-label={t("nameStep.edit.ariaLabel")}
          >
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              height="auto"
            >
              <Content
                icon={({ className, style }) => (
                  <InputAvatar
                    style={style}
                    className={cn(
                      className,
                      "flex items-center justify-center bg-background-neutral-inverted-00"
                    )}
                  >
                    <Text as="p" font="secondary-body" color="text-inverted-05">
                      {savedName?.[0]?.toUpperCase()}
                    </Text>
                  </InputAvatar>
                )}
                title={savedName}
                sizePreset="main-ui"
                variant="section"
              />
              <Section
                flexDirection="row"
                alignItems="center"
                gap={1}
                padding={1}
                width="fit"
                height="auto"
              >
                <Hoverable.Item group="nonAdminName" variant="appear-on-hover">
                  <Button
                    prominence="internal"
                    size="md"
                    icon={SvgEdit}
                    tooltip={t("nameStep.edit.tooltip")}
                  />
                </Hoverable.Item>
                <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
              </Section>
            </Section>
          </SelectCard>
        </Hoverable.Root>
      )}
    </>
  );
}
