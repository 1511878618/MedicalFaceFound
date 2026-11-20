"""Export loader failure gates with a compact real fixture, not a large Swin."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import torch
from torch import nn
from safetensors.torch import save_file
from medicalfacefound.inference.head_only import MLPHead
from medicalfacefound.inference.predict import load_task

class TinyBackbone(nn.Module):
    def __init__(self, **kwargs):
        super().__init__()
        self.fc_norm=nn.LayerNorm(1536)
        self.head=nn.Identity()

class ExportLoader(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.h=self.root/'tasks_binary/ocad';self.h.mkdir(parents=True)
        (self.root/'backbone').mkdir()
        self.b=self.root/'backbone/model.safetensors'
        save_file({},str(self.b))
        save_file(MLPHead().state_dict(),str(self.h/'model.safetensors'))
        self.cfg={'task':'ocad','format':'head_only','num_classes':2,'output_class_index':1,
                  'head':{'type':'mlp','input_dim':1536,'hidden_dim':512,'dropout':.2,'norm_eps':1e-5},
                  'backbone':{'path':'backbone/model.safetensors','sha256':hashlib.sha256(self.b.read_bytes()).hexdigest()},
                  'sha256':hashlib.sha256((self.h/'model.safetensors').read_bytes()).hexdigest()}
        self.config()
    def config(self):
        (self.h/'config.json').write_text(json.dumps(self.cfg))
    def tearDown(self): self.tmp.cleanup()
    def load(self):
        with patch('medicalfacefound.utils.models_swin.swin_large_512to256',TinyBackbone):
            return load_task('ocad',local_dir=self.root,task_group='tasks_binary')
    def test_strict_head_load_and_no_double_norm(self):
        model,cfg=self.load()
        self.assertIsInstance(model.fc_norm,nn.Identity)
        self.assertEqual(model.head.net[0].eps,1e-5)
        self.assertFalse(model.training)
        self.assertEqual(model.head(torch.zeros(2,1536)).shape,(2,2))
    def test_remote_resolution_without_network(self):
        def download(repo, relative):
            self.assertEqual(repo, 'owner/repo')
            return str(self.root / relative)
        with patch('huggingface_hub.hf_hub_download', side_effect=download) as get:
            with patch('medicalfacefound.utils.models_swin.swin_large_512to256', TinyBackbone):
                model, cfg=load_task('ocad',repo='owner/repo',task_group='tasks_binary')
            self.assertEqual(len(get.call_args_list), 3)
            self.assertEqual(cfg['task'], 'ocad')

    def test_corrupt_head(self):
        with (self.h/'model.safetensors').open('ab') as f:f.write(b'broken')
        with self.assertRaisesRegex(ValueError,'head checksum'):self.load()
    def test_corrupt_backbone(self):
        with self.b.open('ab') as f:f.write(b'broken')
        with self.assertRaisesRegex(ValueError,'backbone checksum'):self.load()
    def test_missing_backbone(self):
        self.b.unlink()
        with self.assertRaises(FileNotFoundError):self.load()
    def test_dimension_mismatch(self):
        self.cfg['head']['input_dim']=100;self.config()
        with self.assertRaisesRegex(ValueError,'dimensions'):self.load()
    def test_unexpected_backbone_key(self):
        save_file({'bad':torch.zeros(1)},str(self.b))
        self.cfg['backbone']['sha256']=hashlib.sha256(self.b.read_bytes()).hexdigest();self.config()
        with self.assertRaises(RuntimeError):self.load()
    def test_head_shape_mismatch(self):
        save_file(MLPHead(hidden=64).state_dict(),str(self.h/'model.safetensors'))
        self.cfg['sha256']=hashlib.sha256((self.h/'model.safetensors').read_bytes()).hexdigest();self.config()
        with self.assertRaises(RuntimeError):self.load()

if __name__=='__main__':unittest.main()
