"use client";

import { useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SettingsLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import { Button, MessageCard, Text } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgDownload,
  SvgKey,
  SvgLock,
  SvgMoreHorizontal,
  SvgRefreshCw,
  SvgTrash,
  SvgUser,
  SvgUserEdit,
  SvgUserKey,
  SvgUserManage,
  SvgSimpleLoader,
} from "@opal/icons";
import { UserRole } from "@/lib/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Code } from "@opal/components";
import { Popover, PopoverMenu } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { markdown } from "@opal/utils";

import { useBillingInformation } from "@/hooks/useBillingInformation";
import { BillingStatus, hasActiveSubscription } from "@/lib/billing/interfaces";
import {
  deleteApiKey,
  regenerateApiKey,
  updateApiKey,
} from "@/refresh-pages/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import { DISCORD_SERVICE_API_KEY_NAME } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import ApiKeyFormModal from "@/refresh-pages/admin/ServiceAccountsPage/ApiKeyFormModal";
import { Table } from "@opal/components";
import { createTableColumns } from "@opal/components/table/columns";
import { Section } from "@/layouts/general-layouts";

const API_KEY_SWR_KEY = SWR_KEYS.adminApiKeys;
const route = ADMIN_ROUTES.API_KEYS;
const SERVICE_ACCOUNT_ROLE_LABELS: Record<UserRole, string> = {
  [UserRole.ADMIN]: "管理员",
  [UserRole.BASIC]: "标准用户",
  [UserRole.CURATOR]: "策展人",
  [UserRole.GLOBAL_CURATOR]: "全局策展人",
  [UserRole.LIMITED]: "受限账号",
  [UserRole.SLACK_USER]: "Slack 用户",
  [UserRole.EXT_PERM_USER]: "外部权限用户",
};

