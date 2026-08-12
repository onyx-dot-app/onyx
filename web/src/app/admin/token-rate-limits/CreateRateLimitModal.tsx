"use client";

import * as Yup from "yup";
import {
  Button,
  InputTypeIn,
  LineItemButton,
  Modal,
  Popover,
  SelectCard,
  Text,
} from "@opal/components";
import React, { useRef } from "react";
import { Form, Formik, useField, useFormikContext } from "formik";
import { Scope } from "./types";
import {
  ContentAction,
  InputErrorText,
  InputVertical,
  Section,
} from "@opal/layouts";
import { SvgCheck, SvgGlobe, SvgUser, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import useShareableGroups from "@/hooks/useShareableGroups";
import { formatCurrency, formatTokenCount } from "@/lib/format";

const HOURS_PER_DAY = 24;
// 1T tokens stored as thousands (1e9) stays well inside the column's int32.
const MAX_TOKEN_BUDGET = 1_000_000_000_000;
// Keeps *100 finite: an unbounded value can overflow to Infinity, which JSON.stringify serializes as null.
const MAX_COST_BUDGET_DOLLARS = 10_000_000_000;

interface RateLimitFormValues {
  enabled: boolean;
  period_days: string;
  token_budget: string;
  cost_budget_dollars: string;
  target_scope: Scope;
  user_group_id: number | undefined;
}

interface ScopeOptionConfig {
  value: Scope;
  icon: IconFunctionComponent;
  title: string;
}

const SCOPE_OPTIONS: ScopeOptionConfig[] = [
  { value: Scope.GLOBAL, icon: SvgGlobe, title: "Workspace" },
  { value: Scope.USER, icon: SvgUser, title: "Per user" },
  { value: Scope.USER_GROUP, icon: SvgUsers, title: "User group" },
];

function scopeSubject(scope: Scope, groupName?: string): string {
  if (scope === Scope.GLOBAL) return "Everyone in the workspace";
  if (scope === Scope.USER) return "Each user";
  return groupName ? `Members of ${groupName}` : "Members of the chosen group";
}

function handleRadioOptionKeyDown(
  event: React.KeyboardEvent<HTMLElement>,
  onSelect: () => void
): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onSelect();
    return;
  }
  if (
    event.key !== "ArrowRight" &&
    event.key !== "ArrowDown" &&
    event.key !== "ArrowLeft" &&
    event.key !== "ArrowUp" &&
    event.key !== "Home" &&
    event.key !== "End"
  ) {
    return;
  }
  event.preventDefault();
  const group = event.currentTarget.closest('[role="radiogroup"]');
  const options = Array.from(
    group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []
  );
  const currentIndex = options.indexOf(event.currentTarget);
  const nextIndex =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? options.length - 1
        : event.key === "ArrowRight" || event.key === "ArrowDown"
          ? (currentIndex + 1) % options.length
          : (currentIndex - 1 + options.length) % options.length;
  options[nextIndex]?.focus();
  options[nextIndex]?.click();
}

interface ScopeOptionProps extends React.HTMLAttributes<HTMLElement> {
  option: ScopeOptionConfig;
  selected: boolean;
  onSelect: () => void;
  ref?: React.Ref<HTMLDivElement>;
}

function ScopeOption({
  option,
  selected,
  onSelect,
  ref,
  ...rest
}: ScopeOptionProps) {
  return (
    <SelectCard
      state={selected ? "selected" : "empty"}
      padding="sm"
      rounding="sm"
      role="radio"
      aria-checked={selected}
      aria-label={option.title}
      tabIndex={selected ? 0 : -1}
      ref={ref}
      {...rest}
      onClick={(event) => {
        rest.onClick?.(event);
        onSelect();
      }}
      onKeyDown={(event) => {
        rest.onKeyDown?.(event);
        handleRadioOptionKeyDown(event, onSelect);
      }}
    >
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={option.icon}
        title={option.title}
        padding="fit"
        color="interactive"
        center
        rightChildren={
          selected ? (
            <SvgCheck
              size={16}
              className="shrink-0 stroke-action-selection-05"
            />
          ) : undefined
        }
      />
    </SelectCard>
  );
}

interface GroupScopeOptionProps {
  option: ScopeOptionConfig;
  selected: boolean;
  groups: { name: string; value: number }[];
  selectedGroupId: number | undefined;
  onSelectScope: () => void;
  onSelectGroup: (groupId: number) => void;
}

interface GroupMenuContentProps {
  groups: { name: string; value: number }[];
  selectedGroupId: number | undefined;
  onSelectGroup: (groupId: number) => void;
}

