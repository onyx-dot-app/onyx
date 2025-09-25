"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { triggerIndexing } from "./lib";
import { mutate } from "swr";
import { buildCCPairInfoUrl, getTooltipMessage } from "./lib";
import { useState } from "react";
import { Modal } from "@/components/Modal";
import { Separator } from "@/components/ui/separator";
import { ConnectorCredentialPairStatus } from "./types";
import { CCPairStatus } from "@/components/Status";
import { getCCPairStatusMessage } from "@/lib/ccPair";

function ReIndexPopup({
  connectorId,
  credentialId,
  ccPairId,
  setPopup,
  hide,
}: {
  connectorId: number;
  credentialId: number;
  ccPairId: number;
  setPopup: (popupSpec: PopupSpec | null) => void;
  hide: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal title={t(k.START_INDEXING_TITLE)} onOutsideClick={hide}>
      <div>
        <Button
          variant="submit"
          className="ml-auto"
          onClick={() => {
            triggerIndexing(
              false,
              connectorId,
              credentialId,
              ccPairId,
              setPopup
            );
            hide();
          }}
        >
          {t(k.RUN_UPDATE)}
        </Button>

        <Text className="mt-2">{t(k.THIS_WILL_PULL_IN_AND_INDEX_AL)}</Text>

        <Separator />

        <Button
          variant="submit"
          className="ml-auto"
          onClick={() => {
            triggerIndexing(
              true,
              connectorId,
              credentialId,
              ccPairId,
              setPopup
            );
            hide();
          }}
        >
          {t(k.RUN_COMPLETE_RE_INDEXING)}
        </Button>

        <Text className="mt-2">{t(k.THIS_WILL_CAUSE_A_COMPLETE_RE)}</Text>

        <Text className="mt-2">
          <b>{t(k.NOTE)}</b> {t(k.DEPENDING_ON_THE_NUMBER_OF_DOC)}
        </Text>
      </div>
    </Modal>
  );
}

export function ReIndexButton({
  ccPairId,
  connectorId,
  credentialId,
  isIndexing,
  isDisabled,
  ccPairStatus,
}: {
  ccPairId: number;
  connectorId: number;
  credentialId: number;
  isIndexing: boolean;
  isDisabled: boolean;
  ccPairStatus: ConnectorCredentialPairStatus;
}) {
  const { t } = useTranslation();
  const { popup, setPopup } = usePopup();
  const [reIndexPopupVisible, setReIndexPopupVisible] = useState(false);

  return (
    <>
      {reIndexPopupVisible && (
        <ReIndexPopup
          connectorId={connectorId}
          credentialId={credentialId}
          ccPairId={ccPairId}
          setPopup={setPopup}
          hide={() => setReIndexPopupVisible(false)}
        />
      )}
      {popup}
      <Button
        variant="success-reverse"
        className="ml-auto min-w-[100px]"
        onClick={() => {
          setReIndexPopupVisible(true);
        }}
        disabled={
          isDisabled ||
          ccPairStatus == ConnectorCredentialPairStatus.DELETING ||
          ccPairStatus == ConnectorCredentialPairStatus.PAUSED ||
          ccPairStatus == ConnectorCredentialPairStatus.INVALID
        }
        tooltip={getCCPairStatusMessage(isDisabled, isIndexing, ccPairStatus)}
      >
        {t(k.RE_INDEX)}
      </Button>
    </>
  );
}
