# File: onyx/connectors/github_code/config.py

from pydantic import BaseModel, Field, SecretStr

class GitHubCodeConnectorConfig(BaseModel):
    """Configuration for GitHub Code Connector."""
    repo_owner: str = Field(..., title="Repository Owner", description="GitHub user or organization name")
    repo_name: str = Field(..., title="Repository Name", description="Name of the GitHub repository")
    branch: str = Field("main", title="Branch", description="Branch name to index (default: main)")
    access_token: SecretStr = Field(None, title="GitHub Token", description="Personal Access Token for private repos")
    include_file_patterns: list[str] = Field(
        default=["*.js", "*.ts", "*.jsx", "*.tsx", "*.rb", "*.cs", "*.fs", "*.csproj", "*.sln", "*.config", "*.xml", "*.json", "*.md"],
        title="Include File Patterns",
        description="Glob patterns for files to include in indexing (code & docs)."
    )
    exclude_dir_patterns: list[str] = Field(
        default=["node_modules/*", "vendor/*", "dist/*", "build/*", "*.min.js"],
        title="Exclude Directories",
        description="Glob patterns for folders (or files) to exclude from indexing"
    )
    model_name: str = Field(
        "codebert", 
        title="Embedding Model", 
        description="Embedding model to use: 'codebert', 'unixcoder', or external ('openai' for OpenAI API, 'cohere' for Cohere API)"
    )
    openai_model: str = Field(
        "text-embedding-ada-002", 
        title="OpenAI Embedding Model",
        description="OpenAI model name for embeddings (used if model_name='openai')"
    )
    cohere_model: str = Field(
        "embed-english-v2.0", 
        title="Cohere Embedding Model",
        description="Cohere model name for embeddings (used if model_name='cohere')"
    )
    chunk_size: int = Field(256, title="Chunk Size", description="Max tokens per chunk for sliding window")
    chunk_overlap: int = Field(50, title="Chunk Overlap", description="Token overlap between chunks for sliding window")

    # Pydantic model configuration
    class Config:
        allow_population_by_field_name = True
        # GitHub token treated as secret (will be masked in any display)
        fields = {"access_token": {"env": "GITHUB_TOKEN"}}
