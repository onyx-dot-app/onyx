"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSingleSelect,
  InputTypeIn,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { SvgArrowLeft } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { createMarketplace, previewMarketplace } from "@/lib/marketplaces/api";
import { useMarketplaceCopy } from "@/lib/marketplaces/hooks";
import type {
  MarketplaceDefaultPolicy,
  MarketplaceDetail,
  MarketplacePreview as Preview,
  MarketplaceScope,
} from "@/lib/marketplaces/types";
import {
  MARKETPLACE_DEFAULT_POLICIES,
  isMarketplaceDefaultPolicy,
} from "@/lib/marketplaces/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { usePolicyOptions } from "@/lib/skills/hooks";
import { Permission } from "@/lib/types";
import MarketplacePreview from "@/sections/marketplaces/MarketplacePreview";

interface SourceFields {
  repository: string;
  folder: string;
  ref: string;
}

interface AddMarketplaceModalProps {
  open: boolean;
  onClose: () => void;
  onAdded: (marketplace: MarketplaceDetail) => void;
}

interface AddMarketplaceFormProps extends Omit<
  AddMarketplaceModalProps,
  "open"
> {
  onBusyChange: (busy: boolean) => void;
}

function AddMarketplaceForm({
  onClose,
  onAdded,
  onBusyChange,
}: AddMarketplaceFormProps) {
  const t = useTranslations("plugins.marketplaces.add");
  const scopeCopy = useTranslations("plugins.marketplaces.scope");
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const policyOptions = usePolicyOptions({
    levels: MARKETPLACE_DEFAULT_POLICIES,
  });
  const [fields, setFields] = useState<SourceFields>({
    repository: "",
    folder: "",
    ref: "",
  });
  const [scope, setScope] = useState<MarketplaceScope>("personal");
  const [policy, setPolicy] = useState<MarketplaceDefaultPolicy>("AVAILABLE");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusyState] = useState<"preview" | "add" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const copy = useMarketplaceCopy();
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    errorRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [error]);

  function setBusy(next: "preview" | "add" | null) {
    setBusyState(next);
    onBusyChange(next !== null);
  }

  async function resolve() {
    setBusy("preview");
    setError(null);
    try {
      setPreview(
        await previewMarketplace({
          repository: fields.repository.trim(),
          folder: fields.folder.trim() || null,
          ref: fields.ref.trim() || null,
        })
      );
    } catch (caught) {
      setError(copy.describeError(caught, t("previewFailed")));
    } finally {
      setBusy(null);
    }
  }

  async function add(resolved: Preview) {
    setBusy("add");
    setError(null);
    const company = isGlobalHolder && scope === "company";
    try {
      onAdded(
        await createMarketplace({
          repository: resolved.repository,
          folder: resolved.folder,
          ref: resolved.ref,
          scope: company ? "company" : "personal",
          name: resolved.name,
          default_installation_policy: company ? policy : null,
        })
      );
    } catch (caught) {
      setError(copy.describeError(caught, t("addFailed")));
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null;
  const chosenScope = isGlobalHolder ? scope : "personal";
  const duplicate = !preview
    ? null
    : preview.added_company
      ? t("duplicate.company")
      : preview.added_personal && chosenScope === "personal"
        ? t("duplicate.personal")
        : null;
  const inputVariant = disabled ? "disabled" : "primary";

  return (
    <>
      <Modal.Header
        icon={SvgGitHub}
        title={preview ? t("confirmTitle") : t("title")}
        description={preview ? t("confirmDescription") : t("description")}
        onClose={disabled ? undefined : onClose}
      />
      <Modal.Body padding={2}>
        {error && (
          <Section ref={errorRef} role="alert" height="auto" alignItems="start">
            <Text as="p" font="secondary-body" color="status-error-05">
              {error}
            </Text>
          </Section>
        )}
        {preview ? (
          <>
            {isGlobalHolder && preview.status === "complete" && (
              <Card padding={2}>
                <Section gap={3} alignItems="stretch" height="auto">
                  <InputVertical
                    title={t("scope.title")}
                    description={
                      scope === "company"
                        ? t("scope.companyDescription")
                        : t("scope.personalDescription")
                    }
                  >
                    <InputSingleSelect
                      placeholder={t("scope.title")}
                      value={scope}
                      defaultOption="personal"
                      disabled={disabled}
                      options={[
                        { value: "personal", title: scopeCopy("personal") },
                        { value: "company", title: scopeCopy("company") },
                      ]}
                      onValueChange={(value) =>
                        setScope(value === "company" ? "company" : "personal")
                      }
                    />
                  </InputVertical>
                  {scope === "company" && (
                    <InputVertical
                      title={t("defaultAccess.title")}
                      description={t("defaultAccess.description")}
                    >
                      <InputSingleSelect
                        placeholder={t("defaultAccess.title")}
                        value={policy}
                        defaultOption="AVAILABLE"
                        disabled={disabled}
                        options={policyOptions}
                        onValueChange={(value) => {
                          if (isMarketplaceDefaultPolicy(value))
                            setPolicy(value);
                        }}
                      />
                    </InputVertical>
                  )}
                </Section>
              </Card>
            )}
            {duplicate && (
              <MessageCard
                variant="info"
                outerPadding={1}
                innerPadding={1}
                title={duplicate}
              />
            )}
            <MarketplacePreview preview={preview} />
          </>
        ) : (
          <Card padding={2}>
            <Section gap={3} alignItems="stretch" height="auto">
              <InputVertical
                withLabel
                title={t("repository.title")}
                description={t("repository.description")}
              >
                <InputTypeIn
                  aria-label={t("repository.title")}
                  placeholder={t("repository.placeholder")}
                  value={fields.repository}
                  variant={inputVariant}
                  onChange={(event) =>
                    setFields({ ...fields, repository: event.target.value })
                  }
                />
              </InputVertical>
              <InputVertical
                withLabel
                title={t("folder.title")}
                suffix="optional"
                description={t("folder.description")}
              >
                <InputTypeIn
                  aria-label={t("folder.title")}
                  placeholder={t("folder.placeholder")}
                  value={fields.folder}
                  variant={inputVariant}
                  onChange={(event) =>
                    setFields({ ...fields, folder: event.target.value })
                  }
                />
              </InputVertical>
              <InputVertical
                withLabel
                title={t("ref.title")}
                suffix="optional"
                description={t("ref.description")}
              >
                <InputTypeIn
                  aria-label={t("ref.title")}
                  placeholder={t("ref.placeholder")}
                  value={fields.ref}
                  variant={inputVariant}
                  onChange={(event) =>
                    setFields({ ...fields, ref: event.target.value })
                  }
                />
              </InputVertical>
              <Text as="p" font="secondary-body" color="text-03">
                {t("privateNote")}
              </Text>
            </Section>
          </Card>
        )}
      </Modal.Body>
      <Modal.Footer>
        {preview ? (
          <>
            <Button
              prominence="secondary"
              icon={SvgArrowLeft}
              disabled={disabled}
              onClick={() => {
                setPreview(null);
                setError(null);
              }}
            >
              {t("back")}
            </Button>
            <Button
              disabled={
                disabled || preview.status !== "complete" || duplicate !== null
              }
              onClick={() => void add(preview)}
            >
              {busy === "add" ? t("adding") : t("submit")}
            </Button>
          </>
        ) : (
          <>
            <Button
              prominence="secondary"
              disabled={disabled}
              onClick={onClose}
            >
              {t("cancel")}
            </Button>
            <Button
              disabled={disabled || fields.repository.trim() === ""}
              onClick={() => void resolve()}
            >
              {busy === "preview" ? t("previewing") : t("continue")}
            </Button>
          </>
        )}
      </Modal.Footer>
    </>
  );
}

export default function AddMarketplaceModal({
  open,
  onClose,
  onAdded,
}: AddMarketplaceModalProps) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="md" maxHeight="85dvh">
        {open && (
          <AddMarketplaceForm
            onClose={onClose}
            onAdded={onAdded}
            onBusyChange={setBusy}
          />
        )}
      </Modal.Content>
    </Modal>
  );
}
