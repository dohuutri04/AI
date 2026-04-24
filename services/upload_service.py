import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


class UploadServiceError(Exception):
    pass


class UploadService:
    def __init__(self):
        self.provider = (os.environ.get("UPLOAD_PROVIDER", "cloudinary") or "cloudinary").strip().lower()
        self.max_size_mb = int(os.environ.get("UPLOAD_MAX_SIZE_MB", "10") or "10")
        self.cloud_name = (os.environ.get("CLOUDINARY_CLOUD_NAME", "") or "").strip()
        self.api_key = (os.environ.get("CLOUDINARY_API_KEY", "") or "").strip()
        self.api_secret = (os.environ.get("CLOUDINARY_API_SECRET", "") or "").strip()

    def _validate(self, file_storage, allowed_exts):
        if not file_storage or not getattr(file_storage, "filename", ""):
            raise UploadServiceError("Thiếu file upload.")
        name = file_storage.filename.strip()
        ext = os.path.splitext(name)[1].lower()
        if ext not in allowed_exts:
            raise UploadServiceError(f"Định dạng file không hợp lệ: {ext}")
        raw = file_storage.read()
        if raw is None:
            raw = b""
        if len(raw) == 0:
            raise UploadServiceError("File rỗng.")
        max_bytes = self.max_size_mb * 1024 * 1024
        if len(raw) > max_bytes:
            raise UploadServiceError(f"File vượt giới hạn {self.max_size_mb}MB.")
        file_storage.stream.seek(0)
        return raw, ext

    def upload_file(self, file_storage, folder, allowed_exts):
        if self.provider != "cloudinary":
            raise UploadServiceError("Provider upload chưa được hỗ trợ.")
        if not self.cloud_name or not self.api_key or not self.api_secret:
            raise UploadServiceError("Thiếu cấu hình Cloudinary trong biến môi trường.")
        raw, ext = self._validate(file_storage, allowed_exts)
        timestamp = int(time.time())
        public_id = f"{folder}/{uuid4().hex}"
        sign_payload = f"public_id={public_id}&timestamp={timestamp}{self.api_secret}"
        signature = hashlib.sha1(sign_payload.encode("utf-8")).hexdigest()
        mime_type = file_storage.mimetype or "application/octet-stream"

        boundary = f"----EduConnectBoundary{uuid4().hex}"
        body_parts = [
            self._form_field(boundary, "api_key", self.api_key),
            self._form_field(boundary, "timestamp", str(timestamp)),
            self._form_field(boundary, "public_id", public_id),
            self._form_field(boundary, "signature", signature),
            self._file_field(boundary, "file", file_storage.filename, mime_type, raw),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        body = b"".join(body_parts)
        url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/auto/upload"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise UploadServiceError(f"Upload cloud thất bại: {err_body}")
        except Exception as exc:
            raise UploadServiceError(f"Upload cloud thất bại: {exc}")

        return {
            "public_url": payload.get("secure_url", ""),
            "key": payload.get("public_id", public_id),
            "mime_type": payload.get("resource_type", "raw"),
            "size": int(payload.get("bytes", len(raw))),
            "provider": "cloudinary",
        }

    def delete_file(self, storage_key):
        if self.provider != "cloudinary" or not storage_key:
            return
        if not self.cloud_name or not self.api_key or not self.api_secret:
            return
        timestamp = int(time.time())
        sign_payload = f"public_id={storage_key}&timestamp={timestamp}{self.api_secret}"
        signature = hashlib.sha1(sign_payload.encode("utf-8")).hexdigest()
        encoded = urllib.parse.urlencode(
            {
                "public_id": storage_key,
                "timestamp": timestamp,
                "api_key": self.api_key,
                "signature": signature,
            }
        ).encode("utf-8")
        url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/destroy"
        req = urllib.request.Request(url, data=encoded, method="POST")
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            return

    @staticmethod
    def _form_field(boundary, name, value):
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    @staticmethod
    def _file_field(boundary, name, filename, mime_type, raw_bytes):
        safe_name = filename.replace('"', "")
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{safe_name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        return head + raw_bytes + b"\r\n"
