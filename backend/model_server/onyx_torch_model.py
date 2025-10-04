import json
import os
from typing import cast
from typing import TYPE_CHECKING

import torch
import torch.nn as nn


if TYPE_CHECKING:
    from transformers import DistilBertConfig  # type: ignore


class HybridClassifier(nn.Module):
    def __init__(self) -> None:
        from transformers import DistilBertConfig, DistilBertModel

        super().__init__()
        config = DistilBertConfig()
        self.distilbert = DistilBertModel(config)
        config = self.distilbert.config  # type: ignore

        # Keyword tokenwise binary classification layer
        self.keyword_classifier = nn.Linear(config.dim, 2)

        # Intent Classifier layers
        self.pre_classifier = nn.Linear(config.dim, config.dim)
        self.intent_classifier = nn.Linear(config.dim, 2)

        self.device = torch.device("cpu")

    def forward(
        self,
        query_ids: torch.Tensor,
        query_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = self.distilbert(input_ids=query_ids, attention_mask=query_mask)  # type: ignore
        sequence_output = outputs.last_hidden_state

        # Intent classification on the CLS token
        cls_token_state = sequence_output[:, 0, :]
        pre_classifier_out = self.pre_classifier(cls_token_state)
        intent_logits = self.intent_classifier(pre_classifier_out)

        # Keyword classification on all tokens
        token_logits = self.keyword_classifier(sequence_output)

        return {"intent_logits": intent_logits, "token_logits": token_logits}

    @classmethod
    def from_pretrained(cls, load_directory: str) -> "HybridClassifier":
        model_path = os.path.join(load_directory, "pytorch_model.bin")
        config_path = os.path.join(load_directory, "config.json")

        with open(config_path, "r") as f:
            config = json.load(f)
        model = cls(**config)

        if torch.backends.mps.is_available():
            # Apple silicon GPU
            device = torch.device("mps")
        elif torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")

        model.load_state_dict(torch.load(model_path, map_location=device))
        model = model.to(device)

        model.device = device

        model.eval()
        # Eval doesn't set requires_grad to False, do it manually to save memory and have faster inference
        for param in model.parameters():
            param.requires_grad = False

        return model


class ConnectorClassifier(nn.Module):
    def __init__(self, config: "DistilBertConfig") -> None:
        from transformers import DistilBertTokenizer, DistilBertModel

        super().__init__()

        self.config = config
        self.distilbert = DistilBertModel(config)
        config = self.distilbert.config  # type: ignore
        self.connector_global_classifier = nn.Linear(config.dim, 1)
        self.connector_match_classifier = nn.Linear(config.dim, 1)
        self.tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")

        # Token indicating end of connector name, and on which classifier is used
        self.connector_end_token_id = self.tokenizer.get_vocab()[
            self.config.connector_end_token
        ]

        self.device = torch.device("cpu")

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        hidden_states = self.distilbert(  # type: ignore
            input_ids=input_ids, attention_mask=attention_mask
        ).last_hidden_state

        cls_hidden_states = hidden_states[
            :, 0, :
        ]  # Take leap of faith that first token is always [CLS]
        global_logits = self.connector_global_classifier(cls_hidden_states).view(-1)
        global_confidence = torch.sigmoid(global_logits).view(-1)

        connector_end_position_ids = input_ids == self.connector_end_token_id
        connector_end_hidden_states = hidden_states[connector_end_position_ids]
        classifier_output = self.connector_match_classifier(connector_end_hidden_states)
        classifier_confidence = torch.nn.functional.sigmoid(classifier_output).view(-1)

        return global_confidence, classifier_confidence

    @classmethod
    def from_pretrained(cls, repo_dir: str) -> "ConnectorClassifier":
        from transformers import DistilBertConfig

        config = cast(
            DistilBertConfig,
            DistilBertConfig.from_pretrained(os.path.join(repo_dir, "config.json")),
        )
        device = (
            torch.device("cuda")
            if torch.cuda.is_available()
            else (
                torch.device("mps")
                if torch.backends.mps.is_available()
                else torch.device("cpu")
            )
        )
        state_dict = torch.load(
            os.path.join(repo_dir, "pytorch_model.pt"),
            map_location=device,
            weights_only=True,
        )

        model = cls(config)
        model.load_state_dict(state_dict)
        model.to(device)
        model.device = device
        model.eval()

        for param in model.parameters():
            param.requires_grad = False

        return model
