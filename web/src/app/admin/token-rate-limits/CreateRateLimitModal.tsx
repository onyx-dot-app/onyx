"use client";

import * as Yup from "yup";
import { Button } from "@opal/components";
import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Form, Formik } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { UserGroup } from "@/lib/types";
import { Scope } from "./types";
import { toast } from "@/hooks/useToast";
import { SvgSettings } from "@opal/icons";

// UI period units -> hours. The backend contract stays period_hours (int), so
// this is purely a friendlier input than typing raw hours.
const PERIOD_UNIT_HOURS: Record<string, number> = {
  hour: 1,
  day: 24,
  week: 168,
};
interface CreateRateLimitModalProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  onSubmit: (
    target_scope: Scope,
    period_hours: number,
    token_budget: number | null,
    cost_budget_cents: number | null,
    group_id: number,
  ) => void;
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
  const [modalUserGroups, setModalUserGroups] = useState([]);
  const [shouldFetchUserGroups, setShouldFetchUserGroups] = useState(
    forSpecificScope === Scope.USER_GROUP,
  );

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch("/api/manage/admin/user-group");
        const data = await response.json();
        const options = data.map((userGroup: UserGroup) => ({
          name: userGroup.name,
          value: userGroup.id,
        }));
        setModalUserGroups(options);
        setShouldFetchUserGroups(false);
      } catch (error) {
        toast.error(`Failed to fetch user groups: ${error}`);
      }
    };

    if (shouldFetchUserGroups) {
      fetchData();
    }
  }, [shouldFetchUserGroups]);

  return (
    <Modal open={isOpen} onOpenChange={() => setIsOpen(false)}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header
          icon={SvgSettings}
          title="Create a Token Rate Limit"
          onClose={() => setIsOpen(false)}
        />
        <Formik
          initialValues={{
            enabled: true,
            period_value: "1",
            period_unit: "week",
            token_budget: "",
            cost_budget_dollars: "",
            target_scope: forSpecificScope || Scope.GLOBAL,
            user_group_id: forSpecificUserGroup,
          }}
          validationSchema={Yup.object().shape({
            period_value: Yup.number()
              .required("Time Window is a required field")
              .min(1, "Time Window must be at least 1"),
            token_budget: Yup.number()
              .min(1, "Token Budget must be at least 1")
              .test(
                "budget-required",
                "Set a token budget and/or a cost budget",
                (value, context) =>
                  value != null || context.parent.cost_budget_dollars !== "",
              ),
            cost_budget_dollars: Yup.number()
              // Empty (no cost budget) is allowed; a 0 would make the gate fire
              // on the first request (cost_since >= 0 is always true).
              .transform((value, original) =>
                original === "" ? undefined : value,
              )
              .moreThan(0, "Cost Budget must be greater than 0"),
            target_scope: Yup.string().required(
              "Target Scope is a required field",
            ),
            user_group_id: Yup.string().test(
              "user_group_id",
              "User Group is a required field",
              (value, context) => {
                return (
                  context.parent.target_scope !== "user_group" ||
                  (context.parent.target_scope === "user_group" &&
                    value !== undefined)
                );
              },
            ),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);
            // Empty token field → null (cost-only); the gate skips a null budget.
            // Sending 0 would mean "0-token limit" and block every request.
            const tokenBudget =
              values.token_budget === "" ? null : Number(values.token_budget);
            const costBudgetCents =
              values.cost_budget_dollars === ""
                ? null
                : Math.round(Number(values.cost_budget_dollars) * 100);
            // UI picks a unit; the backend contract is unchanged (period_hours: int).
            const periodHours =
              Number(values.period_value) *
              (PERIOD_UNIT_HOURS[values.period_unit] ?? 168);
            onSubmit(
              values.target_scope,
              periodHours,
              tokenBudget,
              costBudgetCents,
              Number(values.user_group_id),
            );
            return formikHelpers.setSubmitting(false);
          }}
        >
          {({ isSubmitting, values, setFieldValue }) => (
            <Form className="flex flex-col h-full min-h-0 overflow-visible">
              <Modal.Body>
                {!forSpecificScope && (
                  <SelectorFormField
                    name="target_scope"
                    label="Target Scope"
                    options={[
                      { name: "Global", value: Scope.GLOBAL },
                      { name: "User", value: Scope.USER },
                      { name: "User Group", value: Scope.USER_GROUP },
                    ]}
                    includeDefault={false}
                    onSelect={(selected) => {
                      setFieldValue("target_scope", selected);
                      if (selected === Scope.USER_GROUP) {
                        setShouldFetchUserGroups(true);
                      }
                    }}
                  />
                )}
                {forSpecificUserGroup === undefined &&
                  values.target_scope === Scope.USER_GROUP && (
                    <SelectorFormField
                      name="user_group_id"
                      label="User Group"
                      options={modalUserGroups}
                      includeDefault={false}
                    />
                  )}
                <div className="flex flex-row gap-2 items-end">
                  <div className="flex-1">
                    <TextFormField
                      name="period_value"
                      label="Time Window"
                      type="number"
                      placeholder=""
                    />
                  </div>
                  <div className="flex-1">
                    <SelectorFormField
                      name="period_unit"
                      label="Per"
                      options={[
                        { name: "Hour", value: "hour" },
                        { name: "Day", value: "day" },
                        { name: "Week", value: "week" },
                      ]}
                      includeDefault={false}
                    />
                  </div>
                </div>
                <TextFormField
                  name="token_budget"
                  label="Token Budget (Thousands, optional)"
                  type="number"
                  placeholder=""
                />
                <TextFormField
                  name="cost_budget_dollars"
                  label="Cost Budget (USD per period, optional)"
                  type="number"
                  placeholder=""
                />
              </Modal.Body>
              <Modal.Footer>
                <Button disabled={isSubmitting} type="submit">
                  Create
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
