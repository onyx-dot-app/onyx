import { useState } from "react";
import { mutate } from "swr";
import Modal from "@/refresh-components/Modal";
import { Button, createTableColumns, Table, Tag, Text } from "@opal/components";
import { SvgAlertCircle, SvgPauseCircle, SvgPlayCircle } from "@opal/icons";
import { useReindexErrors } from "@/lib/indexing/hooks";
import { resumePausedPort } from "@/lib/indexing/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ReindexErrorRow } from "@/lib/indexing/interfaces";

function ResumeButton({ row }: { row: ReindexErrorRow }) {
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function onResume() {
    setBusy(true);
    setErrorMsg(null);
    try {
      await resumePausedPort(row);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to resume.");
      setBusy(false);
      return;
    }
    // Resumed (a 503 just means it starts within minutes): the unit is no longer
    // paused/failed, so it drops off the list on refetch. Re-enable in case the
    // refetch itself fails, so the button never stays stuck on "Resuming…".
    setBusy(false);
    void Promise.all([
      mutate(SWR_KEYS.reindexProgress),
      mutate(SWR_KEYS.reindexErrors),
    ]);
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        variant="action"
        prominence="secondary"
        size="sm"
        icon={SvgPlayCircle}
        disabled={busy}
        onClick={onResume}
      >
        {busy ? "Resuming…" : "Resume"}
      </Button>
      {errorMsg && (
        <Text font="secondary-body" color="status-error-05">
          {errorMsg}
        </Text>
      )}
    </div>
  );
}

const tc = createTableColumns<ReindexErrorRow>();
const COLUMNS = [
  tc.column("scope", {
    header: "Type",
    weight: 12,
    cell: (value) => (
      <Text font="secondary-body" color="text-04">
        {value === "connector" ? "Connector" : "User Files"}
      </Text>
    ),
  }),
  tc.column("name", {
    header: "Name",
    weight: 22,
    cell: (value) => (
      <Text font="secondary-body" color="text-04">
        {value}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "entity_id",
    header: "ID",
    width: { weight: 12 },
    cell: (row) => (
      <Text font="secondary-body" color="text-03" nowrap>
        {row.cc_pair_id != null
          ? String(row.cc_pair_id)
          : row.user_id
            ? row.user_id.slice(0, 8)
            : "—"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "status",
    header: "Status",
    width: { weight: 12 },
    cell: (row) =>
      row.paused ? (
        <Tag color="amber" icon={SvgPauseCircle} title="Paused" />
      ) : (
        <Tag color="red" icon={SvgAlertCircle} title="Failed" />
      ),
  }),
  tc.column("error_msg", {
    header: "Error",
    weight: 30,
    enableSorting: false,
    cell: (value) => (
      <Text font="secondary-body" color="text-03">
        {value ?? "Unknown error"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "actions",
    header: "",
    width: { weight: 12 },
    cell: (row) => (row.paused ? <ResumeButton row={row} /> : null),
  }),
];

interface ReindexErrorsModalProps {
  onClose: () => void;
}

export default function ReindexErrorsModal({
  onClose,
}: ReindexErrorsModalProps) {
  const { data: rows, isLoading, error } = useReindexErrors(true);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="xl" height="sm">
        <Modal.Header
          icon={SvgAlertCircle}
          title="Re-index Attention"
          description="Connectors and user files whose latest re-index attempt failed (auto-retrying) or was paused (Resume to retry)."
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading ? (
            <Text as="p" color="text-03">
              Loading…
            </Text>
          ) : error ? (
            <Text as="p" color="status-error-05">
              Couldn&apos;t load re-index status. Please try again.
            </Text>
          ) : !rows || rows.length === 0 ? (
            <Text as="p" color="text-03">
              Nothing needs attention.
            </Text>
          ) : (
            // Modal.Body aligns children to the start; w-full stops the table
            // shrinking to content and left-packing.
            <div className="w-full">
              <Table
                data={rows}
                columns={COLUMNS}
                getRowId={(row) =>
                  `${row.scope}-${row.cc_pair_id ?? row.user_id}`
                }
              />
            </div>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
