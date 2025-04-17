"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import * as Yup from "yup";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { Modal } from "@/components/Modal";
import { Form, Formik } from "formik";
import {
  SelectorFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
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
          message: `Не удалось получить группы пользователей:${error}`,
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
      title={"Создать ограничение скорости токенов"}
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
            .required("Временное окно — обязательное поле")
            .min(1, "Временное окно должно быть не менее 1 часа"),
          token_budget: Yup.number()
            .required("Бюджет токена — обязательное поле")
            .min(1, "Бюджет токена должен быть не менее 1"),
          target_scope: Yup.string().required(
            "Целевая область — обязательное поле"
          ),
          user_group_id: Yup.string().test(
            "user_group_id",
            "Группа пользователей — обязательное поле",
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
                  { name: i18n.t(k.GLOBAL), value: Scope.GLOBAL },
                  { name: i18n.t(k.USER), value: Scope.USER },
                  { name: i18n.t(k.USER_GROUP), value: Scope.USER_GROUP },
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
                  label="Группа пользователей"
                  options={modalUserGroups}
                  includeDefault={false}
                />
              )}
            <TextFormField
              name="period_hours"
              label="Временное окно (часы)"
              type="number"
              placeholder=""
            />

            <TextFormField
              name="token_budget"
              label="Бюджет токенов (тыс.)"
              type="number"
              placeholder=""
            />

            <Button
              type="submit"
              variant="submit"
              size="sm"
              disabled={isSubmitting}
            >
              {i18n.t(k.CREATE)}
            </Button>
          </Form>
        )}
      </Formik>
    </Modal>
  );
};
