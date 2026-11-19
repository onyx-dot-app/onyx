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
  /** The plugin the user just turned on, as the switch call returned it. */
  plugin: Skill;
  onClose: () => void;
}

/** After a plugin is turned on: each integration it needs with the user's
 * state and action. The plugin works without the ones that are not on. */
export default function PluginTurnOnModal({
  plugin,
  onClose,
}: PluginTurnOnModalProps) {
  const t = useTranslations("plugins.turnOn");
  const refreshLists = useRefreshSkillLists();
  const detail = usePluginDetail(plugin.id, plugin);
  const needs = detail.data?.plugin?.needs ?? [];

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
