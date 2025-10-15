"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { SlackBot, ValidSources } from "@/lib/types";
import { useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { updateSlackBotField } from "@/lib/updateSlackBotField";
import { Checkbox } from "@/app/admin/settings/SettingsForm";
import { SlackTokensForm } from "./SlackTokensForm";
import { SourceIcon } from "@/components/SourceIcon";
import { EditableStringFieldDisplay } from "@/components/EditableStringFieldDisplay";
import { deleteSlackBot } from "./new/lib";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";
import Button from "@/refresh-components/buttons/Button";
import SvgTrash from "@/icons/trash";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { cn } from "@/lib/utils";

export const ExistingSlackBotForm = ({
  existingSlackBot,
  refreshSlackBot,
}: {
  existingSlackBot: SlackBot;
  refreshSlackBot?: () => void;
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [formValues, setFormValues] = useState(existingSlackBot);
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  const handleUpdateField = async (
    field: keyof SlackBot,
    value: string | boolean
  ) => {
    try {
      const response = await updateSlackBotField(
        existingSlackBot,
        field,
        value
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setPopup({
        message: `Connector ${field} updated successfully`,
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: `Failed to update connector ${field}`,
        type: "error",
      });
    }
    setFormValues((prev) => ({ ...prev, [field]: value }));
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        isExpanded
      ) {
        setIsExpanded(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isExpanded]);

  return (
    <div>
      {popup}
      <div className="flex items-center justify-between h-14">
        <div className="flex items-center gap-2">
          <div className="my-auto">
            <SourceIcon iconSize={32} sourceType={ValidSources.Slack} />
          </div>
          <div className="ml-1">
            <EditableStringFieldDisplay
              value={formValues.name}
              isEditable={true}
              onUpdate={(value) => handleUpdateField("name", value)}
              scale={2.1}
            />
          </div>
        </div>

        <div className="flex flex-col" ref={dropdownRef}>
          <div className="flex items-center gap-4">
            <Button
              leftIcon={({ className }) => (
                <SvgChevronDownSmall
                  className={cn(className, !isExpanded && "-rotate-90")}
                />
              )}
              onClick={() => setIsExpanded(!isExpanded)}
              secondary
            >
              Update Tokens
            </Button>
            <Button
              danger
              onClick={() => setShowDeleteModal(true)}
              leftIcon={SvgTrash}
            >
              Delete
            </Button>
          </div>

          {isExpanded && (
            <div className="bg-background border rounded-lg border-background-200 shadow-lg absolute mt-12 right-0 z-10 w-full md:w-3/4 lg:w-1/2">
              <div className="p-4">
                <SlackTokensForm
                  isUpdate={true}
                  initialValues={formValues}
                  existingSlackBotId={existingSlackBot.id}
                  refreshSlackBot={refreshSlackBot}
                  setPopup={setPopup}
                  router={router}
                  onValuesChange={(values) => setFormValues(values)}
                />
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="mt-2">
        <div className="inline-block border rounded-lg border-background-200 p-2">
          <Checkbox
            label="Enabled"
            checked={formValues.enabled}
            onChange={(e) => handleUpdateField("enabled", e.target.checked)}
          />
        </div>
        {showDeleteModal && (
          <GenericConfirmModal
            title="Delete Slack Bot"
            message="Are you sure you want to delete this Slack bot? This action cannot be undone."
            confirmText="Delete"
            onClose={() => setShowDeleteModal(false)}
            onConfirm={async () => {
              try {
                const response = await deleteSlackBot(existingSlackBot.id);
                if (!response.ok) {
                  throw new Error(await response.text());
                }
                setPopup({
                  message: "Slack bot deleted successfully",
                  type: "success",
                });
                router.push("/admin/bots");
              } catch (error) {
                setPopup({
                  message: "Failed to delete Slack bot",
                  type: "error",
                });
              }
              setShowDeleteModal(false);
            }}
          />
        )}
      </div>
    </div>
  );
};
