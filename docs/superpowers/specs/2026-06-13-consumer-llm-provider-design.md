# 设计文档：C 端默认 LLM Provider 与模型选择

- **日期**：2026-06-13
- **产品**：Glomi AI
- **背景**：基于 Onyx fork，目标转向 C 端消费级 Agent
- **状态**：设计稿，供后续实施计划使用

---

## 1. 问题与目标

当前 Onyx 的 LLM Provider 更偏组织管理员配置：管理员进入 `/admin/configuration/language-models`，手动配置 provider、API key、base URL、模型列表和默认模型。这个模式适合 B2B workspace，但不适合 C 端。

Glomi AI 的目标是：用户注册后无需理解 provider、API key、base URL、temperature、max tokens 等概念，系统自动加载一套平台默认国产模型配置。用户可以选择“模型档位”或“模型名称”，但真实 provider 凭证、可用模型范围、模型参数和成本策略由平台控制。

本设计的核心目标：

1. 保持 Onyx 当前多租户和 LLM Provider 架构不大改。
2. 新注册账号或新 tenant 自动获得一套默认 Qwen/OpenAI-compatible 模型配置。
3. C 端普通用户只选择模型档位，不进入 LLM Provider 配置页。
4. 平台统一控制模型参数、可见模型、默认模型、限流与成本。
5. 后续可以扩展 DeepSeek、Kimi、智谱、火山等国产模型，但第一期只落 Qwen 系列。

---

## 2. 现有架构判断

Onyx 已有可复用基础：

- `LLMProvider` / `ModelConfiguration` 存储 provider、密钥、base URL、模型列表。
- `openai_compatible` provider 已存在，适合接 DashScope / 百炼这类 OpenAI-compatible endpoint。
- 多租户模式下，每个 tenant 有自己的 schema；LLM Provider 配置跟 tenant 走。
- `configure_default_api_keys()` 已经有“新 tenant 创建时自动 seed 默认 provider”的模式。
- `AUTO_PROVISION_DEFAULT_LLM_PROVIDERS` 已经表达了“是否自动给新 tenant 创建默认 provider”的开关。

架构结论：不需要新增一个全新的 Qwen provider 类型。第一期用现有 `openai_compatible`，把 Qwen 当作平台预置 OpenAI-compatible provider。

---

## 3. 产品原则

### 3.1 用户看到的是“模型选择”，不是“模型配置”

C 端用户不应该看到：

- API Key
- API Base
- Provider Type
- Temperature
- Top P
- Max Tokens
- Tool calling compatibility
- Context window
- Cost per token

用户可以看到：

- 快速
- 均衡
- 深度
- 编程
- 多模态

或者更产品化的模型标签：

- Qwen Turbo
- Qwen Plus
- Qwen Max
- Qwen Coder
- Qwen Vision

### 3.2 Provider 是平台资产

Qwen API key、base URL、模型白名单、参数策略属于平台，不属于用户。普通用户没有新增、编辑、删除 LLM Provider 的权限。

### 3.3 参数策略服务端决定

用户可以选择模型档位，但不能随意调 temperature、max tokens、tools 策略。模型参数由平台根据场景决定，例如普通聊天、深度研究、代码生成、Craft 生成、标题命名可以使用不同 profile。

### 3.4 先用配置，不急着加复杂 DB

第一期优先使用配置文件 + env secrets，而不是马上设计复杂后台。等模型运营频繁后，再做平台运营后台。

---

## 4. 推荐方案

### 方案 A：租户级自动 seed 平台默认 Provider（推荐）

在新 tenant 初始化时，自动创建一个 `openai_compatible` 的 Qwen provider，并写入平台允许的模型列表和默认模型。

优点：

- 最贴合 Onyx 现有架构。
- 不破坏多租户隔离。
- 每个 tenant 都有完整 LLM Provider 数据，现有调用链基本可复用。
- 后续允许部分高级 workspace 使用独立 provider 也容易演进。

缺点：

- 多租户下每个 tenant 都会有一份 provider 配置副本。
- 平台调整模型目录时，需要同步更新已有 tenant。

