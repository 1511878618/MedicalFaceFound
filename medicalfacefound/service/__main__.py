"""Run with python -m medicalfacefound.service (frontend defaults to service/static)."""
from __future__ import annotations

import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Serve the MedicalFaceFound capture UI and API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-dir", help="Static frontend directory (defaults to medicalfacefound/service/static)")
    parser.add_argument("--weights-dir", help="Local weights root containing tasks/<name>/")
    parser.add_argument("--database", help="SQLite file used to store captures")
    args = parser.parse_args()
    for value, name in ((args.frontend_dir, "MFF_FRONTEND_DIR"), (args.weights_dir, "MFF_WEIGHTS_DIR"),
                        (args.database, "MEDICALFACE_DB_PATH")):
        if value is not None:
            os.environ[name] = value

    import uvicorn

    uvicorn.run("medicalfacefound.service.app:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
