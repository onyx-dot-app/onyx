"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useNavigation } from "@opal/navigation";
import { toast } from "@opal/layouts";
import { newSkillHref, pluginHref } from "@/lib/customize/paths";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import UploadPluginModal from "@/sections/modals/plugins/UploadPluginModal";

interface UploadPluginFlowProps {
  open: boolean;
  onClose: () => void;
}

/** The plugin upload dialog. After a save it shows the result and opens the
 * plugin page. */
export default function UploadPluginFlow({
  open,
  onClose,
}: UploadPluginFlowProps) {
  const uploadCopy = useTranslations("plugins.upload");
  const navigation = useNavigation();
  const revalidate = useRefreshSkillLists();
  const { mutate } = useSWRConfig();
  return (
    <UploadPluginModal
      open={open}
      onClose={onClose}
      onContinueSkill={(draft) => {
        onClose();
        navigation.go(newSkillHref(stageSkillCreationDraft(draft)));
      }}
      onSaved={(
        { target, plugin, unchanged, name_conflicts },
        needsAttention
      ) => {
        onClose();
        revalidate();
        // The plugin page can be open already, and the navigation below then
        // keeps it, so refresh its detail and versions here.
        void mutate(SWR_KEYS.userSkill(plugin.id));
        void mutate(SWR_KEYS.skillVersions(plugin.id));
        const values = {
          name: target.plugin_name,
          version: target.version_number,
        };
        if (unchanged) {
          toast.info(uploadCopy("saved.unchanged", values));
        } else if (name_conflicts.length > 0) {
          toast.warning(
            uploadCopy("saved.off", {
              ...values,
              names: name_conflicts.join(", "),
            })
          );
        } else {
          toast.success(
            target.kind === "new_version"
              ? uploadCopy("saved.newVersion", values)
              : uploadCopy("saved.newPlugin", values)
          );
        }
        navigation.go(
          pluginHref(plugin.id, needsAttention ? "integrations" : undefined)
        );
      }}
    />
  );
}
