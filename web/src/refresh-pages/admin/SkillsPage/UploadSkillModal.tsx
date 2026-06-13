"use client";

import { useRef, useState } from "react";
import { Button } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import SkillSharePicker from "@/refresh-pages/admin/SkillsPage/SkillSharePicker";
import { createCustomSkill } from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful upload so callers can refresh their list. */
  onUploaded: () => void;
}

export default function UploadSkillModal({
  open,
  onClose,
  onUploaded,
}: UploadSkillModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [isPublic, setIsPublic] = useState(true);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setFile(null);
    setIsPublic(true);
    setGroupIds([]);
  }

  function handleClose() {
    if (submitting) return;
    reset();
    onClose();
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
  }

  async function handleSubmit() {
    if (!file) return;
    setSubmitting(true);
    try {
      const created = await createCustomSkill({
        bundle: file,
        is_public: isPublic,
        // Org-wide skills don't carry group grants — keep the DB clean of
        // grants that would be ignored by the visibility filter anyway.
        group_ids: isPublic ? [] : groupIds,
      });
      toast.success(`已上传"${created.name}"`);
      reset();
      onUploaded();
      onClose();
    } catch (err) {
      console.error("技能包上传失败", err);
      toast.error(err instanceof Error ? err.message : "上传失败", {
        description: "技能包未保存。",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const submitDisabled = submitting || !file;

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgUploadCloud}
          title="上传技能"
          description="上传 zip 包。zip 文件名会作为 slug，SKILL.md frontmatter 会提供名称和描述。"
          onClose={handleClose}
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <Section gap={0.25} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                技能包（.zip）
              </Text>
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <Button
                  icon={SvgUploadCloud}
                  prominence="secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {file ? "更换文件" : "选择 zip"}
                </Button>
                <Text as="span" mainUiBody text03>
                  {file ? file.name : "尚未选择文件"}
                </Text>
              </div>
            </Section>

            <Section gap={0.5} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                共享
              </Text>
              <SkillSharePicker
                isPublic={isPublic}
                onIsPublicChange={setIsPublic}
                groupIds={groupIds}
                onGroupIdsChange={setGroupIds}
              />
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={handleClose}>
            取消
          </Button>
          <Button
            disabled={submitDisabled}
            onClick={handleSubmit}
            icon={SvgUploadCloud}
          >
            {submitting ? "上传中..." : "上传"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
