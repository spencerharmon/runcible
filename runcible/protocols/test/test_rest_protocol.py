import unittest
from unittest.mock import MagicMock, patch

from runcible.protocols.rest_protocol import RestProtocol
from runcible.protocols.protocol import TerminalProtocolBase
from runcible.core.errors import (
    RuncibleClientExecutionError,
    RuncibleConnectionError,
    RuncibleNotConnectedError,
    RuncibleValidationError,
)


def _json_response(payload, status=200):
    """Build a stand-in for a requests.Response returning ``payload`` from .json()."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.status_code = status
    resp.url = "https://omada.spencerharmon.com/api"
    return resp


BASE_CONFIG = {
    "hostname": "omada.spencerharmon.com",
    "username": "admin",
    "password": "s3cr3t",
}


class TestRestProtocolBasics(unittest.TestCase):
    def test_is_protocol_subclass(self):
        self.assertTrue(issubclass(RestProtocol, TerminalProtocolBase))

    def test_validate_requires_credentials(self):
        for missing in ("hostname", "username", "password"):
            cfg = dict(BASE_CONFIG)
            del cfg[missing]
            with self.assertRaises(RuncibleValidationError):
                RestProtocol(cfg)

    def test_no_default_credentials(self):
        # Credentials must come from config (the omada_user/omada_password
        # secrets); nothing is hardcoded or defaulted.
        proto = RestProtocol(BASE_CONFIG)
        self.assertEqual(proto.username, "admin")
        self.assertEqual(proto.password, "s3cr3t")

    def test_base_url_defaults_https_443(self):
        proto = RestProtocol(BASE_CONFIG)
        self.assertEqual(proto.base_url, "https://omada.spencerharmon.com:443")

    def test_base_url_honors_scheme_and_port(self):
        cfg = dict(BASE_CONFIG, scheme="http", port=8043)
        proto = RestProtocol(cfg)
        self.assertEqual(proto.base_url, "http://omada.spencerharmon.com:8043")


class TestRestProtocolAuthHandshake(unittest.TestCase):
    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_connect_performs_login_handshake(self, session_cls):
        session = session_cls.return_value
        session.get.return_value = _json_response(
            {"errorCode": 0, "result": {"omadacId": "CID123"}})
        session.post.return_value = _json_response(
            {"errorCode": 0, "result": {"token": "TOKEN-abc"}})

        proto = RestProtocol(BASE_CONFIG)
        proto.connect()

        # 1. GET /api/info to discover the controller id
        session.get.assert_called_once()
        info_url = session.get.call_args.args[0]
        self.assertEqual(info_url, "https://omada.spencerharmon.com:443/api/info")

        # 2. POST /{omadacId}/api/v2/login with the admin credentials
        session.post.assert_called_once()
        login_url = session.post.call_args.args[0]
        self.assertEqual(
            login_url,
            "https://omada.spencerharmon.com:443/CID123/api/v2/login")
        self.assertEqual(
            session.post.call_args.kwargs["json"],
            {"username": "admin", "password": "s3cr3t"})

        # 3. token carried for subsequent calls
        self.assertEqual(proto.omada_cid, "CID123")
        self.assertEqual(proto.token, "TOKEN-abc")
        self.assertEqual(proto._auth_headers()["Csrf-Token"], "TOKEN-abc")

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_connect_raises_on_login_error(self, session_cls):
        session = session_cls.return_value
        session.get.return_value = _json_response(
            {"errorCode": 0, "result": {"omadacId": "CID123"}})
        session.post.return_value = _json_response(
            {"errorCode": -30109, "msg": "Invalid username or password."})

        proto = RestProtocol(BASE_CONFIG)
        with self.assertRaises(RuncibleClientExecutionError):
            proto.connect()

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_connect_raises_when_omadac_id_missing(self, session_cls):
        session = session_cls.return_value
        session.get.return_value = _json_response({"errorCode": 0, "result": {}})
        proto = RestProtocol(BASE_CONFIG)
        with self.assertRaises(RuncibleConnectionError):
            proto.connect()


class TestRestProtocolSendImplement(unittest.TestCase):
    def _connected(self, session_cls):
        session = session_cls.return_value
        session.get.return_value = _json_response(
            {"errorCode": 0, "result": {"omadacId": "CID123"}})
        session.post.return_value = _json_response(
            {"errorCode": 0, "result": {"token": "TOKEN-abc"}})
        proto = RestProtocol(dict(BASE_CONFIG, verify_ssl=False))
        proto.connect()
        return proto, session

    def test_send_requires_connect(self):
        proto = RestProtocol(BASE_CONFIG)
        with self.assertRaises(RuncibleNotConnectedError):
            proto.send_implement({"path": "/sites"})

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_send_maps_request_to_http_call(self, session_cls):
        proto, session = self._connected(session_cls)
        session.request.return_value = _json_response(
            {"errorCode": 0, "result": {"data": [1, 2, 3]}})

        result = proto.send_implement({
            "method": "post",
            "path": "/sites/S1/devices",
            "params": {"page": 1},
            "data": {"name": "sw1"},
        })

        session.request.assert_called_once()
        method = session.request.call_args.args[0]
        url = session.request.call_args.args[1]
        kwargs = session.request.call_args.kwargs
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://omada.spencerharmon.com:443/CID123/api/v2/sites/S1/devices")
        self.assertEqual(kwargs["params"], {"page": 1})
        self.assertEqual(kwargs["json"], {"name": "sw1"})
        self.assertEqual(kwargs["headers"]["Csrf-Token"], "TOKEN-abc")
        self.assertFalse(kwargs["verify"])
        self.assertEqual(result, {"data": [1, 2, 3]})

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_send_defaults_to_get(self, session_cls):
        proto, session = self._connected(session_cls)
        session.request.return_value = _json_response({"errorCode": 0, "result": {}})
        proto.send_implement({"path": "/sites"})
        self.assertEqual(session.request.call_args.args[0], "GET")

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_send_rejects_non_dict_command(self, session_cls):
        proto, _ = self._connected(session_cls)
        with self.assertRaises(RuncibleValidationError):
            proto.send_implement("GET /sites")

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_send_rejects_missing_path(self, session_cls):
        proto, _ = self._connected(session_cls)
        with self.assertRaises(RuncibleValidationError):
            proto.send_implement({"method": "GET"})

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_send_raises_on_api_error(self, session_cls):
        proto, session = self._connected(session_cls)
        session.request.return_value = _json_response(
            {"errorCode": -1, "msg": "boom"})
        with self.assertRaises(RuncibleClientExecutionError):
            proto.send_implement({"path": "/sites"})

    @patch("runcible.protocols.rest_protocol.requests.Session")
    def test_expired_token_triggers_refresh_and_retry(self, session_cls):
        proto, session = self._connected(session_cls)
        # First call: token expired. Second call (after refresh): success.
        session.request.side_effect = [
            _json_response({"errorCode": -44112, "msg": "token expired"}),
            _json_response({"errorCode": 0, "result": {"ok": True}}),
        ]
        # login POST is called again by refresh_token -> new token
        session.post.return_value = _json_response(
            {"errorCode": 0, "result": {"token": "TOKEN-new"}})

        result = proto.send_implement({"path": "/sites"})

        self.assertEqual(session.request.call_count, 2)
        self.assertEqual(proto.token, "TOKEN-new")
        self.assertEqual(result, {"ok": True})
        # the retried request carried the refreshed token
        retry_headers = session.request.call_args_list[1].kwargs["headers"]
        self.assertEqual(retry_headers["Csrf-Token"], "TOKEN-new")


class TestRestProtocolRefresh(unittest.TestCase):
    def test_refresh_requires_connect(self):
        proto = RestProtocol(BASE_CONFIG)
        with self.assertRaises(RuncibleNotConnectedError):
            proto.refresh_token()


if __name__ == "__main__":
    unittest.main()
