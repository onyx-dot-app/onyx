import json
import os

import torch
import torch.nn as nn
from transformers import DistilBertConfig  # type: ignore
from transformers import DistilBertModel


class HybridClassifier(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        config = DistilBertConfig()
        self.distilbert = DistilBertModel(config)

        # Keyword tokenwise binary classification layer
        self.keyword_classifier = nn.Linear(self.distilbert.config.dim, 2)

        # Intent Classifier layers
        self.pre_classifier = nn.Linear(
            self.distilbert.config.dim, self.distilbert.config.dim
        )
        self.intent_classifier = nn.Linear(self.distilbert.config.dim, 2)
        self.dropout = nn.Dropout(self.distilbert.config.seq_classif_dropout)

        self.device = torch.device("cpu")

    def forward(
        self,
        query_ids: torch.Tensor,
        query_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = self.distilbert(input_ids=query_ids, attention_mask=query_mask)
        sequence_output = outputs.last_hidden_state

        # Intent classification on the CLS token
        cls_token_state = sequence_output[:, 0, :]
        pre_classifier_out = self.pre_classifier(cls_token_state)
        dropout_out = self.dropout(pre_classifier_out)
        intent_logits = self.intent_classifier(dropout_out)

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
