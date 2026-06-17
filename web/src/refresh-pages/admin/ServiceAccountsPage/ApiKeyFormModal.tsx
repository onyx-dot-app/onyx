"use client";

import { useState, useMemo, useCallback } from "react";
import { Form, Formik } from "formik";
import { toast } from "@/hooks/useToast";
import {
  createApiKey,
  updateApiKey,
} from "@/refresh-pages/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { FormikField } from "@/refresh-components/form/FormikField";
import { InputVertical } from "@opal/layouts";
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
  const isUpdate = apiKey !== undefined;
  const { data: allGroups, isLoading: groupsLoading } = useGroups();

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
          title={isUpdate ? "Update Service Account" : "Create Service Account"}
          description={
            isUpdate
              ? undefined
              : "Use service account API key to programmatically access Onyx API with user-level permissions. You can modify the account details later."
          }
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
                    ? "Successfully updated service account!"
                    : "Successfully created service account!"
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
                    ? `Error updating service account - ${errorMsg}`
                    : `Error creating service account - ${errorMsg}`
                );
              }
            } catch (e) {
              toast.error(
                e instanceof Error ? e.message : "An unexpected error occurred."
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
                  <InputVertical withLabel="name" title="Name">
                    <FormikField<string>
                      name="name"
                      render={(field) => (
                        <InputTypeIn
                          {...field}
                          placeholder="Enter a name"
                          clearButton
                        />
                      )}
                    />
                  </InputVertical>

                  <InputVertical withLabel="group_ids" title="Groups">
                    <Section
                      gap={0.5}
                      padding={0.25}
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
                              placeholder="Search groups..."
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
                            <LineItem skeleton description="Loading groups...">
                              Loading...
                            </LineItem>
                          ) : dropdownGroups.length === 0 ? (
                            <LineItem
                              skeleton
                              description="Try a different search term."
                            >
                              No groups found
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
                                    description={`${group.users.length} ${
                                      group.users.length === 1
                                        ? "user"
                                        : "users"
                                    }`}
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
                            description="No groups assigned to this service account."
                          >
                            No groups
                          </LineItem>
                        ) : (
                          joinedGroups.map((group) => (
                            <div
                              key={group.id}
                              className="bg-background-tint-01 rounded-08"
                            >
                              <LineItem
                                icon={SvgUsers}
                                description={`${group.users.length} ${
                                  group.users.length === 1 ? "user" : "users"
                                }`}
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
                    Cancel
                  </Button>
                  <Button
                    disabled={isSubmitting || !values.name.trim()}
                    type="submit"
                  >
                    {isUpdate ? "Update" : "Create Account"}
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
