"""
cnn_rnn_detector.py — Hybrid CNN-BiLSTM Voice Cloning Detector.

Architecture (based on IJERT 2026 paper + wav2vec2 backbone):

  Input: log-Mel spectrogram sequence [batch, time, n_mels]

  CNN Encoder:
    Conv1D(80, 128, k=3) → BN → ReLU
    Conv1D(128, 256, k=5) → BN → ReLU → MaxPool(2)
    Conv1D(256, 256, k=3) → BN → ReLU
    Residual connections between conv blocks

  BiLSTM:
    2 layers, hidden=256, bidirectional=True, dropout=0.3

  Attention:
    Self-attention over time steps → weighted sum → context vector

  Classifier:
    Linear(512, 256) → ReLU → Dropout(0.3)
    Linear(256, 128) → ReLU → Dropout(0.3)
    Linear(128, 1) → Sigmoid

Output: P(synthetic) ∈ [0.0, 1.0] per sample

Also supports fused_vector mode (flat feature input for lightweight inference).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.error("PyTorch not available — CNN-RNN detector disabled.")


if _TORCH_AVAILABLE:

    class ConvBlock(nn.Module):
        """Conv1D + BatchNorm + ReLU with optional residual connection."""

        def __init__(
            self,
            in_channels: int,
            out_channels: int,
            kernel_size: int,
            stride: int = 1,
            padding: Optional[int] = None,
            use_residual: bool = False,
        ):
            super().__init__()
            if padding is None:
                padding = kernel_size // 2
            self.conv = nn.Conv1d(
                in_channels, out_channels, kernel_size,
                stride=stride, padding=padding,
            )
            self.bn = nn.BatchNorm1d(out_channels)
            self.relu = nn.ReLU(inplace=True)
            self.use_residual = use_residual
            if use_residual and in_channels != out_channels:
                self.residual_proj = nn.Conv1d(in_channels, out_channels, 1)
            else:
                self.residual_proj = None

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            residual = x
            out = self.relu(self.bn(self.conv(x)))
            if self.use_residual:
                if self.residual_proj is not None:
                    residual = self.residual_proj(residual)
                out = out + residual
            return out


    class SelfAttention(nn.Module):
        """Scaled dot-product self-attention over time steps."""

        def __init__(self, hidden_dim: int):
            super().__init__()
            self.query = nn.Linear(hidden_dim, hidden_dim)
            self.key = nn.Linear(hidden_dim, hidden_dim)
            self.value = nn.Linear(hidden_dim, hidden_dim)
            self.scale = hidden_dim ** -0.5

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # x: [batch, time, hidden_dim]
            Q = self.query(x)
            K = self.key(x)
            V = self.value(x)

            attn_weights = torch.softmax(
                torch.bmm(Q, K.transpose(1, 2)) * self.scale, dim=-1
            )  # [batch, time, time]

            context = torch.bmm(attn_weights, V)  # [batch, time, hidden_dim]
            # Mean over time → single context vector
            return context.mean(dim=1)  # [batch, hidden_dim]


    class CnnRnnDetector(nn.Module):
        """
        Hybrid CNN-BiLSTM detector for voice cloning detection.

        Two input modes:
          1. Sequence mode (default): input is log-Mel [batch, time, n_mels]
          2. Fused mode: input is flat feature vector [batch, feature_dim]
        """

        def __init__(
            self,
            n_mels: int = 80,
            cnn_channels: Tuple[int, int, int] = (128, 256, 256),
            lstm_hidden: int = 256,
            lstm_layers: int = 2,
            lstm_dropout: float = 0.3,
            fc_hidden: int = 256,
            fc_dropout: float = 0.3,
            fused_input_dim: Optional[int] = None,
        ):
            super().__init__()
            self.n_mels = n_mels
            self.fused_input_dim = fused_input_dim

            if fused_input_dim is not None:
                # Lightweight path: flat feature → classifier
                self.feature_proj = nn.Sequential(
                    nn.Linear(fused_input_dim, 512),
                    nn.ReLU(),
                    nn.Dropout(fc_dropout),
                    nn.Linear(512, lstm_hidden * 2),
                    nn.ReLU(),
                )
                cnn_out_channels = lstm_hidden * 2
                self.cnn_blocks = None
                self.pool = None
            else:
                # CNN path from spectrograms
                self.feature_proj = None
                c1, c2, c3 = cnn_channels
                self.cnn_blocks = nn.Sequential(
                    ConvBlock(n_mels, c1, kernel_size=3, use_residual=False),
                    ConvBlock(c1, c2, kernel_size=5, use_residual=False),
                    nn.MaxPool1d(kernel_size=2, stride=2),
                    ConvBlock(c2, c3, kernel_size=3, use_residual=True),
                )
                cnn_out_channels = c3
                self.pool = None

            # BiLSTM
            self.lstm = nn.LSTM(
                input_size=cnn_out_channels,
                hidden_size=lstm_hidden,
                num_layers=lstm_layers,
                batch_first=True,
                bidirectional=True,
                dropout=lstm_dropout if lstm_layers > 1 else 0.0,
            )
            lstm_out_dim = lstm_hidden * 2  # bidirectional

            # Self-attention
            self.attention = SelfAttention(lstm_out_dim)

            # Classifier head
            self.classifier = nn.Sequential(
                nn.Linear(lstm_out_dim, fc_hidden),
                nn.ReLU(),
                nn.Dropout(fc_dropout),
                nn.Linear(fc_hidden, 128),
                nn.ReLU(),
                nn.Dropout(fc_dropout),
                nn.Linear(128, 1),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            """
            Args:
                x: [batch, time, n_mels] for sequence mode
                   OR [batch, feature_dim] for fused mode

            Returns:
                [batch, 1] — P(synthetic) before sigmoid
            """
            if self.fused_input_dim is not None:
                # Fused path: project to LSTM input, unsqueeze time dim
                projected = self.feature_proj(x)  # [batch, lstm_hidden*2]
                projected = projected.unsqueeze(1)  # [batch, 1, lstm_hidden*2]
                lstm_input = projected
            else:
                # Sequence path: x is [batch, time, n_mels]
                # CNN expects [batch, channels, time]
                x_t = x.transpose(1, 2)  # [batch, n_mels, time]
                cnn_out = self.cnn_blocks(x_t)  # [batch, c3, time']
                lstm_input = cnn_out.transpose(1, 2)  # [batch, time', c3]

            lstm_out, _ = self.lstm(lstm_input)  # [batch, time', 2*hidden]
            context = self.attention(lstm_out)   # [batch, 2*hidden]
            logit = self.classifier(context)     # [batch, 1]
            return logit

        def predict_proba(self, x: "torch.Tensor") -> "torch.Tensor":
            """Return P(synthetic) in [0, 1] via sigmoid."""
            return torch.sigmoid(self.forward(x))


    class EnsembleDetector(nn.Module):
        """
        Ensemble of the CNN-RNN detector operating on both sequence
        and fused feature modalities, combined via learned gating.
        """

        def __init__(self, n_mels: int = 80, fused_dim: int = 1167):
            super().__init__()
            self.seq_detector = CnnRnnDetector(n_mels=n_mels)
            self.fused_detector = CnnRnnDetector(fused_input_dim=fused_dim)
            self.gate = nn.Sequential(
                nn.Linear(2, 4),
                nn.ReLU(),
                nn.Linear(4, 2),
                nn.Softmax(dim=-1),
            )

        def forward(
            self,
            mel_seq: "torch.Tensor",
            fused_vec: "torch.Tensor",
        ) -> "torch.Tensor":
            """
            Args:
                mel_seq:    [batch, time, n_mels]
                fused_vec:  [batch, fused_dim]

            Returns:
                [batch, 1] ensemble P(synthetic) before sigmoid
            """
            logit_seq = self.seq_detector(mel_seq)      # [batch, 1]
            logit_fused = self.fused_detector(fused_vec) # [batch, 1]

            combined = torch.cat([logit_seq, logit_fused], dim=-1)  # [batch, 2]
            weights = self.gate(combined.detach())  # [batch, 2]

            weighted = (weights[:, 0:1] * logit_seq +
                        weights[:, 1:2] * logit_fused)
            return weighted

        def predict_proba(
            self,
            mel_seq: "torch.Tensor",
            fused_vec: "torch.Tensor",
        ) -> "torch.Tensor":
            return torch.sigmoid(self.forward(mel_seq, fused_vec))

else:
    # Fallback stubs when torch is unavailable
    class CnnRnnDetector:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyTorch is required for CnnRnnDetector.")

    class EnsembleDetector:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyTorch is required for EnsembleDetector.")
