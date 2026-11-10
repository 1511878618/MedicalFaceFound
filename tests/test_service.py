"""Service integration tests using a real HTTP server and temporary capture storage.

Inference tests replace weight loading/model execution; they do not validate real weights.
Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import uvicorn
from PIL import Image

from medicalfacefound.inference.face import to_model_input
from medicalfacefound.service.app import create_app
from medicalfacefound.service.image import ImageInputError, decode_image, prepare_image
from medicalfacefound.service.models import ModelStore
from medicalfacefound.service.settings import Settings


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (48, 32), (220, 60, 30)).save(output, format="PNG")
    return output.getvalue()


def multipart(image, fields=None, *, white_fill_mask=None):
    boundary = "medicalfacefound-test-boundary"
    body = bytearray()
    for name, value in (fields or {}).items():
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    # Deliberately mismatched filename/header: detected image bytes are authoritative.
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="photo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode())
    body.extend(image)
    if white_fill_mask is not None:
        body.extend(f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="white_fill_mask"; filename="mask.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
        body.extend(white_fill_mask)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.frontend = self.root / "frontend"
        self.frontend.mkdir()
        (self.frontend / "index.html").write_text("<h1>Existing frontend</h1>")
        (self.frontend / "app.js").write_text("const connected = true;")
        self.settings = Settings(self.root / "weights", self.root / "capture.sqlite3", self.frontend)
        self.app = create_app(self.settings)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.base_url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="critical", lifespan="on", ws="none"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.server.started:
            self.tearDown()
            self.fail("HTTP test server did not start")

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.socket.close()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None, *, method=None):
        request = Request(self.base_url + path, data=data, headers=headers or {}, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                payload = json.loads(payload)
            return response.status, payload

    def verified(self, decoded):
        from medicalfacefound.service.quality import png_bytes
        crop = np.full((256, 256, 3), 128, dtype=np.uint8)
        return {"passed": True, "checks": [], "crop_box": [0,0,32,32], "face_box": [0,0,32,32], "version":"test"}, crop

    def create_record(self, **overrides):
        from medicalfacefound.service.catalog import CONSENT_VERSION
        fields = {"age":40,"gender":"female","height_cm":165.5,"weight_kg":60,"capture_source":"upload",
                  "consent":"true","consent_version":CONSENT_VERSION,"request_id":"r"*32,"access_token":"t"*64}
        fields.update(overrides)
        data, headers = multipart(png_bytes(),fields)
        with patch.object(self.app.state.quality,"check",side_effect=self.verified):
            return self.request("/v1/captures",data,headers)

    def admin_headers(self):
        return {"Authorization":"Bearer "+self.app.state.admin_token}

    def test_readiness_and_frontend(self):
        self.assertEqual(self.request("/health"),(200,{"status":"ok"}))
        status, body = self.request("/ready")
        self.assertEqual(status,200)
        self.assertEqual(body["quality_ready"],self.app.state.quality.available)
        self.assertFalse(body["inference_ready"])
        self.assertIn(b"Existing frontend",self.request("/")[1])
        self.assertIn(b"connected",self.request("/ui-assets/app.js")[1])

    def test_capture_is_idempotent_preserves_images_and_consent(self):
        from medicalfacefound.service.catalog import CONSENT_VERSION
        status, body = self.create_record()
        self.assertEqual(status,201,body)
        status, again = self.create_record()
        self.assertEqual(body["capture_id"],again["capture_id"])
        with sqlite3.connect(self.settings.database_path) as conn:
            row=conn.execute("SELECT image_data,processed_image,consent_version,access_hash FROM captures").fetchone()
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],1)
        self.assertEqual(row[0],png_bytes())
        self.assertEqual(decode_image(row[1]).array.shape,(256,256,3))
        self.assertEqual(row[2],CONSENT_VERSION)
        self.assertNotEqual(row[3],"t"*64)
        self.assertEqual(self.create_record(age=41)[0],409)

    def test_rejects_missing_consent_and_invalid_profile_without_storage(self):
        for kwargs in ({"consent":"false"},{"consent_version":"old"},{"age":121},{"weight_kg":"nan"}):
            self.assertEqual(self.create_record(**kwargs)[0],422)
        with sqlite3.connect(self.settings.database_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],0)

    def test_quality_preview_does_not_store_and_failed_quality_blocks_capture(self):
        data,headers=multipart(png_bytes())
        with patch.object(self.app.state.quality,"check",return_value=({"passed":False,"checks":[],"crop_box":None},None)):
            self.assertEqual(self.request("/v1/photos/quality",data,headers)[0],200)
            from medicalfacefound.service.catalog import CONSENT_VERSION
            data,headers=multipart(png_bytes(),{"age":40,"gender":"male","height_cm":170,"weight_kg":70,"capture_source":"camera","consent":"true","consent_version":CONSENT_VERSION,"request_id":"x"*32,"access_token":"y"*64})
            self.assertEqual(self.request("/v1/captures",data,headers)[0],422)
        with sqlite3.connect(self.settings.database_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],0)

    def test_white_fill_mask_applies_to_preview_and_saved_capture(self):
        from medicalfacefound.service.catalog import CONSENT_VERSION
        from medicalfacefound.service.quality import png_bytes as encode_png

        image = np.random.default_rng(4).integers(70, 180, (320, 320, 3), dtype=np.uint8)
        image[:, :160] = 255
        mask = np.full((160, 160, 4), 255, dtype=np.uint8)
        mask[:, :80, 3] = 0
        image_bytes = encode_png(image)
        mask_bytes = encode_png(mask)
        fields = {"age": 40, "gender": "male", "height_cm": 170, "weight_kg": 70,
                  "capture_source": "upload", "consent": "true", "consent_version": CONSENT_VERSION,
                  "request_id": "m" * 32, "access_token": "t" * 64}
        detected = [{"box": (80, 60, 240, 250), "score": 0.99}]
        with patch.object(self.app.state.quality, "detect", return_value=detected):
            data, headers = multipart(image_bytes, white_fill_mask=mask_bytes)
            code, preview = self.request("/v1/photos/quality", data, headers)
            self.assertEqual(code, 200)
            self.assertTrue(preview["passed"])
            self.assertAlmostEqual(preview["metrics"]["exposure_excluded_fraction"], 0.5)
            invalid, headers = multipart(image_bytes, white_fill_mask=b"invalid mask")
            self.assertEqual(self.request("/v1/photos/quality", invalid, headers)[0], 422)

            data, headers = multipart(image_bytes, fields)
            self.assertEqual(self.request("/v1/captures", data, headers)[0], 422)
            data, headers = multipart(image_bytes, fields, white_fill_mask=mask_bytes)
            code, saved = self.request("/v1/captures", data, headers)
            self.assertEqual(code, 201)
            self.assertEqual(saved["quality"]["metrics"], preview["metrics"])
            self.assertEqual(self.request("/v1/captures", data, headers)[1]["capture_id"], saved["capture_id"])
            mask[0, 0, 3] = 255
            changed, headers = multipart(image_bytes, fields, white_fill_mask=encode_png(mask))
            self.assertEqual(self.request("/v1/captures", changed, headers)[0], 409)
        with sqlite3.connect(self.settings.database_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT image_data FROM captures").fetchone()[0], image_bytes)

    def test_report_requires_record_specific_token(self):
        _,body=self.create_record()
        path=f"/v1/captures/{body['capture_id']}/report"
        self.assertEqual(self.request(path)[0],404)
        self.assertEqual(self.request(path,headers={"Authorization":"Bearer wrong"})[0],404)
        code,record=self.request(path,headers={"Authorization":"Bearer "+"t"*64})
        self.assertEqual(code,200)
        for private in ("access_hash","image_data","processed_image","payload_hash"):
            self.assertNotIn(private,record)

    def test_prediction_retry_uses_same_capture_and_cached_success(self):
        _,body=self.create_record()
        folder=self.settings.weights_dir/"tasks"/"Age"
        folder.mkdir(parents=True)
        (folder/"config.json").write_text('{"sha256":"weights-v1"}')
        self.app.state.models.available=["Age"]
        path=f"/v1/captures/{body['capture_id']}/predictions/Age"
        auth={"Authorization":"Bearer "+"t"*64}
        result={"task":"Age","value":54.3,"unit":"year"}
        with patch.object(self.app.state.models,"predict",side_effect=RuntimeError("failure")), self.assertLogs("medicalfacefound.service",level="ERROR"):
            self.assertEqual(self.request(path,b"",auth)[0],503)
        with patch.object(self.app.state.models,"predict",return_value=result) as predict:
            self.assertEqual(self.request(path,b"",auth)[0],200)
            self.assertTrue(self.request(path,b"",auth)[1]["cached"])
            predict.assert_called_once()
            np.testing.assert_array_equal(predict.call_args.args[1],np.full((256,256,3),128,dtype=np.uint8))
        with sqlite3.connect(self.settings.database_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT status,attempts FROM predictions").fetchone(),("completed",2))

    def test_admin_endpoints_are_protected(self):
        _,body=self.create_record()
        identity=body["capture_id"]
        for path,data in [("/v1/admin/captures",None),(f"/v1/admin/captures/{identity}",None),
                          (f"/v1/admin/captures/{identity}/image/original",None),("/v1/admin/export",None),
                          ("/v1/admin/backup",b""),(f"/v1/admin/captures/{identity}/delete",b'{}')]:
            self.assertEqual(self.request(path,data,{"Content-Type":"application/json"})[0],401,path)
        code,body=self.request("/v1/admin/captures",headers=self.admin_headers())
        self.assertEqual((code,body["total"]),(200,1))
        self.assertEqual(self.request("/v1/admin/captures?start=2026-11-10&end=2026-11-01",headers=self.admin_headers())[0],422)
        code,csv=self.request("/v1/admin/export",headers=self.admin_headers())
        self.assertEqual(code,200)
        self.assertIn(identity.encode(),csv)
        self.assertNotIn(("t"*64).encode(),csv)

    def test_default_gradcam_only_generates_block_and_retries(self):
        _, body = self.create_record()
        capture = f"/v1/captures/{body['capture_id']}"
        auth = {"Authorization": "Bearer " + "t" * 64}
        folder = self.settings.weights_dir / "tasks" / "Age"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text('{"sha256":"weights-v1"}')
        self.app.state.models.available = ["Age"]
        store = self.app.state.models
        path = f"{capture}/predictions/Age?explain=true"
        result = {"task": "Age", "value": 54.3, "unit": "year"}
        with patch.object(store, "predict", return_value=result) as predict:
            with patch.object(store, "explain", side_effect=RuntimeError("failure")) as failed:
                with self.assertLogs("medicalfacefound.service", level="ERROR"):
                    code, first = self.request(path, b"", auth)
                failed.assert_called_once()
                self.assertEqual(failed.call_args.kwargs["variant"], "block")
            self.assertEqual((code, first["explanation_status"]), (200, "failed"))
            with patch.object(store, "explain", return_value=b"block PNG") as explain:
                code, second = self.request(path, b"", auth)
                self.assertEqual((code, second["explanation_status"]), (200, "completed"))
                self.assertEqual(explain.call_count, 1)
                self.assertEqual(explain.call_args.kwargs["variant"], "block")
            predict.assert_called_once()
        self.assertTrue(second["cached"])
        self.assertEqual(second["result"], result)
        _, report = self.request(f"{capture}/report", headers=auth)
        prediction, = report["predictions"]
        self.assertTrue(prediction["has_explanation"])
        self.assertFalse(prediction["has_norm1_explanation"])
        self.assertNotIn("norm1_explanation_image", prediction)
        endpoint = f"{capture}/explanations/{prediction['id']}"
        self.assertEqual(self.request(endpoint, headers=auth), (200, b"block PNG"))
        self.assertEqual(self.request(f"{endpoint}?variant=norm1", headers=auth)[0], 404)
        self.assertEqual(self.request(f"{endpoint}?variant=norm1")[0], 404)

    def test_admin_age_heatmap_setting_selects_and_preserves_variants(self):
        from medicalfacefound.service import database as db

        endpoint = "/v1/admin/settings/heatmaps"
        headers = {**self.admin_headers(), "Content-Type": "application/json"}
        def put(method, auth=headers):
            return self.request(endpoint, json.dumps({"age_method": method}).encode(), auth, method="PUT")
        self.assertEqual(self.request(endpoint)[0], 401)
        self.assertEqual(put("norm1", {"Content-Type": "application/json"})[0], 401)
        db.set_age_heatmap_method(self.settings.database_path, "pair")
        settings = self.request(endpoint, headers=headers)[1]
        self.assertEqual(settings["age_method"], "block")
        self.assertEqual({option["id"] for option in settings["options"]}, {"block", "hirescam", "layercam"})
        self.assertEqual(put("norm1")[0], 422)
        with patch("medicalfacefound.service.heatmap_settings.find_spec", return_value=None):
            self.assertEqual(put("layercam")[0], 409)
        with patch("medicalfacefound.service.heatmap_settings.find_spec", return_value=object()):
            self.assertEqual(put("layercam")[0], 200)
        self.assertEqual(db.age_heatmap_method(self.settings.database_path), "layercam")
        self.assertEqual(self.request("/ready")[1]["age_heatmap_method"], "layercam")

        _, body = self.create_record()
        capture = f"/v1/captures/{body['capture_id']}"
        auth = {"Authorization": "Bearer " + "t" * 64}
        store = self.app.state.models
        store.available = ["Age"]
        folder = self.settings.weights_dir / "tasks" / "Age"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text('{"sha256":"weights-v1"}')
        path = f"{capture}/predictions/Age?explain=true"
        result = {"task": "Age", "value": 54.3, "unit": "year"}
        with patch.object(store, "predict", return_value=result) as predict:
            with patch.object(store, "explain", return_value=b"layer PNG") as explain:
                self.assertEqual(self.request(path, b"", auth)[1]["explanation_method"], "layercam")
                self.assertEqual(explain.call_count, 1)
                self.assertEqual(explain.call_args.kwargs["variant"], "layercam")
            self.assertEqual(put("block")[0], 200)
            prediction, = self.request(f"{capture}/report", headers=auth)[1]["predictions"]
            self.assertEqual(prediction["explanation_method"], "layercam")
            with patch.object(store, "explain", return_value=b"block PNG"):
                self.assertTrue(self.request(path, b"", auth)[1]["cached"])
            predict.assert_called_once()
        prediction, = self.request(f"{capture}/report", headers=auth)[1]["predictions"]
        self.assertEqual(prediction["explanation_method"], "block")
        self.assertTrue(prediction["has_explanation"])
        explanation = f"{capture}/explanations/{prediction['id']}"
        self.assertEqual(self.request(f"{explanation}?variant=layercam", headers=auth), (200, b"layer PNG"))
        self.assertEqual(self.request(explanation, headers=auth), (200, b"block PNG"))

    def test_deletion_request_filter_and_cascade(self):
        from medicalfacefound.service import database as db
        _,body=self.create_record()
        identity=body["capture_id"]
        auth={"Authorization":"Bearer "+"t"*64}
        prediction,_=db.reserve_prediction(self.settings.database_path,identity,"Age","v1")
        self.assertEqual(self.request(f"/v1/captures/{identity}/deletion-request",b"",auth)[0],200)
        self.assertEqual(self.request("/v1/admin/captures?status=deletion",headers=self.admin_headers())[1]["total"],1)
        with self.assertRaises(db.RecordConflict):
            db.reserve_prediction(self.settings.database_path,identity,"Hb","v1")
        db.finish_prediction(self.settings.database_path,prediction,result={"value":40})
        headers={**self.admin_headers(),"Content-Type":"application/json"}
        path=f"/v1/admin/captures/{identity}/delete"
        self.assertEqual(self.request(path,b'{"confirmation":"wrong"}',headers)[0],422)
        self.assertEqual(self.request(path,json.dumps({"confirmation":identity}).encode(),headers)[0],200)
        with sqlite3.connect(self.settings.database_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM predictions").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM admin_events WHERE action='delete'").fetchone()[0],1)

    def test_backup_is_readable_and_private(self):
        self.create_record()
        status,body=self.request("/v1/admin/backup",b"",self.admin_headers())
        self.assertEqual(status,200)
        backup=self.settings.database_path.parent/"backups"/body["filename"]
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)
        with sqlite3.connect(backup) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM captures").fetchone()[0],1)

    def test_legacy_prediction_also_checks_photo(self):
        self.app.state.models.available=["Age"]
        data,headers=multipart(png_bytes(),{"image_mode":"none"})
        with patch.object(self.app.state.quality,"check",return_value=({"passed":False,"checks":[]},None)):
            self.assertEqual(self.request("/v1/models/Age/predict",data,headers)[0],422)


class ModelAndImageTests(unittest.TestCase):
    def test_discovery_lazy_loading_and_one_model_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Age", "BMI"):
                folder = root / "tasks" / name
                folder.mkdir(parents=True)
                (folder / "config.json").write_text("{}")
                (folder / "model.safetensors").write_bytes(b"test double, not actual weights")
            store = ModelStore(Settings(root, root / "test.db"))
            self.assertEqual(store.status()["available_models"], ["Age", "BMI"])
            self.assertEqual(store.status()["loaded_models"], [])
            with patch("medicalfacefound.service.models.load_task", return_value=(object(), {})) as load, \
                 patch("medicalfacefound.service.models.predict_values", return_value=[{"value": 1}]):
                for name in ("Age", "Age", "BMI", "Age"):
                    store.predict(name, np.zeros((256, 256, 3), dtype=np.uint8))
                self.assertEqual([call.args[0] for call in load.call_args_list], ["Age", "BMI", "Age"])
                self.assertEqual(store.status()["loaded_models"], ["Age"])

    def test_missing_explicit_weights_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ModelStore(Settings(root, root / "test.db", tasks=("Age",)))
            self.assertIn("Age", store.status()["load_errors"])
            self.assertFalse(store.status()["inference_ready"])
            with self.assertRaises(ValueError):
                ModelStore(Settings(root, root / "test.db", tasks=("../secret",)))

    def test_exif_orientation_and_model_normalization(self):
        output = BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (48, 32), (220, 60, 30)).save(output, "JPEG", exif=exif)
        decoded = decode_image(output.getvalue())
        self.assertEqual((decoded.width, decoded.height), (32, 48))
        for mode in ("pad", "none"):
            image, _ = prepare_image(decoded, mode, "retinaface")
            tensor = to_model_input(image)
            self.assertEqual(tensor.shape, (3, 256, 256))
            self.assertEqual(tensor.dtype, np.float32)
        with self.assertRaises(ImageInputError):
            decode_image(b"x" * (10 * 1024 * 1024 + 1))

    def test_face_crop_uses_repository_preprocessing(self):
        decoded = decode_image(png_bytes())
        with patch("medicalfacefound.service.image.detect_faces", return_value=[{"box": (0, 0, 30, 30), "score": .98}]):
            image, metadata = prepare_image(decoded, "face", "retinaface")
        self.assertEqual(image.shape, (256, 256, 3))
        self.assertTrue(metadata["detected_face"])
        self.assertEqual(metadata["face_bbox"], (0, 0, 30, 30))

    def test_padding_handles_narrow_images_without_large_square_allocation(self):
        output = BytesIO()
        Image.new("RGB", (1, 40000), (220, 60, 30)).save(output, "PNG")
        image, _ = prepare_image(decode_image(output.getvalue()), "pad", "retinaface")
        self.assertEqual(image.shape, (256, 256, 3))
        np.testing.assert_array_equal(image[128, 128], [220, 60, 30])


if __name__ == "__main__":
    unittest.main()
