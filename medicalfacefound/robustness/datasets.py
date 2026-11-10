"""Read-only dataset adapters. Pair by identity, never by directory iteration order."""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
# Working mapping, inspected on local FEI contact sheets. The paper does not
# publish filename indices, so these are deliberately NOT labelled exact degrees.
FEI_COMPARISONS = [
    ("pose_03_vs_05", "05", "03"),
    ("pose_07_vs_05", "05", "07"),
    ("smile_vs_neutral", "11", "12"),
    ("dark_vs_light", "13", "14"),
]


def build_pairs(root: Path, protocol="primary", fei_comparisons=None):
    root = root.resolve()
    pairs, issues = [], []

    def add(dataset, subject, contrast, a, b):
        if a is None or b is None or not a.is_file() or not b.is_file():
            issues.append(dict(dataset=dataset, subject=subject, contrast=contrast,
                               error="missing_pair_member", baseline=str(a), variant=str(b)))
            return
        pairs.append(dict(pair_id=f"{dataset}/{contrast}/{subject}", dataset=dataset,
                          subject=subject, contrast=contrast,
                          baseline=str(a.resolve()), variant=str(b.resolve())))

    hda = root / "HDA-PlasticSurgery"
    for surgery in ("Eyebrow", "Eyelid", "Facelift", "FacialBones", "Nose"):
        folder = hda / surgery
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        members = defaultdict(dict)
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            # The released data include 49_b.jpg.png and 77_b.jpg.png.
            match = re.fullmatch(r"([A-Za-z0-9]+)_([ab])(?:\.(?:jpg|jpeg|png))+", path.name, re.I)
            if not match:
                issues.append(dict(dataset="hda", error="unparsed_filename", path=str(path)))
                continue
            subject = str(int(match[1])) if match[1].isdigit() else match[1]
            condition = match[2].lower()
            if condition in members[subject]:
                raise ValueError(f"Duplicate HDA identity/condition: {path}")
            members[subject][condition] = path
        for subject, paths in sorted(members.items()):
            add("hda", f"{surgery}/{subject}", surgery, paths.get("b"), paths.get("a"))

    makeup = root / "Makeup Detection Face Dataset"
    seen = set()
    with (makeup / "make_up.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            a, b = ((makeup / row[k]).resolve() for k in ("no_makeup", "with_makeup"))
            if not a.is_relative_to(makeup.resolve()) or not b.is_relative_to(makeup.resolve()):
                raise ValueError("Makeup CSV path escapes dataset directory")
            if a.stem != b.stem or a.stem in seen:
                raise ValueError(f"Ambiguous makeup pair: {row}")
            seen.add(a.stem)
            add("makeup", a.stem, "with_vs_without", a, b)

    fei = root / "FEI Face Database"
    if not fei.is_dir():
        raise FileNotFoundError(fei)
    members = defaultdict(dict)
    for path in sorted(fei.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        match = re.fullmatch(r"(\d+)-(\d{2})\.(?:jpg|jpeg|png)", path.name, re.I)
        if not match or not 1 <= int(match[2]) <= 14:
            issues.append(dict(dataset="fei", error="unparsed_filename", path=str(path)))
            continue
        subject, condition = str(int(match[1])), match[2]
        if condition in members[subject]:
            raise ValueError(f"Duplicate FEI identity/condition: {path}")
        members[subject][condition] = path
    comparisons = fei_comparisons or FEI_COMPARISONS
    for item in comparisons:
        if (not isinstance(item, (list, tuple)) or len(item) != 3
                or not isinstance(item[0], str) or not item[0]
                or item[1] not in {f"{i:02d}" for i in range(1, 15)}
                or item[2] not in {f"{i:02d}" for i in range(1, 15)} or item[1] == item[2]):
            raise ValueError(f"Invalid FEI comparison: {item}")
    if len({item[0] for item in comparisons}) != len(comparisons):
        raise ValueError("FEI contrast names must be unique")
    if protocol == "extended":
        comparisons = [(f"view_{i:02d}_vs_11", "11", f"{i:02d}") for i in range(1, 15) if i != 11]
    for subject, paths in sorted(members.items(), key=lambda kv: int(kv[0])):
        for contrast, a, b in comparisons:
            add("fei", subject, contrast, paths.get(a), paths.get(b))
    ids = [p["pair_id"] for p in pairs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate pair IDs: check contrast names")
    if not pairs:
        raise ValueError("No complete pairs")
    return pairs, issues


def subset_pairs(pairs, per_group, seed):
    if per_group is None:
        return pairs
    import numpy as np
    groups = defaultdict(list)
    for p in pairs:
        groups[p["dataset"], p["contrast"]].append(p)
    rng = np.random.default_rng(seed)
    selected = []
    for key in sorted(groups):
        group = groups[key]
        indices = sorted(rng.choice(len(group), min(per_group, len(group)), replace=False))
        selected.extend(group[i] for i in indices)
    return selected


def inventory(pairs):
    return {"pairs": len(pairs), "unique_images": len({p[k] for p in pairs for k in ("baseline", "variant")}),
            "comparisons": dict(sorted(Counter(f"{p['dataset']}/{p['contrast']}" for p in pairs).items()))}
