"""Frozen-backbone downstream MLP heads; no experiment/training dependencies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch
from torch import nn


class MLPHead(nn.Module):
    def __init__(self, dim=1536, hidden=512, n_out=2, dropout=0.2, eps=1e-5):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(dim, eps=eps), nn.Linear(dim, hidden),
                                 nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden, n_out))

    def forward(self, x):
        # The cache was stored as float32 after fp16 backbone extraction.
        return self.net(x.float())


def prepare_input(image, size=256):
    from PIL import Image
    from torchvision import transforms

    transform = transforms.Compose([
        transforms.Resize(size, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(size), transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    return transform(Image.fromarray(image).convert('RGB')).numpy()


def resolve_file(repo, local_dir, relative):
    if local_dir is not None:
        return Path(local_dir) / relative
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(repo, relative))


def load_mlp_task(task, repo, local_dir, device, task_group='tasks_binary', cfg=None):
    from safetensors.torch import load_file
    from medicalfacefound.utils.models_swin import swin_large_512to256

    prefix = f'{task_group}/{task}'
    if cfg is None:
        cfg = json.loads(resolve_file(repo, local_dir, f'{prefix}/config.json').read_text())
    if cfg.get('format') != 'head_only' or cfg.get('task') != task:
        raise ValueError('invalid head-only task config')
    h = cfg['head']
    if h['type'] != 'mlp' or h['input_dim'] != 1536 or cfg['num_classes'] != 2:
        raise ValueError('unsupported MLP dimensions or class count')
    if cfg['output_class_index'] not in (0, 1):
        raise ValueError('output_class_index must be 0 or 1')
    head_path = resolve_file(repo, local_dir, f'{prefix}/model.safetensors')
    if hashlib.sha256(head_path.read_bytes()).hexdigest() != cfg['sha256']:
        raise ValueError('MLP head checksum mismatch')
    # Pin the known shared backbone path; public configs cannot traverse outside the repo.
    backbone = resolve_file(repo, local_dir, 'backbone/model.safetensors')
    if cfg['backbone']['path'] != 'backbone/model.safetensors':
        raise ValueError('unsupported backbone path')
    digest = _sha256(backbone)
    if digest != cfg['backbone']['sha256']:
        raise ValueError('backbone checksum mismatch')
    model = swin_large_512to256(num_classes=0)
    model.fc_norm = nn.Identity()
    # Identity fc_norm/head: no missing keys are tolerated, including normalization keys.
    model.load_state_dict(load_file(str(backbone)), strict=True)
    head = MLPHead(h['input_dim'], h['hidden_dim'], cfg['num_classes'], h['dropout'], h['norm_eps'])
    head.load_state_dict(load_file(str(head_path)), strict=True)
    model.head = head
    model.to(device).eval()
    return model, cfg


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
