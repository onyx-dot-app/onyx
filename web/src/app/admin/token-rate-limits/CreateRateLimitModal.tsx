"use client";

import * as Yup from "yup";
import Button from "@/refresh-components/buttons/Button";
import { useEffect, useState } from "react";
import { Modal } from "@/components/Modal";
import { Form, Formik } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { UserGroup } from "@/lib/types";
import { Scope } from "./types";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface CreateRateLimitModalProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  onSubmit: (
    target_scope: Scope,
    period_hours: number,
    token_budget: number,
    group_id: number
  ) => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  forSpecificScope?: Scope;
  forSpecificUserGroup?: number;
}

export const CreateRateLimitModal = ({
  isOpen,
  setIsOpen,
  onSubmit,
  setPopup,
  forSpecificScope,
  forSpecificUserGroup,
}: CreateRateLimitModalProps) => {
  const [modalUserGroups, setModalUserGroups] = useState([]);
  const [shouldFetchUserGroups, setShouldFetchUserGroups] = useState(
    forSpecificScope === Scope.USER_GROUP
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
        setPopup({
          type: "error",
          message: `Failed to fetch user groups: ${error}`,
        });
      }
    };

    if (shouldFetchUserGroups) {
      fetchData();
    }
  }, [shouldFetchUserGroups, setPopup]);

  if (!isOpen) {
    return null;
  }

  return (
    <Modal
      title={"Create a Token Rate Limit"}
      onOutsideClick={() => setIsOpen(false)}
      width="max-w-2xl w-full"
    >
      <Formik
        initialValues={{
          enabled: true,
          period_hours: "",
          token_budget: "",
          target_scope: forSpecificScope || Scope.GLOBAL,
          user_group_id: forSpecificUserGroup,
        }}
        validationSchema={Yup.object().shape({
          period_hours: Yup.number()
            .required("Time Window is a required field")
            .min(1, "Time Window must be at least 1 hour"),
          token_budget: Yup.number()
            .required("Token Budget is a required field")
            .min(1, "Token Budget must be at least 1"),
          target_scope: Yup.string().required(
            "Target Scope is a required field"
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
            }
          ),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          onSubmit(
            values.target_scope,
            Number(values.period_hours),
            Number(values.token_budget),
            Number(values.user_group_id)
          );
          return formikHelpers.setSubmitting(false);
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => (
          <Form className="overflow-visible px-2">
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
            <TextFormField
              name="period_hours"
              label="Time Window (Hours)"
              type="number"
              placeholder=""
            />
            <TextFormField
              name="token_budget"
              label="Token Budget (Thousands)"
              type="number"
              placeholder=""
            />
            <Button disabled={isSubmitting}>Create</Button>
          </Form>
        )}
      </Formik>
    </Modal>
  );
};
