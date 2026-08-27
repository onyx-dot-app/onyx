import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import {
  Button,
  Modal,
  Table,
  Tag,
  Text,
  createTableColumns,
} from "@opal/components";
import { SvgAlertCircle, SvgPauseCircle, SvgPlayCircle } from "@opal/icons";
import { useReindexErrors } from "@/lib/indexing/hooks";
import { resumePausedPort } from "@/lib/indexing/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ReindexErrorRow } from "@/lib/indexing/types";

function ResumeButton({ row }: { row: ReindexErrorRow }) {
  const t = useTranslations("admin.indexSettings");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function onResume() {
    setBusy(true);
    setErrorMsg(null);
    try {
      await resumePausedPort(row);
    } catch (e) {
      console.error("Failed to resume paused port unit:", e);
      setErrorMsg(
        e instanceof Error ? e.message : t("errorsModal.resumeFailed")
      );
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
        {busy
          ? t("errorsModal.resumingButton.label")
          : t("errorsModal.resumeButton.label")}
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

interface ReindexErrorsModalProps {
  onClose: () => void;
}

export default function ReindexErrorsModal({
  onClose,
}: ReindexErrorsModalProps) {
  const t = useTranslations("admin.indexSettings");
  const { data: rows, isLoading, error } = useReindexErrors(true);

  const columns = useMemo(
    () => [
      tc.column("scope", {
        header: t("errorsModal.columns.type"),
        weight: 12,
        cell: (value) => (
          <Text font="secondary-body" color="text-04">
            {value === "connector"
              ? t("errorsModal.scope.connector")
              : t("errorsModal.scope.userFiles")}
          </Text>
        ),
      }),
      tc.column("name", {
        header: t("errorsModal.columns.name"),
        weight: 22,
        cell: (value) => (
          <Text font="secondary-body" color="text-04">
            {value}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "entity_id",
        header: t("errorsModal.columns.id"),
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
        header: t("errorsModal.columns.status"),
        width: { weight: 12 },
        cell: (row) =>
          row.paused ? (
            <Tag
              color="amber"
              icon={SvgPauseCircle}
              title={t("errorsModal.status.paused")}
            />
          ) : (
            <Tag
              color="red"
              icon={SvgAlertCircle}
              title={t("errorsModal.status.failed")}
            />
          ),
      }),
      tc.column("error_msg", {
        header: t("errorsModal.columns.error"),
        weight: 30,
        enableSorting: false,
        cell: (value) => (
          <Text font="secondary-body" color="text-03">
            {value ?? t("errorsModal.unknownError")}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "actions",
        header: "",
        width: { weight: 12 },
        cell: (row) => (row.paused ? <ResumeButton row={row} /> : null),
      }),
    ],
    [t]
  );

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="xl" height="sm">
        <Modal.Header
          icon={SvgAlertCircle}
          title={t("errorsModal.title")}
          description={t("errorsModal.description")}
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading ? (
            <Text as="p" color="text-03">
              {t("errorsModal.loading")}
            </Text>
          ) : error ? (
            <Text as="p" color="status-error-05">
              {t("errorsModal.loadError")}
            </Text>
          ) : !rows || rows.length === 0 ? (
            <Text as="p" color="text-03">
              {t("errorsModal.empty")}
            </Text>
          ) : (
            <div className="w-full">
              {/* Modal.Body aligns children to the start; w-full stops the
                  table shrinking to content and left-packing. */}
              <Table
                data={rows}
                columns={columns}
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
