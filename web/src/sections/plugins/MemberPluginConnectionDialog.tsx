"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Modal, Text } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { SvgExternalLink, SvgPlug } from "@opal/icons";
import {
  connectMemberPlugin,
  MemberPluginConnectionError,
  memberPluginName,
  memberPluginReference,
  type MemberPlugin,
} from "@/lib/plugins/member";

interface MemberPluginConnectionDialogProps {
  plugin: MemberPlugin;
  open: boolean;
  onClose: () => void;
  onConnected: () => void;
}

type ConnectionAttempt =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "error"; reason: MemberPluginConnectionError["reason"] };

function ConnectionForm({
  plugin,
  onClose,
  onConnected,
}: Omit<MemberPluginConnectionDialogProps, "open">) {
  const t = useTranslations("actions.memberPlugins.connection");
  const name = memberPluginName(plugin);
  const formId = useId();
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState<ConnectionAttempt>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);
  const connection = plugin.connection;
  const canConnect =
    connection.kind === "oauth" || connection.kind === "credentials";
  const pending = attempt.kind === "pending";
  const fields = connection.kind === "credentials" ? connection.fields : [];
  const usesOAuth =
    connection.kind === "oauth" ||
    (connection.kind === "credentials" && connection.thenOAuth);

  useEffect(() => () => controller.current?.abort(), []);

  function close() {
    controller.current?.abort();
    onClose();
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canConnect || pending) return;
    if (fields.some((field) => !credentials[field]?.trim())) {
      setAttempt({ kind: "error", reason: "credentials_required" });
      return;
    }
    const current = new AbortController();
    controller.current = current;
    setAttempt({ kind: "pending" });
    try {
      await connectMemberPlugin(plugin, credentials, {
        signal: current.signal,
      });
      if (!current.signal.aborted) onConnected();
    } catch (error) {
      if (!current.signal.aborted) {
        setAttempt({
          kind: "error",
          reason:
            error instanceof MemberPluginConnectionError
              ? error.reason
              : "request_failed",
        });
      }
    }
  }

  function connectionDescription() {
    switch (connection.kind) {
      case "connected":
        switch (connection.ownership) {
          case "workspace":
            return t("workspaceDescription");
          case "session":
            return t("sessionDescription");
          case "none":
            return t("noneDescription");
          case "user":
            return t("connectedDescription");
        }
      case "credentials":
        return t("credentialsDescription");
      case "oauth":
        return t("oauthDescription");
      case "unconfigured":
        return t("unconfiguredDescription");
      case "checking":
        return t("checkingDescription");
      case "unavailable":
        return t("unavailableDescription");
    }
  }

  return (
    <Modal open onOpenChange={(open) => !open && close()}>
      <Modal.Content width="sm" position="top" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgPlug}
          title={t("title", { name })}
          description={t("description")}
          onClose={close}
        />
        <Modal.Body twoTone={false} alignItems="stretch">
          <Text as="p" font="main-ui-body" color="text-03">
            {connectionDescription()}
          </Text>
          <form
            id={formId}
            onSubmit={(event) => void connect(event)}
            className="flex flex-col gap-4"
          >
            {fields.map((field, index) => (
              <InputVertical
                key={field}
                title={field}
                withLabel={`${formId}-${index}`}
              >
                <InputTypeIn
                  id={`${formId}-${index}`}
                  type="password"
                  name={field}
                  autoComplete="off"
                  required
                  variant={pending ? "disabled" : "primary"}
                  value={credentials[field] ?? ""}
                  onChange={(event) => {
                    setCredentials((current) => ({
                      ...current,
                      [field]: event.target.value,
                    }));
                    if (attempt.kind === "error") setAttempt({ kind: "idle" });
                  }}
                />
              </InputVertical>
            ))}
            {attempt.kind === "error" && (
              <div role="alert">
                <Text as="p" font="secondary-body" color="status-error-05">
                  {t(`errors.${attempt.reason}`)}
                </Text>
              </div>
            )}
          </form>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={close}>
            {t(canConnect ? "cancel" : "done")}
          </Button>
          {canConnect && (
            <Button
              type="submit"
              form={formId}
              disabled={
                pending || fields.some((field) => !credentials[field]?.trim())
              }
              rightIcon={usesOAuth ? SvgExternalLink : undefined}
            >
              {t(pending ? "connecting" : usesOAuth ? "continue" : "connect", {
                name,
              })}
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

export default function MemberPluginConnectionDialog({
  open,
  ...props
}: MemberPluginConnectionDialogProps) {
  if (!open) return null;
  const reference = memberPluginReference(props.plugin);
  return (
    <ConnectionForm key={`${reference.kind}-${reference.id}`} {...props} />
  );
}
