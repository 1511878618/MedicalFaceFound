"""Calibration block and research tier assignment: formula, boundaries and plumbing."""
import csv
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch import nn

from medicalfacefound.inference import assign_tiers, calibrate_probabilities
from medicalfacefound.inference.predict import predict_values

A = 1.6352888539610513
B = 2.741584860936987
TIERS = ["Very low", "Low", "Moderate", "High"]
CFG = {
    "task": "ocad", "task_type": "classification", "num_classes": 2,
    "calibration": {"a": A, "b": B, "eps": 1e-06},
    "stratification": {"cutoffs": [0.3, 0.5, 0.7], "labels": TIERS, "comparator": ">="},
}


class ConstantLogits(nn.Module):
    def forward(self, x):
        return torch.tensor([[-1.0, 1.0]]).repeat(len(x), 1)


def expected(p):
    x = math.log(p / (1 - p))
    return 1.0 / (1.0 + math.exp(-(A * x + B)))


class Calibration(unittest.TestCase):
    def test_matches_platt_formula(self):
        for p in (0.02, 0.35, 0.5, 0.83, 0.995):
            self.assertAlmostEqual(float(calibrate_probabilities(p, CFG)), expected(p), places=12)

    def test_extremes_are_clipped_not_infinite(self):
        values = calibrate_probabilities(np.array([0.0, 1.0]), CFG)
        self.assertTrue(np.isfinite(values).all())
        self.assertGreater(values[1], values[0])

    def test_absent_block_returns_none(self):
        self.assertIsNone(calibrate_probabilities(0.5, {"task_type": "classification"}))
        self.assertIsNone(assign_tiers(0.5, {"task_type": "classification"}))


class Tiers(unittest.TestCase):
    def test_boundaries_are_inclusive(self):
        cases = {0.2999: "Very low", 0.3: "Low", 0.4999: "Low", 0.5: "Moderate",
                 0.6999: "Moderate", 0.7: "High", 1.0: "High", 0.0: "Very low"}
        for p, tier in cases.items():
            self.assertEqual(assign_tiers(p, CFG), tier, msg=p)

    def test_array_input_keeps_order(self):
        self.assertEqual(assign_tiers([0.1, 0.4, 0.6, 0.9], CFG), TIERS)

    def test_strict_comparator_shifts_boundary(self):
        cfg = {"stratification": {"cutoffs": [0.3, 0.5, 0.7], "labels": TIERS, "comparator": ">"}}
        self.assertEqual(assign_tiers(0.3, cfg), "Very low")
        self.assertEqual(assign_tiers(0.31, cfg), "Low")

    def test_invalid_configs_rejected(self):
        bad = [
            {"stratification": {"cutoffs": [0.5, 0.3], "labels": TIERS}},
            {"stratification": {"cutoffs": [0.3, 0.5], "labels": TIERS}},
            {"stratification": {"cutoffs": [0.3], "labels": TIERS, "comparator": "="}},
            {"calibration": {"a": -1.0, "b": 0.0}},
            {"calibration": {"a": 1.0}},
        ]
        for cfg in bad:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                (calibrate_probabilities if "calibration" in cfg else assign_tiers)(0.4, cfg)


class PredictValuesPlumbing(unittest.TestCase):
    def test_raw_output_unchanged_without_blocks(self):
        cfg = {"task": "old", "task_type": "classification"}
        row = predict_values(ConstantLogits(), cfg, [np.zeros((256, 256, 3), np.uint8)])[0]
        self.assertEqual(set(row), {"task", "value", "unit"})
        self.assertAlmostEqual(row["value"], 0.880797, places=6)

    def test_calibrated_fields_added_per_image(self):
        rows = predict_values(ConstantLogits(), CFG, [np.zeros((256, 256, 3), np.uint8)] * 3)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertAlmostEqual(row["value_calibrated"], expected(row["value"]), places=12)
            self.assertEqual(row["risk_tier"], assign_tiers(row["value_calibrated"], CFG))

    def test_calibration_without_stratification(self):
        cfg = {k: v for k, v in CFG.items() if k != "stratification"}
        row = predict_values(ConstantLogits(), cfg, [np.zeros((256, 256, 3), np.uint8)])[0]
        self.assertIn("value_calibrated", row)
        self.assertNotIn("risk_tier", row)


class TaskGroups(unittest.TestCase):
    def test_part2_index_and_folder_resolution(self):
        import json
        import tempfile
        from pathlib import Path

        from medicalfacefound.inference.predict import load_task, load_tasks_index

        with tempfile.TemporaryDirectory() as d:
            for group in ("tasks_binary", "tasks_part3"):
                folder = Path(d) / group
                folder.mkdir()
                (folder / "tasks.json").write_text(json.dumps({"tasks": [{"task": "X"}]}))
            self.assertEqual(load_tasks_index(local_dir=d, task_group="tasks_binary")["tasks"][0]["task"], "X")
            with self.assertRaises(FileNotFoundError):
                load_task("Missing", local_dir=d, task_group="tasks_binary")
        with self.assertRaises(ValueError):
            load_tasks_index(local_dir="/tmp", task_group="tasks_part9")


class CliColumns(unittest.TestCase):
    def _run(self, cfg, out):
        from PIL import Image

        from medicalfacefound.inference import cli

        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "crop.jpg"
            Image.fromarray(np.zeros((256, 256, 3), np.uint8)).save(image)
            rows = [{"task": cfg["task"], "value": 0.5, "unit": "prob"}]
            if "calibration" in cfg:
                rows[0]["value_calibrated"] = 0.62
            if "stratification" in cfg:
                rows[0]["risk_tier"] = "High"
            with patch.object(cli, "load_task", return_value=(None, cfg)), \
                    patch.object(cli, "predict_values", return_value=rows):
                args = cli.build_parser().parse_args(
                    ["predict", "--input", str(image), "--task", cfg["task"],
                     "--no-crop", "--out", str(out)])
                cli.cmd_predict(args)
        with open(out, newline="", encoding="utf-8") as fh:
            return next(csv.reader(fh))

    def test_columns_added_when_config_has_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            header = self._run(CFG, Path(d) / "out.csv")
        self.assertEqual(header, ["file", "task", "value", "unit", "value_calibrated", "risk_tier"])

    def test_columns_absent_for_plain_config(self):
        with tempfile.TemporaryDirectory() as d:
            header = self._run({"task": "old", "task_type": "classification"}, Path(d) / "out.csv")
        self.assertEqual(header, ["file", "task", "value", "unit"])


if __name__ == "__main__":
    unittest.main()
