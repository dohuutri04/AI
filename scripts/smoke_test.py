import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import app as edu


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def run_smoke_test():
    fd, tmp_db = tempfile.mkstemp(prefix="educonnect_smoke_", suffix=".db")
    os.close(fd)

    try:
        edu.DB = tmp_db
        edu.app.config["TESTING"] = True
        edu.init_db()

        conn = edu.get_db()
        conn.execute(
            "INSERT INTO users (name,email,password,is_admin,wallet_balance) VALUES (?,?,?,?,?)",
            ("Learner One", "learner@example.com", edu.generate_password_hash("pass1234"), 0, 500000),
        )
        conn.execute(
            "INSERT INTO users (name,email,password,is_admin,wallet_balance) VALUES (?,?,?,?,?)",
            ("Admin One", "admin@example.com", edu.generate_password_hash("admin1234"), 1, 0),
        )
        conn.commit()
        conn.close()

        # --- Forgot password flow (3 steps + expiry) ---
        forgot_client = edu.app.test_client()
        step1 = forgot_client.post("/quen-mat-khau", data={"step": "1", "email": "learner@example.com"}).get_json()
        assert_true(step1 and step1.get("success") is True, f"Forgot password step1 failed: {step1}")
        otp = step1.get("token")
        assert_true(bool(otp), f"OTP missing: {step1}")

        step2 = forgot_client.post(
            "/quen-mat-khau", data={"step": "2", "email": "learner@example.com", "token": otp}
        ).get_json()
        assert_true(step2 and step2.get("success") is True, f"Forgot password step2 failed: {step2}")

        step3 = forgot_client.post(
            "/quen-mat-khau",
            data={"step": "3", "email": "learner@example.com", "token": otp, "new_password": "newpass123"},
        ).get_json()
        assert_true(step3 and step3.get("success") is True, f"Forgot password step3 failed: {step3}")

        login_new_password = forgot_client.post(
            "/login", data={"email": "learner@example.com", "password": "newpass123"}
        ).get_json()
        assert_true(
            login_new_password and login_new_password.get("success") is True,
            f"Login with new password failed: {login_new_password}",
        )

        # OTP one-time use
        reused = forgot_client.post(
            "/quen-mat-khau",
            data={"step": "3", "email": "learner@example.com", "token": otp, "new_password": "another123"},
        ).get_json()
        assert_true(reused and reused.get("success") is False, f"OTP should not be reusable: {reused}")

        # Expired OTP check
        conn = edu.get_db()
        conn.execute(
            "INSERT INTO password_resets (email, token, expires_at, used) VALUES (?,?,?,0)",
            ("learner@example.com", "EXPIRED1", (datetime.now() - timedelta(minutes=5)).isoformat()),
        )
        conn.commit()
        conn.close()
        expired = forgot_client.post(
            "/quen-mat-khau", data={"step": "2", "email": "learner@example.com", "token": "EXPIRED1"}
        ).get_json()
        assert_true(expired and expired.get("success") is False, f"Expired OTP should fail: {expired}")

        # --- AI + wallet/refund flow ---
        learner_client = edu.app.test_client()
        learner_login = learner_client.post(
            "/login", data={"email": "learner@example.com", "password": "newpass123"}
        ).get_json()
        assert_true(learner_login and learner_login.get("success") is True, f"Learner login failed: {learner_login}")

        ai_res = learner_client.get("/api/ai/personalization").get_json()
        assert_true(ai_res and ai_res.get("success") is True, f"AI endpoint failed: {ai_res}")
        assert_true("coach_source" in ai_res.get("data", {}), f"AI payload missing coach_source: {ai_res}")

        bank_res = learner_client.post(
            "/update-bank-info",
            data={"bank_name": "Vietcombank", "bank_account": "1234567890", "bank_holder": "Learner One"},
        ).get_json()
        assert_true(bank_res and bank_res.get("success") is True, f"Update bank info failed: {bank_res}")

        withdraw_res = learner_client.post("/wallet/withdraw-request", data={"amount": "200000"}).get_json()
        assert_true(withdraw_res and withdraw_res.get("success") is True, f"Withdraw request failed: {withdraw_res}")

        conn = edu.get_db()
        withdraw_txn = conn.execute(
            "SELECT * FROM wallet_transactions WHERE type='withdraw' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert_true(withdraw_txn is not None, "Withdraw transaction not found")
        withdraw_id = int(withdraw_txn["id"])
        learner_id = int(withdraw_txn["user_id"])
        conn.close()

        admin_client = edu.app.test_client()
        admin_login = admin_client.post("/login", data={"email": "admin@example.com", "password": "admin1234"}).get_json()
        assert_true(admin_login and admin_login.get("success") is True, f"Admin login failed: {admin_login}")

        reject_res = admin_client.post(
            f"/admin/withdrawals/reject/{withdraw_id}", data={"note": "Smoke test reject"}
        ).get_json()
        assert_true(reject_res and reject_res.get("success") is True, f"Reject withdraw failed: {reject_res}")

        conn = edu.get_db()
        failed_status = conn.execute("SELECT status FROM wallet_transactions WHERE id=?", (withdraw_id,)).fetchone()
        refund_txn = conn.execute(
            "SELECT * FROM wallet_transactions WHERE user_id=? AND type='refund' ORDER BY id DESC LIMIT 1", (learner_id,)
        ).fetchone()
        final_balance = conn.execute("SELECT wallet_balance FROM users WHERE id=?", (learner_id,)).fetchone()["wallet_balance"]
        conn.close()

        assert_true(failed_status and failed_status["status"] == "failed", "Withdraw transaction should be failed")
        assert_true(refund_txn is not None, "Refund transaction missing")
        assert_true(float(final_balance) == 500000.0, f"Wallet balance mismatch after refund: {final_balance}")

        print("PASS: all critical flows are working.")
        print("- Forgot password 3-step with OTP expiry")
        print("- AI personalization API")
        print("- Withdraw request + admin reject + refund")

    finally:
        try:
            os.remove(tmp_db)
        except OSError:
            pass


if __name__ == "__main__":
    run_smoke_test()
