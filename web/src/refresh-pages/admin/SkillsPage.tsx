"use client";

import { useRef, useState } from "react";
import { Button, MessageCard } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgArrowLeft, SvgBlocks, SvgPlus, SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import useAdminSkills from "@/hooks/useAdminSkills";
import BuiltinSkillsTable from "@/refresh-pages/admin/SkillsPage/BuiltinSkillsTable";
import CustomSkillsTable from "@/refresh-pages/admin/SkillsPage/CustomSkillsTable";
import UploadSkillModal from "@/refresh-pages/admin/SkillsPage/UploadSkillModal";
import ShareSkillModal from "@/refresh-pages/admin/SkillsPage/ShareSkillModal";
import {
  deleteCustomSkill,
  patchCustomSkill,
  replaceCustomSkillBundle,
} from "@/lib/skills/api";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface SkillsPageProps {
  onBack?: () => void;
}

export default function SkillsPage({ onBack }: SkillsPageProps = {}) {
  const { data, error, isLoading, refresh } = useAdminSkills();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const replaceBundleTarget = useRef<CustomSkill | null>(null);
  const replaceFileRef = useRef<HTMLInputElement>(null);

  async function handleToggleEnabled(skill: CustomSkill) {
    try {
      await patchCustomSkill(skill.id, { enabled: !skill.enabled });
      toast.success(
        `${skill.enabled ? "已停用" : "已重新启用"}“${skill.name}”`
      );
      refresh();
    } catch (err) {
      console.error("Failed to update skill enabled state", err);
      toast.error(
        err instanceof Error ? err.message : "更新技能失败"
      );
    }
  }

  async function handleDelete(skill: CustomSkill) {
    try {
      await deleteCustomSkill(skill.id);
      toast.success(`已删除“${skill.name}”`);
      refresh();
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  function handleReplaceBundleClick(skill: CustomSkill) {
    replaceBundleTarget.current = skill;
    replaceFileRef.current?.click();
  }

  async function handleReplaceBundleFile(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const target = replaceBundleTarget.current;
    const file = event.target.files?.[0];
    event.target.value = "";
    replaceBundleTarget.current = null;
    if (!target || !file) return;

    try {
      await replaceCustomSkillBundle(target.id, file);
      toast.success(`已替换“${target.name}”的 bundle`);
      refresh();
    } catch (err) {
      console.error("Failed to replace skill bundle", err);
      toast.error(
        err instanceof Error ? err.message : "替换 bundle 失败"
      );
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="技能"
        description="Glomi 创作智能体可调用的能力包。内置技能随 Glomi AI 提供，自定义技能可上传 zip 包，并通过用户组授权控制。"
        rightChildren={
          onBack ? (
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                onClick={onBack}
              >
                返回
              </Button>
            </div>
          ) : undefined
        }
      />
      <SettingsLayouts.Body>
        {isLoading && <SvgSimpleLoader />}

        {error && !isLoading && (
          <MessageCard
            variant="error"
            title="加载技能失败"
            description="请查看控制台详情，并尝试刷新页面。"
          />
        )}

        {!isLoading && !error && data && (
          <Section gap={2} alignItems="stretch">
            {/* Built-ins */}
            <Section gap={0.5} alignItems="stretch">
              <Text as="p" headingH3 text05>
                内置技能
              </Text>
              {data.builtins.length === 0 ? (
                <IllustrationContent
                  illustration={SvgNoResult}
                  title="尚未注册内置技能"
                  description="内置技能会随部署提供。"
                />
              ) : (
                <BuiltinSkillsTable skills={data.builtins} />
              )}
            </Section>

            {/* Customs */}
            <Section gap={0.5} alignItems="stretch">
              <div className="flex items-center justify-between gap-2">
                <Text as="p" headingH3 text05>
                  自定义技能
                </Text>
                <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
                  上传技能
                </Button>
              </div>
              <CustomSkillsTable
                skills={data.customs}
                onShareSkill={setShareTarget}
                onReplaceBundle={handleReplaceBundleClick}
                onToggleEnabled={handleToggleEnabled}
                onDeleteSkill={handleDelete}
              />
            </Section>
          </Section>
        )}
      </SettingsLayouts.Body>

      {/* Inline file picker for the row-level "Replace bundle" action so we
          don't have to open the Inspect modal first. */}
      <input
        ref={replaceFileRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={handleReplaceBundleFile}
      />

      <UploadSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={refresh}
      />

      <ShareSkillModal
        skill={shareTarget}
        open={shareTarget !== null}
        onClose={() => setShareTarget(null)}
        onSaved={refresh}
      />
    </SettingsLayouts.Root>
  );
}
