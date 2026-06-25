"use client";

import * as Yup from "yup";
import { Button } from "@opal/components";
import { useEffect, useState, useMemo } from "react";
import Modal from "@/refresh-components/Modal";
import { Form, Formik } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { UserGroup } from "@/lib/types";
import { Scope } from "./types";
import { toast } from "@/hooks/useToast";
import { SvgSettings } from "@opal/icons";
import { useTranslation } from "react-i18next";

interface CreateRateLimitModalProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  onSubmit: (
    target_scope: Scope,
    period_hours: number,
    token_budget: number,
    group_id: number
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
  const { t } = useTranslation();
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
        toast.error(`Failed to fetch user groups: ${error}`);
      }
    };

    if (shouldFetchUserGroups) {
      fetchData();
    }
  }, [shouldFetchUserGroups]);

  const validationSchema = useMemo(() => {
    return Yup.object().shape({
      period_hours: Yup.number()
        .required(t("admin.token_rate_limits.required_field", { field: t("admin.token_rate_limits.time_window_label") }))
        .min(1, t("admin.token_rate_limits.time_window_min")),
      token_budget: Yup.number()
        .required(t("admin.token_rate_limits.required_field", { field: t("admin.token_rate_limits.token_budget_label") }))
        .min(1, t("admin.token_rate_limits.token_budget_min")),
      target_scope: Yup.string().required(
        t("admin.token_rate_limits.required_field", { field: t("admin.token_rate_limits.target_scope_label") })
      ),
      user_group_id: Yup.string().test(
        "user_group_id",
        t("admin.token_rate_limits.required_field", { field: t("admin.token_rate_limits.user_group_label") }),
        (value, context) => {
          return (
            context.parent.target_scope !== "user_group" ||
            (context.parent.target_scope === "user_group" &&
              value !== undefined)
          );
        }
      ),
    });
  }, [t]);

  return (
    <Modal open={isOpen} onOpenChange={() => setIsOpen(false)}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header
          icon={SvgSettings}
          title={t("admin.token_rate_limits.modal_title")}
          onClose={() => setIsOpen(false)}
        />
        <Formik
          initialValues={{
            enabled: true,
            period_hours: "",
            token_budget: "",
            target_scope: forSpecificScope || Scope.GLOBAL,
            user_group_id: forSpecificUserGroup,
          }}
          validationSchema={validationSchema}
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
            <Form className="flex flex-col h-full min-h-0 overflow-visible">
              <Modal.Body>
                {!forSpecificScope && (
                  <SelectorFormField
                    name="target_scope"
                    label={t("admin.token_rate_limits.target_scope_label")}
                    options={[
                      { name: t("admin.token_rate_limits.tab_global"), value: Scope.GLOBAL },
                      { name: t("admin.token_rate_limits.tab_user"), value: Scope.USER },
                      { name: t("admin.token_rate_limits.tab_groups"), value: Scope.USER_GROUP },
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
                      label={t("admin.token_rate_limits.user_group_label")}
                      options={modalUserGroups}
                      includeDefault={false}
                    />
                  )}
                <TextFormField
                  name="period_hours"
                  label={t("admin.token_rate_limits.time_window_label")}
                  type="number"
                  placeholder=""
                />
                <TextFormField
                  name="token_budget"
                  label={t("admin.token_rate_limits.token_budget_label")}
                  type="number"
                  placeholder=""
                />
              </Modal.Body>
              <Modal.Footer>
                <Button disabled={isSubmitting} type="submit">
                  {t("admin.token_rate_limits.create_modal_btn")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
