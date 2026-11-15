from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests
from scripts import zotero_sync as sync


class MemoryVault:
    def __init__(self):
        self.entries = {}

    def get_password(self, service, server):
        return self.entries.get((service, server))

    def set_password(self, service, server, key):
        self.entries[service, server] = key

    def delete_password(self, service, server):
        self.entries.pop((service, server), None)


class AuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault()
        self.server = "test-server-a"
        self.remember = True
        self.grants = 0
        self.writes = 0
        self.reject = []
        self.output = io.StringIO()
        for context in (patch.dict(sync.os.environ, {}, clear=True),
                        patch.object(sync, "credential_backend", return_value=self.vault),
                        patch.object(sync.Zotero, "call", side_effect=self.call),
                        redirect_stdout(self.output)):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def call(self, method, path, **kwargs):
        if path == "/api/":
            return SimpleNamespace(headers={"Zotero-Server-ID": self.server})
        if path == "/api/local/authorize":
            self.grants += 1
            return SimpleNamespace(json=lambda: {"key": "secret-grant-" + str(self.grants), "remember": self.remember})
        self.writes += 1
        if self.reject:
            response = requests.Response()
            response.status_code = self.reject.pop(0)
            if response.status_code != 200:
                raise requests.HTTPError(response=response)
        return SimpleNamespace(status_code=200)

    def test_remembered_grant_is_reused_by_new_client_and_partitioned_by_server(self):
        sync.Zotero().write("PATCH", "/api/users/0/items/test")
        sync.Zotero().write("PATCH", "/api/users/0/items/test")
        self.assertEqual(self.grants, 1)
        self.server = "test-server-b"
        sync.Zotero().write("PATCH", "/api/users/0/items/test")
        self.assertEqual(self.grants, 2)
        self.assertEqual(len(self.vault.entries), 2)
        self.assertNotIn("secret-grant", self.output.getvalue())

    def test_single_use_grant_is_never_persisted(self):
        self.remember = False
        client = sync.Zotero()
        client.write("PATCH", "/api/users/0/items/test")
        client.write("PATCH", "/api/users/0/items/test")
        self.assertEqual(self.grants, 2)
        self.assertFalse(self.vault.entries)
        self.assertIsNone(client.key)

    def test_revoked_cached_key_is_replaced_once(self):
        self.vault.set_password(sync.AUTH_SERVICE, self.server, "old-secret")
        self.reject = [401, 200]
        sync.Zotero().write("PATCH", "/api/users/0/items/test")
        self.assertEqual((self.grants, self.writes), (1, 2))
        self.assertEqual(self.vault.get_password(sync.AUTH_SERVICE, self.server), "secret-grant-1")
        self.reject = [401, 401]
        with self.assertRaises(requests.HTTPError):
            sync.Zotero().write("PATCH", "/api/users/0/items/test")
        self.assertEqual(self.writes, 4)

    def test_read_only_calls_do_not_access_credentials_or_authorize(self):
        with patch.object(sync, "credential_backend") as store:
            sync.Zotero()
            store.assert_not_called()
        self.assertEqual((self.grants, self.writes), (0, 0))

    def test_non_authentication_failure_does_not_prompt_again(self):
        self.vault.set_password(sync.AUTH_SERVICE, self.server, "saved-secret")
        self.reject = [403]
        with self.assertRaises(requests.HTTPError):
            sync.Zotero().write("PATCH", "/api/users/0/items/test")
        self.assertEqual((self.grants, self.writes), (0, 1))

    def test_storage_failure_remains_memory_only_and_redacted(self):
        with patch.object(self.vault, "set_password", side_effect=OSError("private credential detail")):
            client = sync.Zotero()
            client.write("PATCH", "/api/users/0/items/test")
            client.write("PATCH", "/api/users/0/items/test")
        self.assertEqual(self.grants, 1)
        self.assertFalse(self.vault.entries)
        self.assertNotIn("private credential detail", self.output.getvalue())
        self.assertNotIn("secret-grant", self.output.getvalue())