### 方案 B：单平台共享 Provider，所有 C 端用户共用一个 tenant

把所有 C 端用户放在同一个 tenant，共享一份 provider。

优点：

- 最快。
- 不需要做多租户 provider seed。

缺点：

- 用户数据隔离压力变大。
- 后续团队空间、用量计费、用户删除、合规审计都会更别扭。
- 和 Onyx 已有 tenant 隔离模型不一致。

### 方案 C：用户自带 API key / 自己配置 Provider

允许用户填写自己的模型 key。

优点：

- 平台成本低。
- 适合开发者用户。

缺点：

- 不适合 C 端主路径。
- 配置复杂，转化率低。
- 容易把产品变成工具后台。

结论：第一期采用方案 A。方案 C 可以作为未来高级功能，不进入 C 端默认路径。

---

## 5. 目标架构

### 5.1 概念模型

**Platform LLM Provider**

平台维护的真实 provider 配置，例如 Qwen OpenAI-compatible endpoint。包含 API key、base URL、provider type、默认模型和可用模型。

**Consumer Model Catalog**

面向用户展示的模型目录。它不是 provider 配置页，而是一份平台策划过的模型产品清单。

**Model Profile**

平台控制的调用策略。一个 profile 绑定真实 provider/model 和参数策略。例如：

| profile_id | 用户文案 | 真实模型 | 使用场景 |
|---|---|---|---|
| `fast` | 快速 | `qwen-turbo` | 快速问答、轻量任务 |
| `balanced` | 均衡 | `qwen-plus` | 默认聊天 |
| `deep` | 深度 | `qwen-max` | 复杂推理、深度研究 |
| `coding` | 编程 | `qwen3-coder-plus` | 代码、Craft |
| `vision` | 多模态 | `qwen-vl-plus` | 图片理解 |

**User Model Preference**

用户选择的默认模型档位。第一期可以先用现有用户偏好/前端 cookie/轻量后端字段承载；如果需要跨设备稳定同步，再加明确的 DB 字段。

### 5.2 配置来源

新增平台默认模型配置，建议由两部分组成：

1. secrets/env：只放密钥和敏感 endpoint。
2. catalog JSON/Python 常量：放模型目录、显示名、默认 profile、参数策略。

建议环境变量：

```bash
CONSUMER_DEFAULT_LLM_ENABLED=true
CONSUMER_DEFAULT_LLM_PROVIDER_NAME=Qwen
CONSUMER_DEFAULT_LLM_PROVIDER_TYPE=openai_compatible
CONSUMER_DEFAULT_LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
CONSUMER_DEFAULT_LLM_API_KEY=...
CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE=balanced
```

模型目录建议放代码配置，便于评审和测试：

```text
backend/onyx/llm/consumer_model_catalog.py
```

后续模型目录运营频繁后，再迁移到 DB 或平台运营后台。

---

## 6. 注册与租户初始化流程

### 6.1 新 tenant 创建

新用户注册时，如果多租户模式为该用户创建新 tenant，则在 tenant setup 中执行：

1. 创建 tenant schema。
2. 跑 tenant migration。
3. 执行 Onyx 默认 setup。
4. 执行 `seed_consumer_default_llm_provider()`。
5. 创建 `LLMProvider(provider="openai_compatible", name="Qwen")`。
6. 创建允许展示的 `ModelConfiguration`。
7. 设置默认 chat model flow。
8. 可选：设置 deep research / build / title generation 等场景默认模型。

### 6.2 已存在 tenant

需要提供一个 idempotent 同步函数，用于已有 tenant 补齐或更新默认模型目录。

函数必须具备幂等性：

- provider 已存在则更新，不重复创建。
- model 已存在则更新可见性和显示名。
- 被平台下架的模型可置为不可见，不直接删除，避免历史记录引用失效。
- 默认模型不存在时才重设；除非平台配置要求强制覆盖。

### 6.3 单租户 self-hosted

如果 `MULTI_TENANT=false`，同样可以在 `public` schema 中 seed 一套 Qwen provider。所有账号共享这套配置。

