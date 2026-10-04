"""C-only class weighting around the verified elementwise classification focal loss."""
import torch
from focal_trainer import ClassificationFocalLoss, FocalDetectionTrainer


class HazardWeightedFocalLoss(ClassificationFocalLoss):
    def forward(self, logits, targets):
        weights = logits.new_ones(12)
        weights[7], weights[10] = 4.0, 2.0
        return super().forward(logits, targets) * weights


class HazardWeightedTrainer(FocalDetectionTrainer):
    def _setup_train(self):
        super()._setup_train()
        assert self.model.criterion.nc == 12
        self.model.criterion.bce = HazardWeightedFocalLoss()
        print("CME-OPT2-C weighted classification focal ACTIVE: chemical=4 smoke=2 others=1; gamma=1.5 alpha=.25; box/DFL unchanged", flush=True)
