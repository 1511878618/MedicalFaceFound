"""Paper-derived display catalog, separate from installed model availability."""
from medicalfacefound.service.models import model_folder

import json
from pathlib import Path

CONSENT_VERSION = 'personal-records-2026-11-12-v2'
RESEARCH_CONSENT_VERSION = 'research-training-2026-11-12-v3'
CATALOG = {item['id']: item for item in json.loads(Path(__file__).with_name('model_catalog.json').read_text())}
REFERENCE_RANGES = json.loads(Path(__file__).with_name('reference_ranges.json').read_text())
DISCLAIMER = '只是模型预测，仅供参考和科研交流，不作为临床诊断依据，不能替代实际检验。模型仍存在误差，我们期待通过进一步验证和自愿参与的研究持续改进。'


def public_catalog(store):
    missing = store.status()['missing_dependencies']
    items = []
    for name in dict.fromkeys([*CATALOG, *store.available]):
        item = dict(CATALOG.get(name, {'id': name, 'label': name, 'unit': '', 'performance': None}))
        item['reference_range'] = dict(REFERENCE_RANGES.get(name, {'text': '', 'unit': '', 'source': '', 'conditions': '暂无参考范围'}))
        item['available'] = name in store.available and not missing
        item['availability'] = '可分析' if item['available'] else '待接入'
        item.setdefault('description', '研究性模型预测，不作为临床诊断依据。')
        if name in store.available:
            try:
                cfg = json.loads((model_folder(store.settings.weights_dir, name)/'config.json').read_text())
                item['unit'] = '岁' if name == 'Age' else cfg.get('unit', item.get('unit', ''))
                item['task_type'] = cfg.get('task_type', item.get('task_type'))
            except (OSError, ValueError):
                pass
        items.append(item)
    return items