function GroupMenuContent({
  groups,
  selectedGroupId,
  onSelectGroup,
}: GroupMenuContentProps) {
  return (
    <Popover.Content align="start" side="bottom" width="lg">
      <Popover.Menu>
        {groups.length === 0
          ? [
              <div className="p-2" key="empty">
                <Text font="secondary-body" color="text-03" as="p">
                  No user groups yet. Create one under Users &amp; Groups.
                </Text>
              </div>,
            ]
          : groups.map((group) => (
              <Popover.Close asChild key={group.value}>
                <LineItemButton
                  onClick={() => onSelectGroup(group.value)}
                  rounding="md"
                  selectVariant="select-heavy"
                  sizePreset="main-ui"
                  state={group.value === selectedGroupId ? "selected" : "empty"}
                  title={group.name}
                  variant="section"
                  width="full"
                />
              </Popover.Close>
            ))}
      </Popover.Menu>
    </Popover.Content>
  );
}

function GroupScopeOption({
  option,
  selected,
  groups,
  selectedGroupId,
  onSelectScope,
  onSelectGroup,
}: GroupScopeOptionProps) {
  return (
    <Popover>
      <Popover.Trigger asChild>
        <ScopeOption
          option={option}
          selected={selected}
          onSelect={onSelectScope}
        />
      </Popover.Trigger>
      <GroupMenuContent
        groups={groups}
        selectedGroupId={selectedGroupId}
        onSelectGroup={onSelectGroup}
      />
    </Popover>
  );
}

function TokenBudgetField() {
  const [field, meta, helpers] = useField<string>("token_budget");
  const inputRef = useRef<HTMLInputElement>(null);
  const digits = String(field.value ?? "")
    .replace(/\D/g, "")
    .slice(0, 15);
  const formattedValue = digits
    ? new Intl.NumberFormat("en-US").format(Number(digits))
    : "";

  return (
    <InputTypeIn
      ref={inputRef}
      id="token_budget"
      name="token_budget"
      value={formattedValue}
      inputMode="numeric"
      pattern="[0-9,]*"
      maxLength={19}
      placeholder="No token limit"
      onChange={(event) => {
        const input = event.target;
        const cursorPosition = input.selectionStart ?? input.value.length;
        const digitsBeforeCursor = input.value
          .slice(0, cursorPosition)
          .replace(/\D/g, "").length;

        const nextDigits = input.value.replace(/\D/g, "").slice(0, 15);
        void helpers.setValue(nextDigits);

        const nextFormatted = nextDigits
          ? new Intl.NumberFormat("en-US").format(Number(nextDigits))
          : "";
        let seenDigits = 0;
        let nextCursorPosition = nextFormatted.length;
        for (let i = 0; i < nextFormatted.length; i++) {
          if (/\d/.test(nextFormatted.charAt(i))) seenDigits++;
          if (seenDigits === digitsBeforeCursor) {
            nextCursorPosition = i + 1;
            break;
          }
        }
        requestAnimationFrame(() => {
          inputRef.current?.setSelectionRange(
            nextCursorPosition,
            nextCursorPosition
          );
        });
      }}
      onBlur={() => void helpers.setTouched(true)}
      variant={meta.touched && meta.error ? "error" : "primary"}
      rightChildren={
        <div className="pr-1">
          <Text font="secondary-action" color="text-03" nowrap>
            tokens
          </Text>
        </div>
      }
    />
  );
}

function formatDollarBudgetInput(raw: string): string | null {
  const amount = Number(raw);
  if (raw === "" || !Number.isFinite(amount) || amount <= 0) return null;
  return formatCurrency(amount);
}

function formatTokenBudgetInput(raw: string): string | null {
  const amount = Number(raw);
  if (raw === "" || !Number.isFinite(amount) || amount <= 0) return null;
  return `${formatTokenCount(amount)} tokens`;
}

interface GroupPickerProps {
  groups: { name: string; value: number }[];
  selectedGroupId: number | undefined;
  onSelectGroup: (groupId: number) => void;
}

function GroupPicker({
  groups,
  selectedGroupId,
  onSelectGroup,
}: GroupPickerProps) {
  const selectedGroup = groups.find((group) => group.value === selectedGroupId);

  return (
    <Popover>
      <Popover.Trigger asChild>
        <Button prominence="secondary" width="full">
          {selectedGroup?.name ?? "Choose a group"}
        </Button>
      </Popover.Trigger>
      <GroupMenuContent
        groups={groups}
        selectedGroupId={selectedGroupId}
        onSelectGroup={onSelectGroup}
      />
    </Popover>
  );
}

