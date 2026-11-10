"""Scientific correctness and data-integrity checks; no remote models required."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
import contextlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from medicalfacefound.robustness.datasets import build_pairs, subset_pairs, inventory
from medicalfacefound.robustness.statistics import paired_statistics, adjust_bh
from medicalfacefound.robustness.storage import discover_models, fingerprint, digest_file
from medicalfacefound.robustness.runner import summarize, duplicate_pairs


class StatisticsTests(unittest.TestCase):
    def test_constant_shift_is_not_agreement(self):
        result = paired_statistics([1, 2, 3, 4], [11, 12, 13, 14], bootstrap=100)
        self.assertAlmostEqual(result['pearson_r'], 1)
        self.assertLess(result['concordance'], .1)
        self.assertLess(result['icc_a1'], .1)
        self.assertEqual(result['mean_difference'], 10)
        self.assertEqual(result['mean_absolute_difference'], 10)
        self.assertEqual(result['mean_difference_ci_low'], 10)

    def test_direction_and_absolute_change(self):
        result = paired_statistics([1, 5], [3, 1], bootstrap=100)
        self.assertEqual(result['mean_difference'], -1)
        self.assertEqual(result['mean_absolute_difference'], 3)

    def test_perfect_agreement(self):
        result = paired_statistics([1, 2, 3], [1, 2, 3], bootstrap=100)
        self.assertEqual(result['wilcoxon_p'], 1)
        self.assertEqual(result['icc_a1'], 1)
        self.assertEqual(result['concordance'], 1)

    def test_constant_outputs_are_not_proof_of_reliability(self):
        result = paired_statistics([2, 2, 2], [2, 2, 2], bootstrap=100)
        self.assertIsNone(result['pearson_r'])
        self.assertIsNone(result['icc_a1'])

    def test_empty_singleton_and_nonfinite(self):
        self.assertEqual(paired_statistics([], []), {'n': 0})
        self.assertIsNone(paired_statistics([1], [2])['wilcoxon_p'])
        with self.assertRaises(ValueError):
            paired_statistics([1, np.nan], [2, 3])

    def test_threshold_and_tolerance(self):
        result = paired_statistics([.4, .9], [.6, .8], bootstrap=100, threshold=.5, tolerance=.15)
        self.assertEqual(result['flip_rate'], .5)
        self.assertEqual(result['fraction_within_tolerance'], .5)

    def test_bh_known_values(self):
        rows = [{'wilcoxon_p': v} for v in [.04, .001, .03, None]]
        adjust_bh(rows)
        np.testing.assert_allclose([r['wilcoxon_q_bh'] for r in rows[:3]], [.04, .003, .04])

    def test_bootstrap_reproducible(self):
        a = list(range(20)); b = np.asarray(a)**1.1
        self.assertEqual(paired_statistics(a, b, bootstrap=100, seed=7), paired_statistics(a, b, bootstrap=100, seed=7))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        for surgery in ['Eyebrow', 'Eyelid', 'Facelift', 'FacialBones', 'Nose']:
            d = self.root/'HDA-PlasticSurgery'/surgery; d.mkdir(parents=True)
            (d/'1a_b.jpg.png').touch(); (d/'1a_a.png').touch()
        makeup = self.root/'Makeup Detection Face Dataset'; makeup.mkdir()
        (makeup/'no_makeup').mkdir(); (makeup/'with_makeup').mkdir()
        (makeup/'no_makeup/0.jpg').touch(); (makeup/'with_makeup/0.jpg').touch()
        (makeup/'make_up.csv').write_text('no_makeup,with_makeup\nno_makeup/0.jpg,with_makeup/0.jpg\n')
        fei = self.root/'FEI Face Database'; fei.mkdir()
        for subject in [1, 2]:
            for i in range(1, 15):
                (fei/f'{subject}-{i:02d}.jpg').touch()
        # Distinct source bytes, including in mocked-inference tests.
        for path in self.root.rglob('*'):
            if path.suffix in {'.jpg', '.png'}:
                path.write_bytes(str(path.relative_to(self.root)).encode())

    def tearDown(self):
        self.temp.cleanup()

    def test_pairing_and_double_extensions(self):
        pairs, issues = build_pairs(self.root)
        self.assertEqual(issues, []); self.assertEqual(len(pairs), 14)
        hda = next(p for p in pairs if p['dataset'] == 'hda')
        self.assertTrue(hda['baseline'].endswith('_b.jpg.png'))
        self.assertTrue(hda['variant'].endswith('_a.png'))

    def test_missing_side_is_audited(self):
        (self.root/'HDA-PlasticSurgery/Nose/1a_a.png').unlink()
        pairs, issues = build_pairs(self.root)
        self.assertEqual(len(pairs), 13)
        self.assertEqual(issues[0]['error'], 'missing_pair_member')

    def test_duplicate_key_fails(self):
        (self.root/'HDA-PlasticSurgery/Nose/1a_a.jpg').touch()
        with self.assertRaises(ValueError):
            build_pairs(self.root)

    def test_extended_fei_all_conditions(self):
        pairs, _ = build_pairs(self.root, 'extended')
        self.assertEqual(len([p for p in pairs if p['dataset']=='fei']), 26)

    def test_subset_keeps_pairs_and_all_groups(self):
        pairs, _ = build_pairs(self.root)
        selected = subset_pairs(pairs, 1, 2026)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected, subset_pairs(pairs, 1, 2026))

    def test_changed_file_invalidates_content_fingerprint(self):
        path = self.root/'example'; path.write_bytes(b'first')
        before = digest_file(path); path.write_bytes(b'other')
        self.assertNotEqual(before, digest_file(path))
        self.assertNotEqual(fingerprint({'threshold': .9}), fingerprint({'threshold': .8}))

    def test_incomplete_and_multiclass_models_are_reported(self):
        folder = self.root/'weights/tasks/Incomplete'; folder.mkdir(parents=True)
        (folder/'config.json').write_text('{}')
        models, issues = discover_models(self.root/'weights')
        self.assertEqual(models, []); self.assertEqual(issues[0]['task'], 'Incomplete')
        (folder/'config.json').write_text(json.dumps({'task':'Incomplete','task_type':'classification','num_classes':3}))
        (folder/'model.safetensors').touch()
        models, issues = discover_models(self.root/'weights')
        self.assertEqual(models, [])
        self.assertIn('only binary', issues[0]['error'])

    def test_invalid_fei_mapping_rejected(self):
        with self.assertRaises(ValueError):
            build_pairs(self.root, fei_comparisons=[['self', '11', '11']])

    def test_resume_reuses_predictions_and_weight_change_invalidates(self):
        from medicalfacefound.robustness.runner import run, reanalyse
        folder = self.root/'weights/tasks/Age'; folder.mkdir(parents=True)
        cfg = {'task':'Age','task_type':'regression','num_classes':1,'target_mean':0,'target_std':1,'unit':'year'}
        (folder/'config.json').write_text(json.dumps(cfg))
        weight = folder/'model.safetensors'; weight.write_bytes(b'test-weights')
        detector = self.root/'detector/.deepface/weights'; detector.mkdir(parents=True)
        (detector/'retinaface.pth').write_bytes(b'test-detector')
        args = SimpleNamespace(data_root=self.root, weights_dir=self.root/'weights', output=self.root/'results',
            cache=self.root/'cache', detector_home=self.root/'detector', threads=1, seed=7, device='cpu', half=False,
            batch_size=4, protocol='primary', fei_mapping=None, limit_per_group=None, task=None, dataset=None,
            thresholds=None, preprocess='retina-align', face_threshold=.9, ratio=1.2, multi_face='reject',
            detector_max_side=640, allow_upscaling=False, retry_failures=False, bootstrap=100, command='run')
        def prediction(_model, _cfg, images, **kwargs):
            return [{'value':1.0,'unit':'year','task':'Age'} for _ in images]
        with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()), \
             patch('medicalfacefound.robustness.runner.version_info', return_value={'test':'1'}), \
             patch('medicalfacefound.robustness.preprocess.prepare', return_value=(np.zeros((256,256,3),dtype=np.uint8), {'status':'ok'})) as prep, \
             patch('medicalfacefound.inference.predict.load_task', return_value=(object(),cfg)) as loader, \
             patch('medicalfacefound.inference.predict.predict_values', side_effect=prediction) as predict, \
             patch('medicalfacefound.robustness.report.write_report'):
            self.assertEqual(run(args), 0)
            self.assertGreater(predict.call_count, 0)
            prep.reset_mock(); loader.reset_mock(); predict.reset_mock()
            self.assertEqual(run(args), 0)
            prep.assert_not_called(); loader.assert_not_called(); predict.assert_not_called()
            weight.write_bytes(b'changed-test-weights')
            self.assertEqual(run(args), 0)
            prep.assert_not_called(); loader.assert_called_once()
            self.assertGreater(predict.call_count, 0)
            prediction_hash = digest_file(args.output/'predictions.csv')
            loader.reset_mock(); predict.reset_mock()
            self.assertEqual(reanalyse(args.output), 0)
            loader.assert_not_called(); predict.assert_not_called()
            self.assertEqual(prediction_hash, digest_file(args.output/'predictions.csv'))
        report = json.loads((args.output/'summary.json').read_text())
        self.assertEqual(len(report), 10)
        self.assertTrue(all(r['n']==r['n_expected'] for r in report))

    def test_exact_duplicate_pair_is_excluded_from_statistics(self):
        pairs = [dict(pair_id=f'hda/Facelift/{i}',dataset='hda',contrast='Facelift',subject=str(i),
                      baseline=f'{i}_b',variant=f'{i}_a') for i in [64,77]]
        hashes = {'64_b':'before','77_b':'before','64_a':'after','77_a':'after'}
        self.assertEqual(duplicate_pairs(pairs,hashes), {'hda/Facelift/77':'hda/Facelift/64'})
        models = [{'task':'Age','config':{'task_type':'regression','target_std':10,'unit':'year'}}]
        preds = [dict(task='Age',path=path,value=40 if path.endswith('_b') else 42,status='ok') for path in hashes]
        paired, summary = summarize(pairs,preds,models,SimpleNamespace(bootstrap=100,seed=7),{},image_hashes=hashes)
        self.assertEqual(summary[0]['n'],1)
        self.assertEqual(summary[0]['n_expected'],2)
        self.assertEqual(summary[0]['n_duplicate_pairs'],1)
        self.assertEqual(paired[1]['status'],'duplicate_pair')
        self.assertEqual(summary[0]['mean_difference'],2)

    def test_same_baseline_or_same_images_in_different_contrasts_not_deduplicated(self):
        pairs = [dict(pair_id='a',dataset='fei',contrast='pose',subject='1',baseline='front',variant='left'),
                 dict(pair_id='b',dataset='fei',contrast='pose',subject='2',baseline='front',variant='right'),
                 dict(pair_id='c',dataset='fei',contrast='other',subject='1',baseline='front',variant='left')]
        self.assertEqual(duplicate_pairs(pairs,{'front':'f','left':'l','right':'r'}),{})

    def test_failed_image_excludes_pair_but_remains_in_denominator(self):
        pairs, _ = build_pairs(self.root)
        pair = pairs[0]
        models = [{'task': 'Age', 'config': {'task_type': 'regression', 'target_std': 10, 'unit': 'year'}}]
        preds = [{'task': 'Age', 'path': pair['baseline'], 'value': 40, 'status': 'ok'},
                 {'task': 'Age', 'path': pair['variant'], 'value': None, 'status': 'no_face'}]
        paired, summary = summarize([pair], preds, models, SimpleNamespace(bootstrap=100, seed=7), {})
        self.assertEqual(summary[0]['n_expected'], 1)
        self.assertEqual(summary[0]['n'], 0)
        self.assertEqual(summary[0]['variant_failure_rate'], 1)
        self.assertEqual(paired[0]['status'], 'excluded')


if __name__ == '__main__':
    unittest.main()
