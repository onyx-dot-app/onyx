# 设计文档：平台默认 OpenAI-compatible LLM Provider 自动初始化

- **日期**：2026-06-14
- **产品**：Glomi AI
- **状态**：已确认的替代设计，等待实施计划
- **替代**：`2026-06-13-consumer-llm-provider-design.md`

---

## 1. 背景与纠偏

上一版 E2 设计把“C 端用户不用配置 LLM”扩展成了“平台默认 provider + 用户可选模型档位”。这偏离了当前验证期目标。

当前目标更简单：**每个新账户或新 tenant 进来时，系统自动拥有一套可用的 Onyx 原生 LLM Provider 配置**。用户不理解 provider、API key、base URL、模型列表，也不选择 fast/balanced/deep/coding/vision 档位。平台先配置一个主模型，把对话、深度研究、标题生成、Craft 等能力跑通。

这不是新建一套 C 端模型系统，而是把 Onyx 已有的管理员手动 LLM 配置流程自动化。

---

## 2. 目标

1. 新 tenant 或本地单租户初始化时，自动 seed 一个 Onyx 原生 `LLMProvider`。
2. 第一阶段只支持 `openai_compatible` provider 类型。
3. 平台配置极简化，只要求：
   - `CONSUMER_DEFAULT_LLM_API_BASE`
   - `CONSUMER_DEFAULT_LLM_API_KEY`
   - `CONSUMER_DEFAULT_LLM_MODEL_NAME`
4. C 端用户不看到模型档位、provider selector、API key、base URL 或参数配置。
5. 聊天、深度研究、标题生成、Craft 默认都走 Onyx 现有默认模型链路。
6. 不破坏 Onyx 原有 Admin LLMProvider 架构，后续仍可通过现有后台查看和维护 provider。

---

## 3. 非目标

- 不做 fast/balanced/deep/coding/vision 多档位。
- 不做 `/api/model-catalog`。
- 不做 `/api/user/model-preference`。
- 不做 C 端模型 selector。
- 不做按场景强制切换模型，例如 deep research 强制 deep、Craft 强制 coding。
- 不做多个国产 provider 的抽象层。
- 不做模型套餐、计费档位、成本策略 UI。
- 不新增数据库表或迁移。

---

## 4. 现有架构判断

Onyx 已经有足够的原语：

- `LLMProvider` 保存 provider 类型、密钥、base URL、custom config。
- `ModelConfiguration` 保存该 provider 下的模型。
- `LLMModelFlow` 保存 chat / vision / reasoning 等 flow 的默认模型。
- `upsert_llm_provider()` 是 Admin LLM Provider 配置的核心写入路径。
- `update_default_provider()` 设置 chat 默认模型。
- `get_default_llm()` 是大多数运行时默认模型入口。
- `setup_postgres()` 覆盖单租户启动初始化。
- EE tenant provisioning 的 `configure_default_api_keys()` 覆盖新 tenant 初始化。

架构结论：第一阶段只需要一个“平台默认 provider seed”模块，调用现有 `LLMProviderUpsertRequest` / `upsert_llm_provider()` / `update_default_provider()`。

---

## 5. 配置设计

保留一个显式开关：

```env
CONSUMER_DEFAULT_LLM_ENABLED=true
```

必填配置：

```env
CONSUMER_DEFAULT_LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
CONSUMER_DEFAULT_LLM_API_KEY=...
CONSUMER_DEFAULT_LLM_MODEL_NAME=qwen-plus
```

内部固定值：

- provider type：`openai_compatible`
- provider name：`Glomi Default`
- model visibility：visible
- default flow：chat

移除或废弃以下配置：

```env
CONSUMER_DEFAULT_LLM_PROVIDER_NAME
CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE
```

说明：provider type 暂时固定，避免把“平台主模型初始化”误发展成“多 provider 产品配置面”。如果后续真的要支持 Kimi、DeepSeek、Qwen 多网关并存，再单独立项。

---

## 6. Seed 行为

### 6.1 何时执行

在两个现有生命周期里执行：

1. 单租户 / 本地启动：`backend/onyx/setup.py:setup_postgres()`
2. 新 tenant 创建：`backend/ee/onyx/server/tenants/provisioning.py:configure_default_api_keys()`

