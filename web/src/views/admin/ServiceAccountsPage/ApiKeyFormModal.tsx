"use client";

import { useState, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Form, Formik } from "formik";
import {
  createApiKey,
  updateApiKey,
} from "@/views/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/views/admin/ServiceAccountsPage/interfaces";
import { Modal } from "@opal/components";
import { Button } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { FormikField } from "@/refresh-components/form/FormikField";
import { InputVertical, toast } from "@opal/layouts";
import { SvgCheck, SvgKey, SvgLogOut, SvgUsers } from "@opal/icons";
import useGroups from "@/hooks/useGroups";
import { Popover } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import { ShadowDiv } from "@opal/components";
import { cn } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";

interface ApiKeyFormModalProps {
  onClose: () => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

export default function ApiKeyFormModal({
  onClose,
  onCreateApiKey,
  apiKey,
}: ApiKeyFormModalProps) {
  const t = useTranslations("admin.serviceAccounts");
  const isUpdate = apiKey !== undefined;
  // A key's access is whatever groups it lands in, so Admin/Basic must be offered too.
  const { data: allGroups, isLoading: groupsLoading } = useGroups(true);

  const [searchTerm, setSearchTerm] = useState("");
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [contentEl, setContentEl] = useState<HTMLDivElement | null>(null);
  const contentRef = useCallback((node: HTMLDivElement | null) => {
    setContentEl(node);
  }, []);

  const dropdownGroups = useMemo(() => {
    if (!allGroups) return [];
    if (searchTerm.length === 0) return allGroups;
    const lower = searchTerm.toLowerCase();
    return allGroups.filter((g) => g.name.toLowerCase().includes(lower));
  }, [allGroups, searchTerm]);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="lg" ref={contentRef}>
        <Modal.Header
          icon={SvgKey}
          title={
            isUpdate ? t("formModal.title.update") : t("formModal.title.create")
          }
          description={isUpdate ? undefined : t("formModal.description")}
          onClose={onClose}
        />
        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            group_ids: apiKey?.groups.map((g) => g.id) || ([] as number[]),
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const payload = {
              name: values.name || undefined,
              group_ids: values.group_ids,
            };

            try {
              let response;
              if (isUpdate) {
                response = await updateApiKey(apiKey.api_key_id, payload);
              } else {
                response = await createApiKey(payload);
              }
              if (response.ok) {
                toast.success(
                  isUpdate
                    ? t("formModal.toasts.updated")
                    : t("formModal.toasts.created")
                );
                if (!isUpdate) {
                  onCreateApiKey(await response.json());
                }
                onClose();
              } else {
                const responseJson = await response.json();
                const errorMsg = responseJson.detail || responseJson.message;
                toast.error(
                  isUpdate
                    ? t("formModal.toasts.updateFailed", { detail: errorMsg })
                    : t("formModal.toasts.createFailed", { detail: errorMsg })
                );
              }
            } catch (e) {
              toast.error(
                e instanceof Error
                  ? e.message
                  : t("formModal.toasts.unexpectedError")
              );
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => {
            const memberGroupIds = new Set(values.group_ids);
            const joinedGroups = (allGroups ?? []).filter((g) =>
              memberGroupIds.has(g.id)
            );

            const toggleGroup = (groupId: number) => {
              const next = new Set(memberGroupIds);
              if (next.has(groupId)) {
                next.delete(groupId);
              } else {
                next.add(groupId);
              }
              setFieldValue("group_ids", Array.from(next));
            };

            return (
              <Form className="w-full overflow-visible">
                <Modal.Body>
                  <InputVertical
                    withLabel="name"
                    title={t("formModal.name.title")}
                  >
                    <FormikField<string>
                      name="name"
                      render={(field) => (
                        <InputTypeIn
                          {...field}
                          placeholder={t("formModal.name.placeholder")}
                          clearButton
                        />
                      )}
                    />
                  </InputVertical>

                  <InputVertical
                    withLabel="group_ids"
                    title={t("formModal.groups.title")}
                  >
                    <Section
                      gap={2}
                      padding={1}
                      height={
                        joinedGroups.length === 0 && !popoverOpen
                          ? "auto"
                          : 14.5
                      }
                      alignItems="stretch"
                      justifyContent="start"
                      className="bg-background-tint-02 rounded-08"
                    >
                      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
                        <Popover.Trigger asChild>
                          <div>
                            <InputTypeIn
                              data-testid="groups-search-input"
                              value={searchTerm}
                              onChange={(e) => setSearchTerm(e.target.value)}
                              placeholder={t(
                                "formModal.groups.search.placeholder"
                              )}
                              searchIcon
                            />
                          </div>
                        </Popover.Trigger>
                        <Popover.Content
                          width="trigger"
                          align="start"
                          container={contentEl}
                        >
                          {groupsLoading ? (
                            <LineItem
                              skeleton
                              description={t(
                                "formModal.groups.loading.description"
                              )}
                            >
                              {t("formModal.groups.loading.title")}
                            </LineItem>
                          ) : dropdownGroups.length === 0 ? (
                            <LineItem
                              skeleton
                              description={t(
                                "formModal.groups.noResults.description"
                              )}
                            >
                              {t("formModal.groups.noResults.title")}
                            </LineItem>
                          ) : (
                            <ShadowDiv
                              shadowHeight="0.75rem"
                              className={cn(
                                "flex flex-col gap-1 max-h-[15rem] rounded-08"
                              )}
                            >
                              {dropdownGroups.map((group) => {
                                const isMember = memberGroupIds.has(group.id);
                                return (
                                  <LineItem
                                    key={group.id}
                                    icon={isMember ? SvgCheck : SvgUsers}
                                    description={t(
                                      "formModal.groups.memberCount",
                                      { count: group.users.length }
                                    )}
                                    selected={isMember}
                                    emphasized={isMember}
                                    onClick={() => toggleGroup(group.id)}
                                  >
                                    {group.name}
                                  </LineItem>
                                );
                              })}
                            </ShadowDiv>
                          )}
                        </Popover.Content>
                      </Popover>

                      <ShadowDiv
                        className={cn(
                          "max-h-[11rem] flex flex-col gap-1 rounded-08"
                        )}
                        shadowHeight="0.75rem"
                      >
                        {joinedGroups.length === 0 ? (
                          <LineItem
                            icon={SvgUsers}
                            skeleton
                            interactive={false}
                            description={t(
                              "formModal.groups.empty.description"
                            )}
                          >
                            {t("formModal.groups.empty.title")}
                          </LineItem>
                        ) : (
                          joinedGroups.map((group) => (
                            <div
                              key={group.id}
                              className="bg-background-tint-01 rounded-08"
                            >
                              <LineItem
                                icon={SvgUsers}
                                description={t("formModal.groups.memberCount", {
                                  count: group.users.length,
                                })}
                                rightChildren={
                                  <SvgLogOut height={16} width={16} />
                                }
                                onClick={() => toggleGroup(group.id)}
                              >
                                {group.name}
                              </LineItem>
                            </div>
                          ))
                        )}
                      </ShadowDiv>
                    </Section>
                  </InputVertical>
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    prominence="secondary"
                    type="button"
                    onClick={onClose}
                  >
                    {t("formModal.cancelButton.label")}
                  </Button>
                  <Button
                    disabled={isSubmitting || !values.name.trim()}
                    type="submit"
                  >
                    {isUpdate
                      ? t("formModal.submitButton.update")
                      : t("formModal.submitButton.create")}
                  </Button>
                </Modal.Footer>
              </Form>
            );
          }}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