---

## 7. 用户选择模型的设计

### 7.1 UI 原则

C 端模型选择入口放在聊天输入框附近或用户设置中，避免进入 AdminPanel。第一期推荐做一个轻量选择器：

- 默认：均衡
- 可选：快速 / 均衡 / 深度 / 编程
- 多模态在用户上传图片时自动出现或自动切换

### 7.2 API 设计方向

新增面向普通用户的 API，而不是复用 admin provider API：

```text
GET /api/model-catalog
GET /api/user/model-preference
PUT /api/user/model-preference
```

返回给前端的数据只包含非敏感信息：

```json
{
  "default_profile_id": "balanced",
  "profiles": [
    {
      "id": "fast",
      "label": "快速",
      "description": "适合日常问答，响应更快",
      "supports_image": false
    },
    {
      "id": "balanced",
      "label": "均衡",
      "description": "默认推荐，质量和速度平衡",
      "supports_image": false
    }
  ]
}
```

不返回真实 API key、base URL、provider id、成本参数。

### 7.3 调用链选择逻辑

用户请求进入聊天/深度研究/Craft 时：

1. 读取用户选择的 `profile_id`。
2. 根据当前场景解析到具体 provider/model。
3. 合并服务端控制的参数策略。
4. 调用现有 LLM factory / model resolver。

如果用户没有选择，使用平台默认 profile。若用户选择的 profile 已下架，则回退到 `balanced`。

---

## 8. 参数控制策略

模型参数不让用户直接配置。平台定义 profile-level defaults，并允许场景覆盖。

示例策略：

| profile | model | temperature | max_tokens | 说明 |
|---|---|---:|---:|---|
| fast | qwen-turbo | 0.7 | 2048 | 快速轻问答 |
| balanced | qwen-plus | 0.5 | 4096 | 默认聊天 |
| deep | qwen-max | 0.3 | 8192 | 深度推理和报告 |
| coding | qwen3-coder-plus | 0.2 | 8192 | 代码与 Craft |
| vision | qwen-vl-plus | 0.4 | 4096 | 图片理解 |

场景覆盖：

- 深度研究：优先 `deep`，更低 temperature，更高 token 上限。
- Craft：优先 `coding`，并开启适合工具调用的模型。
- 标题生成/摘要：使用 `fast`，降低成本。
- 普通聊天：使用用户偏好，默认 `balanced`。

---

## 9. 权限与 AdminPanel 策略

普通 C 端用户：

- 可以使用模型。
- 可以选择模型档位。
- 不可以访问 `/admin/configuration/language-models`。
- 不可以创建、编辑、删除 LLM Provider。

平台运营账号：

- 可以配置平台默认 provider。
- 可以调整 Consumer Model Catalog。
- 可以触发同步已有 tenant 的默认模型目录。

当前阶段可以先用环境变量和代码配置维护平台目录，不急着做运营后台。

---

## 10. 错误处理与降级

需要覆盖以下情况：

1. **平台未配置 API key**
   - tenant seed 跳过 provider 创建。
   - 管理日志明确提示缺少 `CONSUMER_DEFAULT_LLM_API_KEY`。
   - 用户侧显示“模型服务暂不可用”，不要暴露配置细节。

2. **用户选择的 profile 不存在**
   - 自动回退到 `balanced`。
   - 若 `balanced` 也不存在，回退到 tenant 默认 provider。

3. **模型调用失败**
   - 保留现有 LLM 错误处理。
   - 对 C 端展示友好错误。
   - 后台记录 provider/model/profile/tenant/user 维度，便于排查。

4. **平台调整模型目录**
   - 新 tenant 使用新目录。
   - 老 tenant 通过同步任务补齐。
   - 下架模型置为不可见，避免历史会话失效。

---

## 11. 数据与隐私边界

LLM Provider key 是平台密钥，必须只存在后端 encrypted storage 或环境变量中。前端永远不返回密钥、base URL、真实 provider 配置。