### 6.2 幂等规则

seed 过程按 provider name + provider type 查找现有 provider：

- 不存在：创建 `Glomi Default / openai_compatible` provider。
- 已存在：更新 api key、api base，并确保 env 指定的主模型存在且 visible。
- 已存在额外模型：保留，不删除，避免破坏管理员或历史数据。
- 当前没有 chat default：把 env 主模型设为默认。
- 当前 chat default 是同一个 managed provider 的旧模型：更新为 env 主模型。
- 当前 chat default 是其他 provider 或管理员手动配置：不覆盖。

### 6.3 缺配置处理

如果未启用或缺少必填配置：

- 不阻塞应用启动。
- 返回结构化 seed result，例如 `disabled`、`missing_api_key`、`missing_api_base`、`missing_model_name`。
- 写日志提示具体缺项。
- 运行时如果没有默认 LLM，沿用 Onyx 现有错误和前端未配置状态。

---

## 7. 运行时数据流

目标运行时路径：

```text
平台 env
  -> tenant/setup seed
  -> LLMProvider + ModelConfiguration + default CHAT flow
  -> get_default_llm()
  -> chat / deep research / title / Craft
```

需要收回的路径：

```text
model profile catalog
  -> user model preference
  -> profile_to_llm_override()
  -> scene-specific forced model
```

普通聊天：

- 不再通过 consumer profile 生成 `LLMOverride`。
- 有显式 override 时仍走 Onyx 现有 override 逻辑。
- 无 override 时走 persona default 或系统默认模型。

深度研究：

- 不再强制切到 `deep` profile。
- 先统一走默认主模型。

标题生成：

- 不再使用 `TITLE_CONSUMER_MODEL_PROFILE_ID`。
- 直接走 `get_default_llm()`。

Craft：

- 不再优先 `coding` profile。
- 继续走现有 `select_default_llm_config()` 的 provider/model 选择逻辑。

---

## 8. 前端与 API

删除或停用的产品面：

- `ConsumerModelProfileSelector`
- `useConsumerModelCatalog`
- `consumerModels/*`
- `SWR_KEYS.consumerModelCatalog`
- `SWR_KEYS.consumerModelPreference`
- `/api/model-catalog`
- `/api/user/model-preference`

保留的 Onyx 原生能力：

- Admin LLM Provider 页面仍可看到 provider。
- 现有 `useLlmManager` / provider descriptor /默认模型逻辑继续工作。
- 输入框是否可用仍由现有 LLM provider 配置状态决定。

---

## 9. 错误处理

本设计不新增公开 API，因此不需要新增用户可见错误模型。

内部错误处理原则：

- seed 阶段捕获异常并记录日志，不阻塞服务启动。
- 如果调用 `upsert_llm_provider()` 或 `update_default_provider()` 失败，保留原异常日志，返回 `failed` seed result。
- 后端 API 如需抛业务错误，继续使用 `OnyxError`，不直接抛 `HTTPException`。

---

## 10. 测试

后端 focused unit tests：

1. 构建 seed request 只包含一个 env 主模型。
2. 缺 `api_key` / `api_base` / `model_name` 时跳过并返回明确 reason。
3. 无现有 provider 时 upsert provider，并设置 chat 默认模型。
4. 有现有 provider 时保留额外 model config，不删除。
5. 没有默认模型时设置默认。
6. 默认模型属于同一个 managed provider 的旧模型时更新到 env 主模型。
7. 默认模型属于其他 provider 时不覆盖。
8. `setup_postgres()` 和 tenant provisioning 仍调用 seed。

前端 tests：

- 删除 consumer model selector 相关 tests。
- 如果移除 import 影响页面类型检查，跑 `npm run types:check`。

验证：

- `PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest <focused tests>`
- `npm run types:check`
- 本地启动后确认没有 `/model-catalog` auth 启动错误。

---

## 11. 后续扩展边界

如果未来需要多模型策略，应另立项，不在本期暗中保留档位系统。可能的未来方向：

- 平台内部按场景选择模型，但不暴露给用户。
- 多 provider fallback。
- vision model 默认配置。
- 成本感知路由。
- 用户套餐和模型能力边界。

这些都依赖真实使用数据。验证期先把“注册即可用的单主模型”跑稳定。
