"use client";

import { cn } from "@/lib/utils";
import Modal from "@/refresh-components/Modal";
import { Text } from "@opal/components";
import VaultCard from "@/sections/settings/VaultCard";
import type { UserCounter } from "@/sections/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface VaultPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function VaultPanel({ open, onOpenChange }: VaultPanelProps) {
  const { data: counters } = useSWR<UserCounter[]>(
    open ? "/api/usage/user-counters" : null,
    errorHandlingFetcher
  );

  const completedCount =
    counters?.filter((c) => c.completed_at !== null).length ?? 0;
  const totalCount = counters?.length ?? 0;

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title="Vault"
          description={`${completedCount} / ${totalCount} unlocked`}
        />
        <Modal.Body>
          <div className="flex flex-col gap-2 pb-4">
            <div className={cn("grid gap-3", "grid-cols-1 sm:grid-cols-2")}>
              {counters?.map((counter) => (
                <VaultCard key={counter.key} counter={counter} />
              ))}
            </div>
            {!counters && (
              <div className="flex items-center justify-center py-12">
                <Text font="main-ui-body" color="text-05">
                  Loading...
                </Text>
              </div>
            )}
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

export default VaultPanel;
