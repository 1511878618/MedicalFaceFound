#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_root="${MFF_BACKEND_DIR:-$project_root}"
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
cd "$backend_root"
exec "$python_bin" -m medicalfacefound.robustness "$@"
