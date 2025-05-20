from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.configs.chat_configs import HYBRID_ALPHA
from onyx.configs.chat_configs import HYBRID_ALPHA_KEYWORD
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)


class SearchEvalConfig(BaseModel):
    hybrid_alpha: float
    hybrid_alpha_keyword: float
    doc_time_decay: float
    num_returned_hits: int
    rank_profile: QueryExpansionType
    offset: int
    title_content_ratio: float
    user_email: str | None
    skip_rerank: bool
    eval_topk: int
    export_folder: str


def load_config() -> SearchEvalConfig:
    """Loads the search evaluation configs from the config file."""
    # open the config file
    current_dir = Path(__file__).parent
    config_path = current_dir / "search_eval_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Search eval config file not found at {config_path}")
    with config_path.open("r") as file:
        config_raw = yaml.safe_load(file)

    # create the export folder
    export_folder = config_raw.get("EXPORT_FOLDER", "eval-%Y-%m-%d-%H-%M-%S")
    export_folder = datetime.now().strftime(export_folder)
    export_path = Path(export_folder)
    export_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created export folder: {export_path}")

    # create the config
    config = SearchEvalConfig(
        hybrid_alpha=config_raw.get("HYBRID_ALPHA", HYBRID_ALPHA),
        hybrid_alpha_keyword=config_raw.get(
            "HYBRID_ALPHA_KEYWORD", HYBRID_ALPHA_KEYWORD
        ),
        doc_time_decay=config_raw.get("DOC_TIME_DECAY", DOC_TIME_DECAY),
        num_returned_hits=config_raw.get("NUM_RETURNED_HITS", NUM_RETURNED_HITS),
        rank_profile=config_raw.get("RANK_PROFILE", QueryExpansionType.SEMANTIC),
        offset=config_raw.get("OFFSET", 0),
        title_content_ratio=config_raw.get("TITLE_CONTENT_RATIO", TITLE_CONTENT_RATIO),
        user_email=config_raw.get("USER_EMAIL"),
        skip_rerank=config_raw.get("SKIP_RERANK", False),
        eval_topk=config_raw.get("EVAL_TOPK", 5),
        export_folder=export_folder,
    )
    logger.info(f"Using search parameters: {config}")

    # export the config
    config_file = export_path / "search_eval_config.yaml"
    with config_file.open("w") as file:
        config_dict = config.model_dump(mode="python")
        config_dict["rank_profile"] = config.rank_profile.value
        yaml.dump(config_dict, file, sort_keys=False)
    logger.info(f"Exported config to {config_file}")

    return config
