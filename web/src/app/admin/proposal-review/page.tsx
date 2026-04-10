"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { toast } from "@/hooks/useToast";
import { Button, Text, Tag } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgCheckSquare,
  SvgEdit,
  SvgMoreHorizontal,
  SvgSettings,
  SvgTrash,
} from "@opal/icons";
import { Form, Formik } from "formik";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { FormikField } from "@/refresh-components/form/FormikField";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import Modal from "@/refresh-components/Modal";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { markdown } from "@opal/utils";
import { Table } from "@opal/components";
import { createTableColumns } from "@opal/components/table/columns";
import { Vertical as VerticalInput } from "@/layouts/input-layouts";
import type {
  RulesetResponse,
  RulesetCreate,
  RulesetUpdate,
} from "@/app/admin/proposal-review/interfaces";

const API_URL = "/api/proposal-review/rulesets";
const route = ADMIN_ROUTES.PROPOSAL_REVIEW;

const tc = createTableColumns<RulesetResponse>();

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function RulesetsPage() {
  const router = useRouter();
  const {
    data: rulesets,
    isLoading,
    error,
  } = useSWR<RulesetResponse[]>(API_URL, errorHandlingFetcher);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editTarget, setEditTarget] = useState<RulesetResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RulesetResponse | null>(
    null
  );
  const [search, setSearch] = useState("");

  const filteredRulesets = (rulesets ?? []).filter(
    (rs) =>
      !search ||
      rs.name.toLowerCase().includes(search.toLowerCase()) ||
      (rs.description ?? "").toLowerCase().includes(search.toLowerCase())
  );

  function handleEditOpen(ruleset: RulesetResponse) {
    setEditTarget(ruleset);
  }

  async function handleDelete(ruleset: RulesetResponse) {
    try {
      const res = await fetch(`${API_URL}/${ruleset.id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to delete ruleset");
      }
      await mutate(API_URL);
      setDeleteTarget(null);
      toast.success("Ruleset deleted.");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete ruleset"
      );
    }
  }

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgCheckSquare,
      }),
      tc.column("name", {
        header: "Name",
        weight: 30,
        cell: (value, row) =>
          row.description ? (
            <Content
              title={value}
              description={row.description}
              sizePreset="main-ui"
              variant="section"
            />
          ) : (
            <Content title={value} sizePreset="main-ui" variant="body" />
          ),
      }),
      tc.displayColumn({
        id: "rules_count",
        header: "Rules",
        width: { weight: 10, minWidth: 80 },
        cell: (row) => (
          <Text font="main-ui-body" color="text-03">
            {String(row.rules.length)}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "status",
        header: "Status",
        width: { weight: 15, minWidth: 100 },
        cell: (row) => (
          <Tag
            title={row.is_active ? "Active" : "Inactive"}
            color={row.is_active ? "green" : "gray"}
          />
        ),
      }),
      tc.displayColumn({
        id: "default",
        header: "Default",
        width: { weight: 10, minWidth: 80 },
        cell: (row) =>
          row.is_default ? <Tag title="Default" color="blue" /> : null,
      }),
      tc.column("updated_at", {
        header: "Last Modified",
        weight: 15,
        cell: (value) => (
          <Text font="secondary-body" color="text-03">
            {formatDate(value)}
          </Text>
        ),
      }),
      tc.actions({
        cell: (row) => (
          <div className="flex flex-row gap-1">
            <Popover>
              <Popover.Trigger asChild>
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="tertiary"
                  tooltip="More"
                />
              </Popover.Trigger>
              <Popover.Content side="bottom" align="end" width="md">
                <PopoverMenu>
                  <LineItem icon={SvgEdit} onClick={() => handleEditOpen(row)}>
                    Edit Ruleset
                  </LineItem>
                  <LineItem
                    icon={SvgTrash}
                    danger
                    onClick={() => setDeleteTarget(row)}
                  >
                    Delete Ruleset
                  </LineItem>
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        ),
      }),
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  if (error) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description="Manage review rulesets for automated proposal evaluation."
          separator
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="Failed to load rulesets."
            description="Please check the console for more details."
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description="Manage review rulesets for automated proposal evaluation."
          separator
        />
        <SettingsLayouts.Body>
          <SimpleLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const hasRulesets = (rulesets ?? []).length > 0;

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title={route.title}
        icon={route.icon}
        description="Manage review rulesets for automated proposal evaluation."
        separator
        rightChildren={
          <Button
            icon={SvgSettings}
            prominence="secondary"
            onClick={() => router.push("/admin/proposal-review/settings")}
          >
            Jira Integration
          </Button>
        }
      />

      <SettingsLayouts.Body>
        <div className="flex flex-col">
          <AdminListHeader
            hasItems={hasRulesets}
            searchQuery={search}
            onSearchQueryChange={setSearch}
            placeholder="Search rulesets..."
            emptyStateText="Create rulesets to define automated proposal review rules."
            onAction={() => setShowCreateForm(true)}
            actionLabel="New Ruleset"
          />

          {hasRulesets && (
            <Table
              data={filteredRulesets}
              getRowId={(row) => row.id}
              columns={columns}
              searchTerm={search}
              onRowClick={(row) =>
                router.push(`/admin/proposal-review/rulesets/${row.id}`)
              }
            />
          )}
        </div>
      </SettingsLayouts.Body>

      {/* Create Ruleset Modal */}
      {showCreateForm && (
        <Modal open onOpenChange={() => setShowCreateForm(false)}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header
              icon={SvgCheckSquare}
              title="New Ruleset"
              description="Create a new set of review rules."
              onClose={() => setShowCreateForm(false)}
            />
            <Formik
              initialValues={{ name: "", description: "" }}
              onSubmit={async (values, { setSubmitting }) => {
                setSubmitting(true);
                try {
                  const res = await fetch("/api/proposal-review/rulesets", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(values),
                  });
                  if (!res.ok) throw new Error(await res.text());
                  const created = await res.json();
                  toast.success("Ruleset created. Add rules to get started.");
                  setShowCreateForm(false);
                  router.push(`/admin/proposal-review/rulesets/${created.id}`);
                } catch (err) {
                  toast.error(
                    err instanceof Error
                      ? err.message
                      : "Failed to create ruleset."
                  );
                } finally {
                  setSubmitting(false);
                }
              }}
            >
              {({ isSubmitting, values }) => (
                <Form className="w-full">
                  <Modal.Body>
                    <VerticalInput
                      name="name"
                      title="Name"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="name"
                        render={(field, helper) => (
                          <InputTypeIn
                            {...field}
                            placeholder="e.g., Institutional Review"
                            onClear={() => helper.setValue("")}
                            showClearButton={false}
                          />
                        )}
                      />
                    </VerticalInput>
                    <VerticalInput
                      name="description"
                      title="Description"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="description"
                        render={(field, helper) => (
                          <InputTypeIn
                            {...field}
                            placeholder="Optional description"
                            onClear={() => helper.setValue("")}
                            showClearButton={false}
                          />
                        )}
                      />
                    </VerticalInput>
                  </Modal.Body>
                  <Modal.Footer>
                    <Button
                      prominence="secondary"
                      type="button"
                      onClick={() => setShowCreateForm(false)}
                      disabled={isSubmitting}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmitting || !values.name.trim()}
                    >
                      {isSubmitting ? "Creating..." : "Create"}
                    </Button>
                  </Modal.Footer>
                </Form>
              )}
            </Formik>
          </Modal.Content>
        </Modal>
      )}

      {/* Edit Ruleset Modal */}
      {editTarget && (
        <Modal open onOpenChange={() => setEditTarget(null)}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header
              icon={SvgEdit}
              title="Edit Ruleset"
              description="Update the ruleset name and description."
              onClose={() => setEditTarget(null)}
            />
            <Formik
              initialValues={{
                name: editTarget.name,
                description: editTarget.description || "",
              }}
              onSubmit={async (values, { setSubmitting }) => {
                setSubmitting(true);
                try {
                  const res = await fetch(
                    `/api/proposal-review/rulesets/${editTarget.id}`,
                    {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(values),
                    }
                  );
                  if (!res.ok) throw new Error(await res.text());
                  toast.success("Ruleset updated.");
                  mutate(API_URL);
                  setEditTarget(null);
                } catch (err) {
                  toast.error(
                    err instanceof Error
                      ? err.message
                      : "Failed to update ruleset."
                  );
                } finally {
                  setSubmitting(false);
                }
              }}
            >
              {({ isSubmitting, values }) => (
                <Form className="w-full">
                  <Modal.Body>
                    <VerticalInput
                      name="name"
                      title="Name"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="name"
                        render={(field, helper) => (
                          <InputTypeIn
                            {...field}
                            placeholder="Ruleset name"
                            onClear={() => helper.setValue("")}
                            showClearButton={false}
                          />
                        )}
                      />
                    </VerticalInput>
                    <VerticalInput
                      name="description"
                      title="Description"
                      nonInteractive
                      sizePreset="main-ui"
                    >
                      <FormikField<string>
                        name="description"
                        render={(field, helper) => (
                          <InputTypeIn
                            {...field}
                            placeholder="Optional description"
                            onClear={() => helper.setValue("")}
                            showClearButton={false}
                          />
                        )}
                      />
                    </VerticalInput>
                  </Modal.Body>
                  <Modal.Footer>
                    <Button
                      prominence="secondary"
                      type="button"
                      onClick={() => setEditTarget(null)}
                      disabled={isSubmitting}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmitting || !values.name.trim()}
                    >
                      {isSubmitting ? "Saving..." : "Save"}
                    </Button>
                  </Modal.Footer>
                </Form>
              )}
            </Formik>
          </Modal.Content>
        </Modal>
      )}

      {/* Delete Confirmation */}
      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Ruleset"
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                const target = deleteTarget;
                setDeleteTarget(null);
                await handleDelete(target);
              }}
            >
              Delete
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              `Are you sure you want to delete *${deleteTarget.name}*? All rules within this ruleset will also be deleted. This action cannot be undone.`
            )}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}

export default function Page() {
  return <RulesetsPage />;
}