interface LimitSummaryProps {
  groupName?: string;
}

function LimitSummary({ groupName }: LimitSummaryProps) {
  const { values } = useFormikContext<RateLimitFormValues>();

  const period = Number(values.period_days);
  if (!Number.isInteger(period) || period < 1) return null;

  const budgets = [
    formatDollarBudgetInput(values.cost_budget_dollars),
    formatTokenBudgetInput(values.token_budget),
  ].filter((budget): budget is string => budget !== null);
  if (budgets.length === 0) return null;

  const budgetText = budgets.join(" or ");
  const periodText = period === 1 ? "every day" : `every ${period} days`;

  const subject = scopeSubject(values.target_scope, groupName);
  const subjectText =
    values.target_scope === Scope.USER
      ? `${subject} can spend`
      : `${subject} share${values.target_scope === Scope.GLOBAL ? "s" : ""}`;

  const summary = `${subjectText} up to ${budgetText} ${periodText}. Usage is blocked until the period resets.`;

  return (
    <div className="rounded-08 bg-background-tint-01 p-2">
      <Text font="secondary-body" color="text-03" as="p">
        {summary}
      </Text>
    </div>
  );
}

interface CreateRateLimitModalProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  onSubmit: (
    target_scope: Scope,
    period_hours: number,
    token_budget: number | null,
    cost_budget_cents: number | null,
    group_id?: number
  ) => Promise<void>;
  forSpecificScope?: Scope;
  forSpecificUserGroup?: number;
}