const tc = createTableColumns<APIKey>();

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ServiceAccountsPage() {
  const {
    data: apiKeys,
    isLoading,
    error,
  } = useSWR<APIKey[]>(API_KEY_SWR_KEY, errorHandlingFetcher);

  const { data: billingData } = useBillingInformation();
  const isTrialing =
    billingData !== undefined &&
    hasActiveSubscription(billingData) &&
    billingData.status === BillingStatus.TRIALING;

  const [fullApiKey, setFullApiKey] = useState<string | null>(null);
  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<APIKey | undefined>();
  const [search, setSearch] = useState("");
  const [regenerateTarget, setRegenerateTarget] = useState<APIKey | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<APIKey | null>(null);

  const visibleApiKeys = (apiKeys ?? []).filter(
    (key) => key.api_key_name !== DISCORD_SERVICE_API_KEY_NAME
  );

  const filteredApiKeys = visibleApiKeys.filter(
    (key) =>
      !search ||
      (key.api_key_name ?? "").toLowerCase().includes(search.toLowerCase()) ||
      key.api_key_display.toLowerCase().includes(search.toLowerCase())
  );

  const handleRoleChange = async (apiKey: APIKey, newRole: UserRole) => {
    try {
      const response = await updateApiKey(apiKey.api_key_id, {
        name: apiKey.api_key_name ?? undefined,
        role: newRole,
      });
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(`角色更新失败：${errorMsg}`);
        return;
      }
      mutate(API_KEY_SWR_KEY);
      toast.success("角色已更新。");
    } catch {
      toast.error("角色更新失败。");
    }
  };

  const handleRegenerate = async (apiKey: APIKey) => {
    try {
      const response = await regenerateApiKey(apiKey);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(`API Key 重新生成失败：${errorMsg}`);
        return;
      }
      const newKey = (await response.json()) as APIKey;
      setFullApiKey(newKey.api_key);
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "API Key 重新生成失败。"
      );
    }
  };

  const handleDelete = async (apiKey: APIKey) => {
    try {
      const response = await deleteApiKey(apiKey.api_key_id);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(`API Key 删除失败：${errorMsg}`);
        return;
      }
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "API Key 删除失败。");
    }
  };

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgUserKey,
      }),
      tc.column("api_key_name", {
        header: "名称",
        weight: 25,
        cell: (value) => (
          <Content
            title={value || "未命名"}
            sizePreset="main-ui"
            variant="body"
          />
        ),
      }),
      tc.column("api_key_display", {
        header: "API Key",
        weight: 30,
        cell: (value) => (
          <Text font="secondary-mono" color="text-03">
            {value}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "account_type",
        header: "账号类型",
        width: { weight: 25, minWidth: 160 },
        cell: (row) => (
          <InputSelect
            value={row.api_key_role}
            onValueChange={(value) => handleRoleChange(row, value as UserRole)}
          >
            <InputSelect.Trigger />
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
        ),
      }),
      tc.actions({
        cell: (row) => (
          <div className="flex flex-row gap-1">
            <Button
              icon={SvgRefreshCw}
              prominence="tertiary"
              tooltip="重新生成"
              onClick={() => setRegenerateTarget(row)}
            />
            <Popover>
              <Popover.Trigger asChild>
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="tertiary"
                  tooltip="更多"
                />
              </Popover.Trigger>
              <Popover.Content side="bottom" align="end" width="md">
                <PopoverMenu>
                  <LineItem
                    icon={SvgUserEdit}
                    onClick={() => {
                      setSelectedApiKey(row);
                      setShowCreateUpdateForm(true);
                    }}
                  >
                    编辑账号
                  </LineItem>
                  <LineItem
                    icon={SvgTrash}
                    danger
                    onClick={() => setDeleteTarget(row)}
                  >
                    删除账号
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
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description="使用服务账号以编程方式访问 Glomi AI API。"
          divider
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="服务账号加载失败"
            description="请查看控制台了解更多详情。"
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description="使用服务账号以编程方式访问 Glomi AI API。"
          divider
        />
        <SettingsLayouts.Body>
          <SvgSimpleLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const hasKeys = visibleApiKeys.length > 0;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={route.title}
        icon={route.icon}
        description="使用服务账号以编程方式访问 Glomi AI API。"
        divider
      />

      <SettingsLayouts.Body>
        {isTrialing && (
          <MessageCard
            variant="warning"
            title="升级到付费套餐后才能创建 API Key。"
            description="试用账号不包含 API Key 访问能力，请购买付费订阅以解锁此功能。"
          />
        )}

        <div className="flex flex-col">
          <AdminListHeader
            hasItems={hasKeys}
            searchQuery={search}
            onSearchQueryChange={setSearch}
            placeholder="搜索服务账号..."
            emptyStateText="创建具备用户级访问权限的服务账号 API Key。"
            onAction={() => {
              setSelectedApiKey(undefined);
              setShowCreateUpdateForm(true);
            }}
            actionLabel="新建服务账号"
          />

          {hasKeys && (
            <Table
              data={filteredApiKeys}
              getRowId={(row) => String(row.api_key_id)}
              columns={columns}
              searchTerm={search}
            />
          )}
        </div>
      </SettingsLayouts.Body>

      <Modal open={!!fullApiKey}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title="服务账号 API Key"
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description="继续前请保存此密钥，之后不会再次显示。"
          />
          <Modal.Body>
            <Code showCopyButton={false}>{fullApiKey ?? ""}</Code>
          </Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              left={
                <Button
                  prominence="secondary"
                  icon={SvgDownload}
                  onClick={() => {
                    if (!fullApiKey) return;
                    const blob = new Blob([fullApiKey], {
                      type: "text/plain",
                    });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "onyx-api-key.txt";
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  下载
                </Button>
              }
              submit={
                // TODO(@raunakab): Create an opalified copy-button and replace it here
                <Button
                  onClick={() => {
                    if (fullApiKey) {
                      navigator.clipboard.writeText(fullApiKey);
                      toast.success("API Key 已复制到剪贴板。");
                    }
                  }}
                >
                  复制 API Key
                </Button>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      </Modal>

      {showCreateUpdateForm && (
        <ApiKeyFormModal
          onCreateApiKey={(apiKey) => {
            setFullApiKey(apiKey.api_key);
          }}
          onClose={() => {
            setShowCreateUpdateForm(false);
            setSelectedApiKey(undefined);
            mutate(API_KEY_SWR_KEY);
          }}
          apiKey={selectedApiKey}
        />
      )}

      {regenerateTarget && (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title="重新生成 API Key"
          onClose={() => setRegenerateTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                const target = regenerateTarget;
                setRegenerateTarget(null);
                await handleRegenerate(target);
              }}
            >
              重新生成密钥
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              `Your current API key *${
                regenerateTarget.api_key_name || "未命名"
              }* (\`${
                regenerateTarget.api_key_display
              }\`) 会被撤销并生成新密钥。所有正在使用此密钥的应用都需要更新为新密钥。`
            )}
          </Text>
        </ConfirmationModalLayout>
      )}

      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="删除账号"
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                await handleDelete(deleteTarget);
                setDeleteTarget(null);
              }}
            >
              删除
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text as="p" color="text-03">
              {markdown(
                `Any application using the API key of account *${
                  deleteTarget.api_key_name || "未命名"
                }* (\`${
                  deleteTarget.api_key_display
                }\`) 的应用都将失去 Glomi AI 访问权限。`
              )}
            </Text>
            <Text as="p" color="text-03">
              删除后无法撤销。
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
