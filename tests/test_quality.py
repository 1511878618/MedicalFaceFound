import unittest
from unittest.mock import patch
import numpy as np
from medicalfacefound.inference import face
from medicalfacefound.service.quality import QualityChecker
from medicalfacefound.service.image import DecodedImage


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.checker=QualityChecker()
        self.image=np.random.default_rng(10).integers(70,180,(320,320,3),dtype=np.uint8)
        self.face={"box":(80,60,240,250),"score":.99}

    def run_check(self,image=None,faces=None,foreground_alpha=None):
        image=self.image if image is None else image
        decoded=DecodedImage(image,image.shape[1],image.shape[0],"PNG")
        with patch.object(face,"detect_faces",return_value=[self.face] if faces is None else faces):
            return self.checker.check(decoded, foreground_alpha=foreground_alpha)

    def test_crop_matches_original_inference_pipeline_exactly(self):
        quality,crop=self.run_check()
        self.assertTrue(quality["passed"],quality)
        with patch.object(face,"detect_faces",return_value=[self.face]):
            expected=face.FaceCropper().crop(self.image)
        np.testing.assert_array_equal(crop,expected)
        np.testing.assert_array_equal(face.to_model_input(crop),face.to_model_input(expected))

    def test_rejects_zero_and_multiple_faces(self):
        for faces in ([],[self.face,self.face]):
            report,crop=self.run_check(faces=faces)
            self.assertFalse(report["passed"])
            self.assertIsNone(crop)

    def test_rejects_blur_bad_exposure_and_truncated_face(self):
        flat=np.full_like(self.image,120)
        dark=np.zeros_like(self.image)
        for image in (flat,dark):
            report,_=self.run_check(image=image)
            self.assertFalse(report["passed"])
        report,_=self.run_check(faces=[{"box":(0,0,160,200),"score":.99}])
        self.assertFalse(report["passed"])
        self.assertFalse(next(c["passed"] for c in report["checks"] if c["key"]=='framing'))

    def test_exposure_ignores_fill_but_keeps_real_overexposure(self):
        image = self.image.copy()
        image[:, :160] = 255
        alpha = np.full(image.shape[:2], 255, dtype=np.uint8)
        alpha[:, :160] = 0
        plain, plain_crop = self.run_check(image=image)
        masked, masked_crop = self.run_check(image=image, foreground_alpha=alpha)
        self.assertFalse(plain["passed"])
        self.assertTrue(masked["passed"])
        self.assertAlmostEqual(masked["metrics"]["exposure_excluded_fraction"], 0.5)
        self.assertEqual(plain["metrics"]["sharpness"], masked["metrics"]["sharpness"])
        np.testing.assert_array_equal(plain_crop, masked_crop)

        image[:, 160:215] = 255
        overexposed, _ = self.run_check(image=image, foreground_alpha=alpha)
        self.assertFalse(next(check["passed"] for check in overexposed["checks"] if check["key"] == "exposure"))
        empty, _ = self.run_check(image=image, foreground_alpha=np.zeros_like(alpha))
        self.assertFalse(empty["passed"])
        self.assertIsNone(empty["metrics"]["brightness"])

class MigrationTests(unittest.TestCase):
    def test_legacy_capture_is_preserved_with_a_readable_backup(self):
        import tempfile,sqlite3
        from pathlib import Path
        from medicalfacefound.service.database import initialize_database
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.sqlite3'
            with sqlite3.connect(path) as conn:
                conn.execute('''CREATE TABLE captures (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,age INTEGER,
                    gender TEXT,height_cm REAL,weight_kg REAL,capture_source TEXT,filename TEXT,content_type TEXT,
                    image_format TEXT,image_width INTEGER,image_height INTEGER,image_size_bytes INTEGER,image_data BLOB)''')
                conn.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('old','2026-11-01T00:00:00+00:00',40,'male',170,70,'upload','old.png','image/png','PNG',1,1,4,b'old!'))
            initialize_database(path)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT id,image_data,consent_version,processed_image FROM captures').fetchone(),('old',b'old!',None,None))
            backups=list((path.parent/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as conn:
                self.assertEqual(conn.execute('SELECT image_data FROM captures').fetchone()[0],b'old!')
