"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Modal } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Badge } from "@/components/ui/badge";
import { AccessType } from "@/lib/types";
import { SvgEdit } from "@opal/icons";
import type { AnyCredential, Credential } from "@/lib/credentials/types";
import type { Connector } from "@/lib/connectors/types";
import {
  SvgArrowExchange,
  SvgAlertTriangle,
  SvgBubbleText,
  SvgTrash,
} from "@opal/icons";
import { Button } from "@opal/components";
import { canEditCredentialWithForm } from "@/lib/credentials/utils";
interface CredentialSelectionTableProps {
  credentials: Credential<any>[];
  onSelectCredential: (credential: Credential<any>) => void;
  /** The selected row. The caller owns the selection. */
  currentCredentialId?: number;
  onDeleteCredential: (credential: Credential<any>) => void;
  onEditCredential?: (credential: Credential<any>) => void;
}

function CredentialSelectionTable({
  credentials,
  onEditCredential,
  onSelectCredential,
  currentCredentialId,
  onDeleteCredential,
}: CredentialSelectionTableProps) {
  const t = useTranslations("admin");
  const locale = useLocale();

  return (
    <div className="w-full max-h-[50vh] overflow-auto">
      <table className="w-full text-sm border-collapse">
        <thead className="sticky top-0 w-full">
          <tr className="bg-neutral-100 dark:bg-neutral-900">
            <th className="p-2 text-start font-medium text-neutral-600 dark:text-neutral-400">
              <span className="sr-only">
                {t("credentials.table.select.label")}
              </span>
            </th>
            <th className="p-2 text-start font-medium text-neutral-600 dark:text-neutral-400">
              {t("credentials.table.id.header")}
            </th>
            <th className="p-2 text-start font-medium text-neutral-600 dark:text-neutral-400">
              {t("credentials.table.name.header")}
            </th>
            <th className="p-2 text-start font-medium text-neutral-600 dark:text-neutral-400">
              {t("credentials.table.created.header")}
            </th>
            <th className="p-2 text-start font-medium text-neutral-600 dark:text-neutral-400">
              {t("credentials.table.lastUpdated.header")}
            </th>
            <th>
              <span className="sr-only">
                {t("credentials.table.actions.label")}
              </span>
            </th>
          </tr>
        </thead>

        {credentials.length > 0 && (
          <tbody className="w-full">
            {credentials.map((credential, ind) => {
              const selected = credential.id === currentCredentialId;
              // Everything the server returns is the caller's to change:
              // `similar-credentials` already filters by permission.
              const formEditable = canEditCredentialWithForm(credential);
              return (
                <tr
                  key={credential.id}
                  className="border-b hover:bg-background-50"
                >
                  <td className="min-w-[60px] p-2">
                    {!selected ? (
                      <input
                        type="radio"
                        name="credentialSelection"
                        onChange={() => onSelectCredential(credential)}
                        className="form-radio ms-4 h-4 w-4 text-blue-600 transition duration-150 ease-in-out"
                      />
                    ) : (
                      <Badge>{t("credentials.table.selected.badge")}</Badge>
                    )}
                  </td>
                  <td className="p-2">{credential.id}</td>
                  <td className="p-2">
                    <p>
                      {credential.name ?? t("credentials.table.untitled.label")}
                    </p>
                  </td>
                  <td className="p-2">
                    {new Date(credential.time_created).toLocaleString(locale)}
                  </td>
                  <td className="p-2">
                    {new Date(credential.time_updated).toLocaleString(locale)}
                  </td>
                  <td className="p-2 flex gap-x-2 content-center mt-auto">
                    <Button
                      disabled={selected}
                      onClick={async () => {
                        onDeleteCredential(credential);
                      }}
                      icon={SvgTrash}
                    />
                    {onEditCredential && formEditable && (
                      <button
                        onClick={() => onEditCredential(credential)}
                        className="cursor-pointer my-auto"
                        aria-label={t("credentials.table.edit.ariaLabel")}
                      >
                        <SvgEdit size={16} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        )}
      </table>

      {credentials.length == 0 && (
        <p className="mt-4">{t("credentials.table.empty.message")}</p>
      )}
    </div>
  );
}

export interface ModifyCredentialProps {
  close?: () => void;
  showIfEmpty?: boolean;
  attachedConnector?: Connector<any>;
  credentials: Credential<any>[];
  defaultedCredential?: Credential<any>;
  accessType: AccessType;
  onSwap?: (
    newCredential: Credential<any>,
    connectorId: number,
    accessType: AccessType
  ) => void;
  onSwitch?: (newCredential: Credential<any>) => void;
  onEditCredential?: (credential: AnyCredential) => void;
  onDeleteCredential: (credential: Credential<any | null>) => void;
  onCreateNew?: () => void;
}

export default function ModifyCredential({
  close,
  showIfEmpty,
  attachedConnector,
  credentials,
  defaultedCredential,
  accessType,
  onSwap,
  onSwitch,
  onEditCredential,
  onDeleteCredential,
  onCreateNew,
}: ModifyCredentialProps) {
  const t = useTranslations("admin");
  const [selectedCredential, setSelectedCredential] =
    useState<Credential<any> | null>(null);
  const [confirmDeletionCredential, setConfirmDeletionCredential] =
    useState<null | Credential<any>>(null);

  if (!credentials) return null;

  return (
    <>
      {confirmDeletionCredential != null && (
        <Modal open onOpenChange={() => setConfirmDeletionCredential(null)}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header
              icon={SvgAlertTriangle}
              title={t("credentials.delete.confirmTitle")}
              onClose={() => setConfirmDeletionCredential(null)}
            />
            <Modal.Body>
              <Text as="p">{t("credentials.delete.confirmBody.message")}</Text>
            </Modal.Body>
            <Modal.Footer>
              <Button
                onClick={async () => {
                  onDeleteCredential(confirmDeletionCredential);
                  setConfirmDeletionCredential(null);
                }}
              >
                {t("credentials.delete.confirmButton.label")}
              </Button>
              <Button
                prominence="secondary"
                onClick={() => setConfirmDeletionCredential(null)}
              >
                {t("credentials.delete.cancelButton.label")}
              </Button>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      )}

      <div className="mb-0 w-full">
        <Text as="p" className="mb-4">
          {t("credentials.modify.instructions.message")}
        </Text>

        <CredentialSelectionTable
          onDeleteCredential={async (credential: Credential<any | null>) => {
            setConfirmDeletionCredential(credential);
          }}
          onEditCredential={
            onEditCredential
              ? (credential: AnyCredential) => onEditCredential(credential)
              : undefined
          }
          // With `onSwitch`, the caller owns the selection and a pick
          // switches at once; without it, a pick waits for the select button.
          currentCredentialId={(selectedCredential ?? defaultedCredential)?.id}
          credentials={credentials}
          onSelectCredential={(credential: Credential<any>) => {
            if (onSwitch) {
              onSwitch(credential);
            } else {
              setSelectedCredential(credential);
            }
          }}
        />

        {!showIfEmpty && (
          <div className="flex mt-8 justify-between">
            {onCreateNew ? (
              <Button onClick={onCreateNew} icon={SvgBubbleText}>
                {t("credentials.modify.createButton.label")}
              </Button>
            ) : (
              <div />
            )}

            <Button
              disabled={selectedCredential == null}
              onClick={() => {
                if (onSwap && attachedConnector) {
                  onSwap(selectedCredential!, attachedConnector.id, accessType);
                  if (close) {
                    close();
                  }
                }
                if (onSwitch) {
                  onSwitch(selectedCredential!);
                }
              }}
              icon={SvgArrowExchange}
            >
              {t("credentials.modify.selectButton.label")}
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
