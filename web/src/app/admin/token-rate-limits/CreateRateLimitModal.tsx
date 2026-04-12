"use client";

import * as Yup from "yup";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Form, Formik } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { UserGroup } from "@/lib/types";
import { Scope } from "./types";
import { toast } from "@/hooks/useToast";
import { SvgSettings } from "@opal/icons";
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
  const t = useTranslations("admin.rateLimits");
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
        toast.error(t("failedToFetchGroups", { error: String(error) }));
      }
    };

    if (shouldFetchUserGroups) {
      fetchData();
    }
  }, [shouldFetchUserGroups, t]);

  return (
    <Modal open={isOpen} onOpenChange={() => setIsOpen(false)}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header
          icon={SvgSettings}
          title={t("createTitle")}
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
          validationSchema={Yup.object().shape({
            period_hours: Yup.number()
              .required(t("validationTimeRequired"))
              .min(1, t("validationTimeMin")),
            token_budget: Yup.number()
              .required(t("validationBudgetRequired"))
              .min(1, t("validationBudgetMin")),
            target_scope: Yup.string().required(
              t("validationScopeRequired")
            ),
            user_group_id: Yup.string().test(
              "user_group_id",
              t("validationGroupRequired"),
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
            <Form className="flex flex-col h-full min-h-0 overflow-visible">
              <Modal.Body>
                {!forSpecificScope && (
                  <SelectorFormField
                    name="target_scope"
                    label={t("targetScope")}
                    options={[
                      { name: t("scopeGlobal"), value: Scope.GLOBAL },
                      { name: t("scopeUser"), value: Scope.USER },
                      { name: t("scopeUserGroup"), value: Scope.USER_GROUP },
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
                      label={t("userGroup")}
                      options={modalUserGroups}
                      includeDefault={false}
                    />
                  )}
                <TextFormField
                  name="period_hours"
                  label={t("timeWindowField")}
                  type="number"
                  placeholder=""
                />
                <TextFormField
                  name="token_budget"
                  label={t("tokenBudgetField")}
                  type="number"
                  placeholder=""
                />
              </Modal.Body>
              <Modal.Footer>
                <Button disabled={isSubmitting} type="submit">
                  {t("create")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