export default function CreateRateLimitModal({
  isOpen,
  setIsOpen,
  onSubmit,
  forSpecificScope,
  forSpecificUserGroup,
}: CreateRateLimitModalProps) {
  const { data: shareableGroupsData } = useShareableGroups();
  const modalUserGroups = (shareableGroupsData ?? []).map((userGroup) => ({
    name: userGroup.name,
    value: userGroup.id,
  }));

  return (
    <Modal open={isOpen} onOpenChange={setIsOpen}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          title="Create spending limit"
          onClose={() => setIsOpen(false)}
        />
        <Formik<RateLimitFormValues>
          initialValues={{
            enabled: true,
            period_days: "30",
            token_budget: "",
            cost_budget_dollars: "",
            target_scope: forSpecificScope || Scope.GLOBAL,
            user_group_id: forSpecificUserGroup,
          }}
          validationSchema={Yup.object().shape({
            period_days: Yup.number()
              .required("Enter a reset period")
              .integer("Enter a whole number of days")
              .min(1, "Use at least 1 day"),
            cost_budget_dollars: Yup.number()
              .transform((value, original) =>
                original === "" ? undefined : value
              )
              .moreThan(0, "Cost budget must be greater than 0")
              .max(
                MAX_COST_BUDGET_DOLLARS,
                `The maximum cost budget is $${new Intl.NumberFormat("en-US").format(MAX_COST_BUDGET_DOLLARS)}`
              )
              .test(
                "minimum-cents",
                "Cost budget must be at least $0.01",
                (value) => value == null || Math.round(value * 100) > 0
              )
              .when("token_budget", {
                is: (value: string | undefined) =>
                  value === undefined || value === "",
                then: (schema) =>
                  schema.required(
                    "Enter a cost budget, a token budget, or both"
                  ),
                otherwise: (schema) => schema.notRequired(),
              }),
            token_budget: Yup.number()
              .transform((value, original) =>
                original === "" ? undefined : value
              )
              .notRequired()
              .integer("Enter a whole number of tokens")
              .min(1_000, "Use at least 1,000 tokens")
              .max(MAX_TOKEN_BUDGET, "The maximum token budget is 1 trillion")
              .test(
                "whole-thousands",
                "Use increments of 1,000 tokens",
                (value) => value == null || value % 1_000 === 0
              ),
            target_scope: Yup.string().required(
              "Target Scope is a required field"
            ),
            user_group_id: Yup.string().test(
              "user_group_id",
              "Select a user group",
              (value, context) => {
                return (
                  context.parent.target_scope !== "user_group" ||
                  (context.parent.target_scope === "user_group" &&
                    value !== undefined)
                );
              }
            ),
          })}
          onSubmit={async (values) => {
            const tokenBudget =
              values.token_budget === ""
                ? null
                : Number(values.token_budget) / 1_000;
            const costBudgetCents =
              values.cost_budget_dollars === ""
                ? null
                : Math.round(Number(values.cost_budget_dollars) * 100);
            await onSubmit(
              values.target_scope,
              Number(values.period_days) * HOURS_PER_DAY,
              tokenBudget,
              costBudgetCents,
              values.target_scope === Scope.USER_GROUP
                ? Number(values.user_group_id)
                : undefined
            );
          }}
        >
          {({ isSubmitting, values, setFieldValue, errors, touched }) => {
            const selectedGroupName = modalUserGroups.find(
              (group) => group.value === values.user_group_id
            )?.name;
            const scopeSubjectLabel = scopeSubject(
              values.target_scope,
              selectedGroupName
            );
            const scopeCaption =
              values.target_scope === Scope.USER
                ? `${scopeSubjectLabel} gets their own budget.`
                : `${scopeSubjectLabel} share${
                    values.target_scope === Scope.GLOBAL ? "s" : ""
                  } one budget.`;

            return (
              <Form className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <Modal.Body>
                  <Section alignItems="stretch" height="auto" gap={4}>
                    {!forSpecificScope && (
                      <InputVertical
                        title="Applies to"
                        subDescription={scopeCaption}
                      >
                        <div
                          role="radiogroup"
                          aria-label="Applies to"
                          className="grid w-full grid-cols-3 gap-1"
                        >
                          {SCOPE_OPTIONS.map((option) =>
                            option.value === Scope.USER_GROUP &&
                            forSpecificUserGroup === undefined ? (
                              <GroupScopeOption
                                key={option.value}
                                option={option}
                                selected={values.target_scope === option.value}
                                groups={modalUserGroups}
                                selectedGroupId={values.user_group_id}
                                onSelectScope={() =>
                                  void setFieldValue(
                                    "target_scope",
                                    option.value
                                  )
                                }
                                onSelectGroup={(groupId) =>
                                  void setFieldValue("user_group_id", groupId)
                                }
                              />
                            ) : (
                              <ScopeOption
                                key={option.value}
                                option={option}
                                selected={values.target_scope === option.value}
                                onSelect={() =>
                                  void setFieldValue(
                                    "target_scope",
                                    option.value
                                  )
                                }
                              />
                            )
                          )}
                        </div>
                        {touched.user_group_id && errors.user_group_id && (
                          <InputErrorText>
                            {errors.user_group_id}
                          </InputErrorText>
                        )}
                      </InputVertical>
                    )}

                    {forSpecificScope === Scope.USER_GROUP &&
                      forSpecificUserGroup === undefined && (
                        <InputVertical
                          title="User group"
                          description="Choose which group shares this budget"
                        >
                          <GroupPicker
                            groups={modalUserGroups}
                            selectedGroupId={values.user_group_id}
                            onSelectGroup={(groupId) =>
                              void setFieldValue("user_group_id", groupId)
                            }
                          />
                          {touched.user_group_id && errors.user_group_id && (
                            <InputErrorText>
                              {errors.user_group_id}
                            </InputErrorText>
                          )}
                        </InputVertical>
                      )}

                    <InputVertical
                      withLabel="cost_budget_dollars"
                      title="Cost budget"
                      description="Maximum spend per reset period. Set a cost budget, a token budget, or both."
                    >
                      <InputTypeInField
                        name="cost_budget_dollars"
                        inputMode="decimal"
                        prefixText="$"
                        placeholder="No cost limit"
                        rightChildren={
                          <div className="pr-1">
                            <Text
                              font="secondary-action"
                              color="text-03"
                              nowrap
                            >
                              USD
                            </Text>
                          </div>
                        }
                      />
                    </InputVertical>

                    <InputVertical
                      withLabel="token_budget"
                      title="Token budget"
                      description="Maximum tokens per reset period"
                    >
                      <TokenBudgetField />
                    </InputVertical>

                    <InputVertical
                      withLabel="period_days"
                      title="Reset period"
                      description="Budgets reset at midnight UTC"
                    >
                      <InputTypeInField
                        name="period_days"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        rightChildren={
                          <div className="pr-1">
                            <Text
                              font="secondary-action"
                              color="text-03"
                              nowrap
                            >
                              days
                            </Text>
                          </div>
                        }
                      />
                    </InputVertical>

                    <LimitSummary groupName={selectedGroupName} />
                  </Section>
                </Modal.Body>
                <Modal.Footer>
                  <Button
                    prominence="tertiary"
                    disabled={isSubmitting}
                    type="button"
                    onClick={() => setIsOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button disabled={isSubmitting} type="submit">
                    Create limit
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
