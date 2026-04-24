import os
import tempfile
import unittest

import app as app_module


class MobileApiSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "mobile_test.db")
        self.old_db = app_module.DB
        app_module.DB = self.db_path
        app_module.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.DB = self.old_db
        self.tempdir.cleanup()

    def test_auth_and_courses_mobile_api(self):
        login = self.client.post(
            "/api/mobile/auth/login",
            data={"email": "an.nguyen@educonnect.vn", "password": "123456"},
        ).get_json()
        self.assertTrue(login["success"])
        me = self.client.get("/api/mobile/auth/me").get_json()
        self.assertTrue(me["success"])
        courses = self.client.get("/api/mobile/courses").get_json()
        self.assertTrue(courses["success"])
        self.assertTrue(len(courses["data"]["courses"]) > 0)

    def test_mobile_recruitment_history_endpoint(self):
        self.client.post(
            "/api/mobile/auth/login",
            data={"email": "an.nguyen@educonnect.vn", "password": "123456"},
        )
        create_job = self.client.post(
            "/courses/1/teacher-jobs",
            data={"title": "Mobile API Job", "description": "Need teacher"},
        ).get_json()
        self.assertTrue(create_job["success"])

        self.client.get("/logout")
        self.client.post(
            "/api/mobile/auth/login",
            data={"email": "binh.tran@educonnect.vn", "password": "123456"},
        )
        self.client.post(
            "/teacher-jobs/1/apply",
            data={
                "bio": "Ung tuyen qua mobile",
                "experience_summary": "2 years",
                "contact_email": "binh.tran@educonnect.vn",
                "contact_phone": "0909",
            },
        )
        history = self.client.get("/api/mobile/my-teacher-applications").get_json()
        self.assertTrue(history["success"])


if __name__ == "__main__":
    unittest.main()
