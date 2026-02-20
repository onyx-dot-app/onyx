"use client";

import { toast } from "@/hooks/useToast";
import { SlackBot, ValidSources } from "@/lib/types";
import { useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { updateSlackBotField } from "@/lib/updateSlackBotField";
import { SlackTokensForm } from "./SlackTokensForm";
import { SourceIcon } from "@/components/SourceIcon";
import { EditableStringFieldDisplay } from "@/components/EditableStringFieldDisplay";
import { deleteSlackBot } from "./new/lib";
import GenericConfirmModal from "@/components/modals/GenericConfirmModal";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import { SvgChevronDownSmall, SvgTrash } from "@opal/icons";

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex text-xs cursor-pointer">
      <input
        checked={checked}
        onChange={onChange}
        type="checkbox"
        className="mr-2 w-3.5 h-3.5 my-auto"
      />
      <span className="block font-medium text-text-700 text-sm">{label}</span>
    </label>
  );
}

export const ExistingSlackBotForm = ({
  existingSlackBot,
  refreshSlackBot,
}: {
  existingSlackBot: SlackBot;
  refreshSlackBot?: () => void;
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [formValues, setFormValues] = useState(existingSlackBot);
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
      toast.success(`Connector ${field} updated successfully`);
    } catch (error) {
      toast.error(`Failed to update connector ${field}`);
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
                toast.success("Slack bot deleted successfully");
                router.push("/admin/bots");
              } catch (error) {
                toast.error("Failed to delete Slack bot");
              }
              setShowDeleteModal(false);
            }}
          />
        )}
      </div>
    </div>
  );
};
