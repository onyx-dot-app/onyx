"use client";

import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgBlocks } from "@opal/icons";
import { usePluginDetail } from "@/lib/plugins/hooks";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import type { Skill } from "@/lib/skills/types";
import PluginNeedList from "@/sections/plugins/PluginNeedList";

interface PluginTurnOnModalProps {
  plugin: Skill;
  onClose: () => void;
}

export default function PluginTurnOnModal({
  plugin,
  onClose,
}: PluginTurnOnModalProps) {
  const t = useTranslations("plugins.turnOn");
  const refreshLists = useRefreshSkillLists();
  const detail = usePluginDetail(plugin.id, plugin);
  // The needs that were not on at turn-on stay listed while the member turns them on.
  const notOn = new Set(
    (plugin.plugin?.needs ?? [])
      .filter((need) => need.state !== "on")
      .map((need) => need.name)
  );
  const needs = (detail.data?.plugin?.needs ?? []).filter((need) =>
    notOn.has(need.name)
  );

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md" maxHeight="85dvh">
        <Modal.Header
          icon={SvgBlocks}
          title={t("title", { name: plugin.name })}
          description={t("description")}
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={2} alignItems="stretch" height="auto">
            <Text as="p" font="secondary-body" color="text-03">
              {t("note")}
            </Text>
            <PluginNeedList
              needs={needs}
              interactive
              onChanged={() => {
                void detail.refresh();
                refreshLists();
              }}
            />
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onClose}>{t("done")}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
