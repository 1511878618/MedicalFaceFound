#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_root="${MFF_BACKEND_DIR:-$project_root}"

# An automatically activated conda base must not hide the service environment.
python_bin="${MFF_PYTHON:-}"
if [[ -z "$python_bin" && -n "${CONDA_PREFIX:-}" && "${CONDA_DEFAULT_ENV:-}" != "base" ]]; then
  python_bin="$CONDA_PREFIX/bin/python"
fi
if [[ -z "$python_bin" ]]; then
  for candidate in "$HOME/miniforge3/envs/MedicalFaceFound/bin/python" \
                   "$HOME/miniforge3/envs/MedicalFaceFound_api/bin/python"; do
    if [[ -x "$candidate" ]]; then python_bin="$candidate"; break; fi
  done
fi
python_bin="${python_bin:-$(command -v python3 || command -v python || true)}"
if [[ -z "$python_bin" ]] || ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python interpreter not found. Set MFF_PYTHON to your Python executable." >&2
  exit 1
fi
if [[ ! -d "$backend_root/medicalfacefound/service" ]]; then
  echo "MedicalFaceFound backend not found: $backend_root. Set MFF_BACKEND_DIR." >&2
  exit 1
fi

export MFF_FRONTEND_DIR="${MFF_FRONTEND_DIR:-$backend_root/medicalfacefound/service/static}"
export MEDICALFACE_DB_PATH="${MEDICALFACE_DB_PATH:-$backend_root/data/medicalface.sqlite3}"
export MFF_WEIGHTS_DIR="${MFF_WEIGHTS_DIR:-$backend_root/weights}"
if [[ "${MFF_ENABLE_FAHR_FACEAGE:-0}" == "1" ]]; then
  export MFF_FAHR_FACEAGE_PYTHON="${MFF_FAHR_FACEAGE_PYTHON:-$HOME/miniforge3/envs/fahr-face/bin/python}"
  export MFF_FAHR_FACEAGE_SOURCE="${MFF_FAHR_FACEAGE_SOURCE:-$backend_root/external/FAHR-Face}"
  export MFF_FAHR_FACEAGE_CHECKPOINT="${MFF_FAHR_FACEAGE_CHECKPOINT:-$backend_root/weights/fahr-face/fahr_faceage.pth}"
fi
cd "$backend_root"
exec "$python_bin" -m medicalfacefound.service "$@"
