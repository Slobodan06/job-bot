import os
import unittest

from app.extension.crypto import decrypt_secret, encrypt_secret


class CryptoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("JWT_SECRET")
        os.environ["JWT_SECRET"] = "test-secret-for-unit-tests"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = self._prev

    def test_roundtrip(self) -> None:
        token = encrypt_secret("hunter2")
        self.assertNotEqual("hunter2", token)
        self.assertEqual("hunter2", decrypt_secret(token))

    def test_decrypt_garbage_returns_empty(self) -> None:
        self.assertEqual("", decrypt_secret("not-a-valid-token"))


if __name__ == "__main__":
    unittest.main()
