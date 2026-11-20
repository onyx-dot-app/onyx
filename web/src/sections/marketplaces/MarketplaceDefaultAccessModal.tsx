"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, InputSingleSelect, Modal } from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import { SvgUsers } from "@opal/icons";
import { fetchErrorDetail } from "@/lib/fetcher";
import { setMarketplaceDefaultAccess } from "@/lib/marketplaces/api";
import type {
  MarketplaceDefaultPolicy,
  MarketplaceSummary,
} from "@/lib/marketplaces/types";
import {
  MARKETPLACE_DEFAULT_POLICIES,
  isMarketplaceDefaultPolicy,
} from "@/lib/marketplaces/utils";
import { usePolicyOptions, useRefreshSkillLists } from "@/lib/skills/hooks";

interface MarketplaceDefaultAccessModalProps {
  marketplace: MarketplaceSummary;
  onClose: () => void;
  onSaved: () => void;
}

export default function MarketplaceDefaultAccessModal({
  marketplace,
  onClose,
  onSaved,
}: MarketplaceDefaultAccessModalProps) {
  const t = useTranslations("plugins.marketplaces.defaultAccess");
  const options = usePolicyOptions({ levels: MARKETPLACE_DEFAULT_POLICIES });
  const refreshSkillLists = useRefreshSkillLists();
  const [policy, setPolicy] = useState<MarketplaceDefaultPolicy>(
    marketplace.default_installation_policy ?? "AVAILABLE"
  );
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await setMarketplaceDefaultAccess(marketplace.id, policy);
      refreshSkillLists();
      toast.success(t("saved"));
      onSaved();
    } catch (caught) {
      toast.error(fetchErrorDetail(caught) ?? t("failed"));
      setBusy(false);
    }
  }

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUsers}
          title={t("title")}
          description={t("description", { name: marketplace.name })}
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={2}>
          <InputVertical title={t("title")}>
            <InputSingleSelect
              placeholder={t("title")}
              value={policy}
              defaultOption="AVAILABLE"
              disabled={busy}
              options={options}
              onValueChange={(value) => {
                if (isMarketplaceDefaultPolicy(value)) setPolicy(value);
              }}
            />
          </InputVertical>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            disabled={
              busy || policy === marketplace.default_installation_policy
            }
            onClick={() => void save()}
          >
            {t("save")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
