"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import LineItem from "@/refresh-components/buttons/LineItem";
import { cn } from "@opal/utils";
import {
  SvgMoreHorizontal,
  SvgEdit,
  SvgBarChart,
  SvgTrash,
  SvgArrowUpRight,
} from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { useRouter } from "next/navigation";
import { deleteAgent } from "@/refresh-pages/admin/AgentsPage/svc";
import type { TutorRow } from "./interfaces";
import type { Route } from "next";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TutorRowActionsProps {
  tutor: TutorRow;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TutorRowActions({
  tutor,
  onMutate,
}: TutorRowActionsProps) {
  const router = useRouter();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  async function handleDelete() {
    setIsSubmitting(true);
    try {
      await deleteAgent(tutor.id);
      onMutate();
      toast.success(`"${tutor.name}" deleted successfully.`);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <div className="flex items-center gap-0.5">
        <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
          <Button
            prominence="tertiary"
            icon={SvgEdit}
            tooltip="Edit Tutor"
            onClick={() =>
              router.push(`/admin/tutor/edit/${tutor.id}` as Route)
            }
          />
        </div>

        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <div
            className={cn(
              !popoverOpen &&
                "opacity-0 group-hover/row:opacity-100 transition-opacity"
            )}
          >
            <Popover.Trigger asChild>
              <Button prominence="tertiary" icon={SvgMoreHorizontal} />
            </Popover.Trigger>
          </div>
          <Popover.Content align="end" width="sm">
            <PopoverMenu>
              {[
                <LineItem
                  key="test"
                  icon={SvgArrowUpRight}
                  onClick={() => {
                    setPopoverOpen(false);
                    window.open(`/app/chat?agentId=${tutor.id}`, "_blank");
                  }}
                >
                  Test
                </LineItem>,
                isPaidEnterpriseFeaturesEnabled ? (
                  <LineItem
                    key="stats"
                    icon={SvgBarChart}
                    onClick={() => {
                      setPopoverOpen(false);
                      router.push(`/ee/agents/stats/${tutor.id}` as Route);
                    }}
                  >
                    View Stats
                  </LineItem>
                ) : undefined,
                null,
                <LineItem
                  key="delete"
                  icon={SvgTrash}
                  danger
                  onClick={() => {
                    setPopoverOpen(false);
                    setDeleteOpen(true);
                  }}
                >
                  Delete
                </LineItem>,
              ]}
            </PopoverMenu>
          </Popover.Content>
        </Popover>
      </div>

      {deleteOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Virtual Tutor"
          onClose={isSubmitting ? undefined : () => setDeleteOpen(false)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button variant="danger" onClick={handleDelete}>
                Delete
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            Are you sure you want to delete{" "}
            <Text as="span" text05>
              {tutor.name}
            </Text>
            ? This action cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
