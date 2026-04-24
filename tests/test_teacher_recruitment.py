import io
import os
import tempfile
import unittest

import app as app_module


class DummyUploadService:
    def upload_file(self, file_storage, folder, allowed_exts):
        return {
            "provider": "cloudinary",
            "public_url": "https://example.com/fake-file.pdf",
            "key": "teacher-applications/fake-file",
            "mime_type": "application/pdf",
            "size": 1234,
        }


class TeacherRecruitmentFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "test.db")
        self.old_db = app_module.DB
        self.old_upload = app_module.upload_service
        app_module.DB = self.db_path
        app_module.upload_service = DummyUploadService()
        app_module.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.DB = self.old_db
        app_module.upload_service = self.old_upload
        self.tempdir.cleanup()

    def _login(self, email):
        rv = self.client.post("/login", data={"email": email, "password": "123456"})
        payload = rv.get_json()
        self.assertTrue(payload["success"])

    def test_owner_can_create_job_and_review_application(self):
        self._login("an.nguyen@educonnect.vn")
        create_job = self.client.post(
            "/courses/1/teacher-jobs",
            data={
                "title": "Tuyển giáo viên React",
                "description": "Dạy dự án thực chiến.",
                "requirements": "Có 2+ năm kinh nghiệm.",
            },
        )
        self.assertTrue(create_job.get_json()["success"])

        self.client.get("/logout")
        self._login("binh.tran@educonnect.vn")
        apply_resp = self.client.post(
            "/teacher-jobs/1/apply",
            data={
                "bio": "Mình đã dạy React 3 năm.",
                "experience_summary": "Mentor hơn 100 học viên.",
                "contact_email": "binh.tran@educonnect.vn",
                "contact_phone": "0900000000",
                "cv_file": (io.BytesIO(b"fake pdf"), "cv.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertTrue(apply_resp.get_json()["success"])

        self.client.get("/logout")
        self._login("an.nguyen@educonnect.vn")
        review_resp = self.client.patch(
            "/teacher-applications/1/status",
            json={"status": "accepted", "review_note": "Phu hop voi khoa hoc"},
        )
        self.assertTrue(review_resp.get_json()["success"])

    def test_non_owner_cannot_create_job(self):
        self._login("binh.tran@educonnect.vn")
        resp = self.client.post(
            "/courses/1/teacher-jobs",
            data={"title": "abc", "description": "xyz"},
        )
        self.assertFalse(resp.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
