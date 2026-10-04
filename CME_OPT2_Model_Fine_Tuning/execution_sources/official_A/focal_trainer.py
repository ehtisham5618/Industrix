"""Classification focal loss for the pinned Ultralytics YOLOv8 detector.

Keep the upstream elementwise BCE reduction contract, task-aligned soft targets,
box loss and DFL. Upstream FocalLoss reduces across classes internally and is
therefore not a drop-in replacement for v8DetectionLoss.bce.
"""
import torch
from torch import nn
from torch.nn import functional as F
from ultralytics.models.yolo.detect import DetectionTrainer
from ultralytics.utils.loss import v8DetectionLoss


class ClassificationFocalLoss(nn.Module):
    def __init__(self, gamma=1.5, alpha=0.25):
        super().__init__()
        self.gamma, self.alpha = gamma, alpha

    def forward(self, logits, targets):
        bce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        probability = logits.sigmoid()
        pt = targets * probability + (1 - targets) * (1 - probability)
        balance = targets * self.alpha + (1 - targets) * (1 - self.alpha)
        return bce * (1 - pt).pow(self.gamma) * balance


class FocalDetectionLoss(v8DetectionLoss):
    def __init__(self, model):
        super().__init__(model)
        self.bce = ClassificationFocalLoss()


class FocalDetectionTrainer(DetectionTrainer):
    def _setup_train(self):
        super()._setup_train()
        self.model.criterion = FocalDetectionLoss(self.model)
        assert self.model.criterion.use_dfl
        print("CME-OPT2 classification focal loss ACTIVE: gamma=1.5 alpha=0.25; box/DFL unchanged", flush=True)

    def save_model(self):
        # Keep exported checkpoints loadable by the ordinary backend YOLO loader.
        objects = [self.model, self.ema.ema] if self.ema else [self.model]
        criteria = [getattr(m, "criterion", None) for m in objects]
        try:
            for model in objects:
                model.criterion = None
            super().save_model()
        finally:
            for model, criterion in zip(objects, criteria):
                model.criterion = criterion
