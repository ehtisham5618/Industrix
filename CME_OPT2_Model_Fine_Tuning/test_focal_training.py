"""Verify focal classification math, gradients and upstream regression isolation."""
import unittest
from unittest.mock import Mock, patch
import torch
from torch.nn import functional as F
from ultralytics.nn.tasks import DetectionModel
from ultralytics.cfg import get_cfg
from ultralytics.utils.loss import v8DetectionLoss
from focal_trainer import ClassificationFocalLoss, FocalDetectionLoss
from gpu_idle_watchdog import watch
from weighted_trainer import HazardWeightedFocalLoss


class FocalTrainingTests(unittest.TestCase):
    def test_class_weighting_targets_only_weak_classification_channels(self):
        logits=torch.zeros(2,5,12,requires_grad=True)
        targets=torch.rand(2,5,12)
        original=ClassificationFocalLoss()(logits,targets)
        weighted=HazardWeightedFocalLoss()(logits,targets)
        torch.testing.assert_close(weighted[...,7],original[...,7]*4)
        torch.testing.assert_close(weighted[...,10],original[...,10]*2)
        torch.testing.assert_close(weighted[...,[0,1,2,3,4,5,6,8,9,11]],original[...,[0,1,2,3,4,5,6,8,9,11]])
        weighted.sum().backward()
        self.assertTrue(torch.isfinite(logits.grad).all())

    def test_idle_watchdog_stops_after_ten_continuous_minutes(self):
        process, event = Mock(), Mock()
        process.poll.return_value = None
        event.wait.return_value = False
        with patch("gpu_idle_watchdog.subprocess.check_output", return_value="0\n"), patch("gpu_idle_watchdog.time.monotonic", side_effect=[0, 600]):
            watch(process, event)
        process.terminate.assert_called_once()

    def test_gpu_activity_resets_idle_timer(self):
        process, event = Mock(), Mock()
        process.poll.return_value = None
        event.wait.return_value = False
        with patch("gpu_idle_watchdog.subprocess.check_output", side_effect=["0\n", "80\n", "0\n", "0\n"]), patch("gpu_idle_watchdog.time.monotonic", side_effect=[0, 200, 800]):
            watch(process, event)
        self.assertEqual(event.wait.call_count, 4)
        process.terminate.assert_called_once()

    def test_elementwise_math_with_soft_assigned_targets(self):
        logits = torch.tensor([-3., 0., 2.], requires_grad=True)
        targets = torch.tensor([0., 0.7, 1.])
        probability = logits.sigmoid()
        expected = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        expected *= (1 - (targets * probability + (1 - targets) * (1 - probability))).pow(1.5)
        expected *= targets * .25 + (1 - targets) * .75
        actual = ClassificationFocalLoss()(logits, targets)
        torch.testing.assert_close(actual, expected)
        actual.sum().backward()
        self.assertTrue(torch.isfinite(logits.grad).all())
        self.assertGreater(logits.grad.abs().sum().item(), 0)

    def test_easy_examples_are_downweighted(self):
        logits = torch.tensor([-10., 0., 10.])
        targets = torch.tensor([0., 1., 1.])
        result = ClassificationFocalLoss()(logits, targets)
        self.assertGreater(result[1], result[0] * 100)
        self.assertGreater(result[1], result[2] * 100)

    def test_only_classification_component_changes(self):
        torch.set_num_threads(2)
        model = DetectionModel("yolov8s.yaml", nc=12, verbose=False)
        model.args = get_cfg()
        stock, focal = v8DetectionLoss(model), FocalDetectionLoss(model)
        self.assertIsInstance(focal.bce, ClassificationFocalLoss)
        self.assertEqual(type(stock.bbox_loss), type(focal.bbox_loss))
        self.assertTrue(focal.use_dfl)
        model.train()
        predictions = model(torch.rand(2, 3, 64, 64))
        batch = {"batch_idx": torch.tensor([0., 1.]), "cls": torch.tensor([[7.], [10.]]),
                 "bboxes": torch.tensor([[.5,.5,.4,.4], [.5,.5,.3,.3]])}
        ordinary, _ = stock(predictions, batch)
        changed, _ = focal(predictions, batch)
        torch.testing.assert_close(ordinary[[0, 2]], changed[[0, 2]])
        self.assertFalse(torch.allclose(ordinary[1], changed[1]))
        changed.sum().backward()
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None))


if __name__ == "__main__":
    unittest.main()
