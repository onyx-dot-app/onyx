from pydantic import BaseModel, ConfigDict, Field


class PluginJsonFile(BaseModel):
    """Keeps the keys it does not name. A dump drops every key whose value is None,
    which is how the export removes one."""

    model_config = ConfigDict(extra="allow")

    def dump(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True, indent=2) + "\n"


class MarketplaceEntry(PluginJsonFile):
    name: str
    version: str


class Marketplace(PluginJsonFile):
    plugins: list[MarketplaceEntry]


class PluginUserOption(PluginJsonFile):
    description: str
    required: bool | None = None


class PluginManifest(PluginJsonFile):
    name: str
    version: str | None = None
    user_config: dict[str, PluginUserOption] = Field(alias="userConfig")


class McpServerEntry(PluginJsonFile):
    url: str
    headers: dict[str, str] | None = None


class McpConfig(PluginJsonFile):
    mcp_servers: dict[str, McpServerEntry] = Field(alias="mcpServers")


class HookCommand(PluginJsonFile):
    command: str


class HookGroup(PluginJsonFile):
    hooks: list[HookCommand]


class HooksFile(PluginJsonFile):
    hooks: dict[str, list[HookGroup]]
