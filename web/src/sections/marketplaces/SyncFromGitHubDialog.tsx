"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  InputCheckbox,
  InputTypeIn,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { InputHorizontal, InputVertical, Section } from "@opal/layouts";
import { SvgGitHub } from "@opal/logos";
import { createMarketplace, previewMarketplace } from "@/lib/marketplaces/api";
import type {
  Marketplace,
  MarketplaceCreate,
  MarketplacePreview as Preview,
} from "@/lib/marketplaces/types";
import { fetchErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import GitHubConnection from "@/sections/marketplaces/GitHubConnection";
import MarketplacePreview from "@/sections/marketplaces/MarketplacePreview";

export interface SyncFromGitHubDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after acceptance. Imported content may still be pending. */
  onSyncRequested: (marketplace: Marketplace) => void;
  /** Host owns sharing controls and an atomic create with these defaults. */
  company?: {
    controls: ReactNode;
    ready: boolean;
    create: (source: MarketplaceCreate) => Promise<Marketplace>;
  };
}

type State =
  | { kind: "idle" | "previewing" }
  | { kind: "preview" | "creating"; preview: Preview }
  | { kind: "error"; message: string }
  | { kind: "requested" };

export default function SyncFromGitHubDialog(props: SyncFromGitHubDialogProps) {
  // Each open owns its requests. A closed session cannot update a later one.
  return props.open ? <SyncSession {...props} /> : null;
}

function SyncSession({
  onClose,
  onSyncRequested,
  company,
}: SyncFromGitHubDialogProps) {
  const t = useTranslations("marketplaces");
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const { mutate } = useSWRConfig();
  const [fields, setFields] = useState({
    name: "",
    owner: "",
    repo: "",
    ref: "",
    folder: "",
  });
  const [personal, setPersonal] = useState(true);
  const [state, setState] = useState<State>({ kind: "idle" });
  const request = useRef(0);
  const closed = useRef(false);
  useEffect(
    () => () => {
      request.current += 1;
    },
    []
  );
  const creating = state.kind === "creating";
  const pending = creating || state.kind === "previewing";
  const canCreateCompany = isGlobalHolder && company !== undefined;
  const valid =
    fields.name.trim() &&
    fields.owner.trim() &&
    fields.repo.trim() &&
    fields.ref.trim();

  function invalidate() {
    request.current += 1;
    setState({ kind: "idle" });
  }

  function close() {
    if (creating || closed.current) return;
    closed.current = true;
    request.current += 1;
    onClose();
  }

  async function submit() {
    if (
      pending ||
      !valid ||
      (!personal && (!canCreateCompany || !company?.ready))
    )
      return;
    const source: MarketplaceCreate = {
      provider: "github",
      provider_config: {
        owner: fields.owner.trim(),
        repo: fields.repo.trim(),
        ref: fields.ref.trim(),
        folder: fields.folder.trim() || null,
      },
      name: fields.name.trim(),
      personal,
    };
    const ticket = ++request.current;
    const preview =
      state.kind === "preview" && state.preview.status === "complete"
        ? state.preview
        : null;
    setState(preview ? { kind: "creating", preview } : { kind: "previewing" });
    try {
      if (!preview) {
        const result = await previewMarketplace({
          provider: source.provider,
          provider_config: source.provider_config,
          personal,
        });
        if (ticket === request.current)
          setState({ kind: "preview", preview: result });
      } else {
        if (!personal && !company) return;
        const result =
          !personal && company
            ? await company.create(source)
            : await createMarketplace(source);
        if (ticket !== request.current) return;
        void mutate(SWR_KEYS.marketplaces);
        setState({ kind: "requested" });
        try {
          onSyncRequested(result);
        } catch (error) {
          console.error("Marketplace host refresh failed", error);
        }
      }
    } catch (error) {
      if (ticket === request.current)
        setState({
          kind: "error",
          message: fetchErrorDetail(error) ?? t("requestError"),
        });
    }
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Modal.Content width="md" height="fit" maxHeight="85dvh">
        <Modal.Header
          icon={SvgGitHub}
          title={t("syncTitle")}
          description={t("syncDescription")}
          onClose={creating ? undefined : close}
        />
        <Modal.Body padding={2}>
          <Section height="auto" alignItems="stretch" gap={3}>
            {state.kind === "requested" ? (
              <MessageCard
                variant="queued"
                outerPadding={1}
                innerPadding={1}
                title={t("requested")}
                description={t("requestedDescription")}
              />
            ) : (
              <>
                <GitHubConnection />
                <Card padding={2}>
                  <Section height="auto" alignItems="stretch" gap={3}>
                    {(["name", "owner", "repo", "ref", "folder"] as const).map(
                      (field) => (
                        <InputVertical
                          key={field}
                          title={t(field)}
                          withLabel
                          description={
                            field === "ref"
                              ? t("refHelp")
                              : field === "folder"
                                ? t("folderHelp")
                                : undefined
                          }
                        >
                          <InputTypeIn
                            aria-label={t(field)}
                            value={fields[field]}
                            variant={creating ? "disabled" : "primary"}
                            maxLength={field === "name" ? 255 : undefined}
                            onChange={(event) => {
                              setFields({
                                ...fields,
                                [field]: event.target.value,
                              });
                              invalidate();
                            }}
                          />
                        </InputVertical>
                      )
                    )}
                    {(canCreateCompany || !personal) && (
                      <InputHorizontal
                        title={t("company")}
                        description={
                          personal ? t("personalHelp") : t("companyHelp")
                        }
                        withLabel
                      >
                        <InputCheckbox
                          aria-label={t("company")}
                          checked={!personal}
                          disabled={creating}
                          onCheckedChange={(checked) => {
                            setPersonal(!checked);
                            invalidate();
                          }}
                        />
                      </InputHorizontal>
                    )}
                    {!canCreateCompany && personal && (
                      <Text font="secondary-body">{t("personalHelp")}</Text>
                    )}
                    {!personal && company?.controls}
                  </Section>
                </Card>
                {state.kind === "error" && (
                  <MessageCard
                    variant="error"
                    outerPadding={1}
                    innerPadding={1}
                    title={state.message}
                  />
                )}
                {(state.kind === "preview" || creating) && (
                  <MarketplacePreview preview={state.preview} />
                )}
              </>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" disabled={creating} onClick={close}>
            {t(state.kind === "requested" ? "close" : "cancel")}
          </Button>
          {state.kind !== "requested" && (
            <Button
              disabled={
                pending ||
                !valid ||
                (!personal && (!canCreateCompany || !company?.ready))
              }
              onClick={() => void submit()}
            >
              {t(
                pending
                  ? "working"
                  : state.kind === "preview" &&
                      state.preview.status === "complete"
                    ? "requestSync"
                    : "preview"
              )}
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
