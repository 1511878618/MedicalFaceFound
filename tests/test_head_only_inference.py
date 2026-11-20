"""Contract checks; real-photo/export parity is exercised separately."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch import nn
from safetensors.torch import save_file

from medicalfacefound.inference.predict import load_task, load_tasks_index, predict_values
from medicalfacefound.inference.cli import build_parser


class ConstantLogits(nn.Module):
    def forward(self, x):
        assert x.shape[2:] == (256, 256)
        return torch.tensor([[0., 2.]]).repeat(len(x), 1)


class HeadOnlyContract(unittest.TestCase):
    def test_moca_event_probability_and_nonsquare_input(self):
        cfg = {"task": "moca_mci", "task_type": "classification", "format": "head_only",
               "output_class_index": 0, "preprocessing": {"size": 256}}
        result = predict_values(ConstantLogits(), cfg, [np.zeros((267, 256, 3), np.uint8)])
        self.assertAlmostEqual(result[0]['value'], torch.softmax(torch.tensor([0., 2.]), 0)[0].item(), places=7)
        self.assertEqual(set(result[0]), {'task', 'value', 'unit'})

    def test_original_probability_unchanged(self):
        cfg = {"task": "old", "task_type": "classification"}
        value = predict_values(ConstantLogits(), cfg, [np.zeros((256, 256, 3), np.uint8)])[0]['value']
        self.assertAlmostEqual(value, 0.880797, places=6)

    def test_group_index_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'tasks_binary'; p.mkdir()
            (p / 'tasks.json').write_text(json.dumps({'tasks': [{'task': 'moca_mci'}]}))
            self.assertEqual(load_tasks_index(local_dir=d, task_group='tasks_binary')['tasks'][0]['task'], 'moca_mci')
        args = build_parser().parse_args(['predict', '--input', 'crop.jpg', '--all-tasks', '--task-group', 'tasks_binary'])
        self.assertEqual(args.task_group, 'tasks_binary')

    def test_invalid_group_rejected(self):
        with self.assertRaises(ValueError):
            load_tasks_index(local_dir='.', task_group='../other')

    def test_original_regression_scaling(self):
        class Regressor(nn.Module):
            def forward(self, x):
                return torch.ones((len(x), 1)) * 2
        cfg = {"task":"old", "task_type":"regression", "target_std":3., "target_mean":10., "unit":"years"}
        result = predict_values(Regressor(), cfg, [np.zeros((256,256,3), np.uint8)])
        self.assertEqual(result, [{"task":"old", "value":16., "unit":"years"}])

    def test_remote_group_index_path(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'tasks.json';p.write_text('{"tasks": []}')
            with patch('huggingface_hub.hf_hub_download', return_value=str(p)) as download:
                load_tasks_index(repo='owner/repo', task_group='tasks_binary')
                download.assert_called_once_with('owner/repo', 'tasks_binary/tasks.json')

    def test_invalid_task_path(self):
        with self.assertRaises(ValueError):
            load_task('../moca_mci', local_dir='.', task_group='tasks_binary')

    def test_empty_images(self):
        self.assertEqual(predict_values(ConstantLogits(), {'task':'old'}, []), [])


if __name__ == '__main__':
    unittest.main()
