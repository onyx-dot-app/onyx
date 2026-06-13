"use client";

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
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { FormikField } from "@/refresh-components/form/FormikField";
import { InputVertical } from "@opal/layouts";
import { UserRole } from "@/lib/types";
import { SvgKey, SvgLock, SvgUser, SvgUserManage } from "@opal/icons";

interface ApiKeyFormModalProps {
  onClose: () => void;
  onCreateApiKey: (apiKey: APIKey) => void;
  apiKey?: APIKey;
}

const SERVICE_ACCOUNT_ROLE_LABELS: Record<UserRole, string> = {
  [UserRole.ADMIN]: "管理员",
  [UserRole.BASIC]: "标准用户",
  [UserRole.CURATOR]: "策展人",
  [UserRole.GLOBAL_CURATOR]: "全局策展人",
  [UserRole.LIMITED]: "受限账号",
  [UserRole.SLACK_USER]: "Slack 用户",
  [UserRole.EXT_PERM_USER]: "外部权限用户",
};

export default function ApiKeyFormModal({
  onClose,
  onCreateApiKey,
  apiKey,
}: ApiKeyFormModalProps) {
  const isUpdate = apiKey !== undefined;

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm" height="lg">
        <Modal.Header
          icon={SvgKey}
          title={isUpdate ? "更新服务账号" : "创建服务账号"}
          description={
            isUpdate
              ? undefined
              : "使用服务账号 API Key 以用户级权限编程访问 Glomi AI API。你可以稍后修改账号详情。"
          }
          onClose={onClose}
        />
        <Formik
          initialValues={{
            name: apiKey?.api_key_name || "",
            role: apiKey?.api_key_role || UserRole.BASIC.toString(),
          }}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            const payload = {
              ...values,
              role: values.role as UserRole,
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
                    ? "服务账号已更新。"
                    : "服务账号已创建。"
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
                    ? `服务账号更新失败：${errorMsg}`
                    : `服务账号创建失败：${errorMsg}`
                );
              }
            } catch (e) {
              toast.error(
                e instanceof Error ? e.message : "发生未知错误。"
              );
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, values }) => (
            <Form className="w-full overflow-visible">
              <Modal.Body>
                <InputVertical withLabel="name" title="名称">
                  <FormikField<string>
                    name="name"
                    render={(field, helper) => (
                      <InputTypeIn {...field} placeholder="输入名称" />
                    )}
                  />
                </InputVertical>

                <InputVertical withLabel="role" title="账号权限">
                  <FormikField<string>
                    name="role"
                    render={(field, helper) => (
                      <InputSelect
                        value={field.value}
                        onValueChange={(value) => helper.setValue(value)}
                      >
                        <InputSelect.Trigger placeholder="选择权限" />
                        <InputSelect.Content>
                          <InputSelect.Item
                            value={UserRole.ADMIN.toString()}
                            icon={SvgUserManage}
                            description="可无限制访问全部管理员接口。"
                          >
                            {SERVICE_ACCOUNT_ROLE_LABELS[UserRole.ADMIN]}
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={UserRole.BASIC.toString()}
                            icon={SvgUser}
                            description="可访问非管理员接口的标准用户权限。"
                          >
                            {SERVICE_ACCOUNT_ROLE_LABELS[UserRole.BASIC]}
                          </InputSelect.Item>
                          <InputSelect.Item
                            value={UserRole.LIMITED.toString()}
                            icon={SvgLock}
                            description="面向智能体：可发送聊天消息，并对其他接口只读访问。"
                          >
                            {SERVICE_ACCOUNT_ROLE_LABELS[UserRole.LIMITED]}
                          </InputSelect.Item>
                        </InputSelect.Content>
                      </InputSelect>
                    )}
                  />
                </InputVertical>
              </Modal.Body>

              <Modal.Footer>
                <Button prominence="secondary" type="button" onClick={onClose}>
                  取消
                </Button>
                <Button
                  disabled={isSubmitting || !values.name.trim()}
                  type="submit"
                >
                  {isUpdate ? "更新" : "创建账号"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