用户偏好只存 profile id，不存真实 provider key。若未来开放 BYOK，应作为独立高级功能处理，不能混入 C 端默认 provider 流程。

---

## 12. 实施分期

### Phase 1：平台默认 Qwen Provider seed

- 新增 Consumer Model Catalog。
- 新增 Qwen OpenAI-compatible env 配置。
- 新增 tenant 初始化 seed 函数。
- 新 tenant 自动创建 Qwen provider 和模型列表。
- 单租户 public schema 也能初始化。

### Phase 2：普通用户模型选择

- 新增 `/api/model-catalog`。
- 新增用户默认 profile 读取和保存。
- 前端聊天入口增加模型选择器。
- 普通用户不接触 AdminPanel。

### Phase 3：场景化模型策略

- 普通聊天、深度研究、Craft、标题生成分别使用合适 profile。
- 服务端统一解析 profile 到 provider/model/params。
- 增加成本和失败日志维度。

### Phase 4：平台运营能力

- 支持同步已有 tenant。
- 支持调整模型可见性。
- 支持灰度切换默认模型。
- 再考虑运营后台。

---

## 13. 测试策略

### Unit Tests

- Consumer Model Catalog 解析和默认 profile 校验。
- profile 下架后的回退逻辑。
- provider seed 幂等性。
- 参数策略解析。

### External Dependency Unit Tests

- 在真实 Postgres tenant schema 下验证：
  - 新 tenant seed 后存在 Qwen provider。
  - model configurations 正确可见。
  - default model flow 正确。
  - 重复执行 seed 不重复创建。

### Integration Tests

- 注册新用户后，登录进入聊天，默认模型可用。
- 普通用户不能访问 admin LLM provider API。
- 切换模型偏好后，新会话使用对应 profile。

### Playwright Tests

- C 端聊天页展示模型选择器。
- 不出现 API key / provider configuration 字段。
- 非 admin 用户无法进入 `/admin/configuration/language-models`。

---

## 14. 风险与取舍

### 风险 1：每个 tenant 都复制 provider 配置

这是复用 Onyx 架构的代价。第一期可接受。后续如果 tenant 数量很大，可引入平台级 provider 引用或同步任务优化。

### 风险 2：Qwen OpenAI-compatible 行为与 OpenAI 不完全一致

需要验证 tool calling、streaming、vision、多轮上下文、错误格式。Onyx 已有 XML tool-call fallback，对国产模型是加分项。

### 风险 3：用户选择模型会增加成本不确定性

通过 profile 限制解决：用户不能任意选所有模型，只能选平台定义的档位。深度模型可以结合会员/积分体系限制。

### 风险 4：AdminPanel 与 C 端体验混杂

短期需要隐藏普通用户 admin 入口。长期应把“平台模型配置”和“用户模型选择”彻底分成两个产品面。

---

## 15. 不做的事

第一期不做：

- 用户自带 API key。
- 用户自定义 base URL。
- 用户自定义 temperature/max tokens。
- 新增独立 Qwen provider 类型。
- 模型运营后台。
- 全量计费系统。
- 替换 Onyx LLM 调用链。

---

## 16. 验收标准

1. 新注册用户无需手动配置 LLM，即可使用默认 Qwen 模型聊天。
2. 新 tenant 中自动存在平台预置 Qwen provider 和模型列表。
3. 普通用户只能选择平台允许的模型档位。
4. 用户无法看到或修改 provider 密钥、base URL、模型参数。
5. 平台可以通过配置调整默认模型和模型目录。
6. 重复执行 seed 不产生重复 provider/model。
7. 当平台默认模型不可用时，有明确回退和用户友好错误。

---

## 17. 后续实施建议

实施时先做最小闭环：

1. 用 env + catalog 固定 Qwen OpenAI-compatible provider。
2. 在 tenant setup 后 seed provider。
3. 本地重新注册一个账号验证是否自动可用。
4. 再做 C 端模型选择器。
5. 最后把不同场景接入 profile 策略。

这样可以先把“注册即能用”的 C 端体验打通，再逐步美化模型选择和运营能力。
