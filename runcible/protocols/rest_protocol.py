"""HTTP/REST transport for the TP-Link Omada controller Northbound API.

This is the first HTTP protocol in runcible. Like the ``ssh`` and ``serial``
protocols it subclasses :class:`TerminalProtocolBase`, but instead of a shell
session it speaks the Omada controller's Northbound/controller API
(https://omada-northbound-docs.tplinkcloud.com).

The controller's endpoint (scheme/host/port) is NOT known to this engine code:
it is supplied at runtime as per-device configuration (``hostname`` plus the
optional ``scheme``/``port`` keys), exactly like the ssh/serial protocols. There
is no hardcoded or default host -- a missing ``hostname`` is a validation error.
Documentation examples use the RFC2606 placeholder ``omada.example.com``.

Auth handshake (Omada controller API v2):

1. ``GET  {base}/api/info``                     -> ``result.omadacId``
2. ``POST {base}/{omadacId}/api/v2/login``      -> ``result.token``
   (body ``{"username": ..., "password": ...}``)
3. Every subsequent call carries the token in the ``Csrf-Token`` header on the
   authenticated :class:`requests.Session`.

The controller admin credentials come from the provisioned ``omada_user`` /
``omada_password`` secrets, delivered to this protocol through runcible's normal
per-device config plumbing as the ``username`` / ``password`` config keys (the
same mechanism the ssh/serial protocols use). They are NEVER hardcoded or given
a default here -- a missing credential is a validation error.
"""
import logging

import requests

from runcible.protocols.protocol import TerminalProtocolBase
from runcible.core.errors import (
    RuncibleClientExecutionError,
    RuncibleConnectionError,
    RuncibleNotConnectedError,
    RuncibleValidationError,
)

logger = logging.getLogger(__name__)

# Omada Northbound errorCode returned when the access token is missing/expired.
# A response carrying it triggers a single transparent token refresh + retry.
TOKEN_EXPIRED_ERROR_CODES = (-44112,)


class RestProtocol(TerminalProtocolBase):
    """Omada controller Northbound API transport.

    Required config keys: ``hostname``, ``username``, ``password``.
    Optional: ``scheme`` (default ``https``), ``port`` (default ``443``),
    ``verify_ssl`` (default ``True``), ``timeout`` (default ``30``).
    """

    def __init__(self, config: dict):
        # Set before super().__init__ so load_config never clobbers them and
        # validate() can run against a fully-formed instance.
        self.session = None
        self.token = None
        self.omada_cid = None
        super().__init__(config=config)

    def validate(self, config):
        for key in ['hostname', 'username', 'password']:
            if key not in config:
                raise RuncibleValidationError(
                    msg=f"Key {key} missing from Protocol {self.__repr__()}")

    @property
    def base_url(self):
        scheme = getattr(self, 'scheme', 'https')
        port = getattr(self, 'port', 443)
        return f"{scheme}://{self.hostname}:{port}"

    @property
    def verify_ssl(self):
        return getattr(self, '_verify_ssl', True)

    @verify_ssl.setter
    def verify_ssl(self, value):
        self._verify_ssl = value

    @property
    def timeout(self):
        return getattr(self, '_timeout', 30)

    @timeout.setter
    def timeout(self, value):
        self._timeout = value

    # -- connection / auth ---------------------------------------------------

    def connect(self):
        """Open the HTTP session and perform the Omada auth handshake."""
        self.session = requests.Session()
        self.omada_cid = self._get_controller_id()
        self.token = self._login()

    def _get_controller_id(self):
        resp = self.session.get(
            f"{self.base_url}/api/info",
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        data = self._decode(resp)
        self._raise_for_errorcode(data, context="GET /api/info")
        try:
            return data['result']['omadacId']
        except (KeyError, TypeError):
            raise RuncibleConnectionError(
                msg=f"Omada /api/info response missing result.omadacId: {data}")

    def _login(self):
        url = f"{self.base_url}/{self.omada_cid}/api/v2/login"
        resp = self.session.post(
            url,
            json={'username': self.username, 'password': self.password},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        data = self._decode(resp)
        self._raise_for_errorcode(data, context="login")
        try:
            return data['result']['token']
        except (KeyError, TypeError):
            raise RuncibleConnectionError(
                msg=f"Omada login response missing result.token: {data}")

    def refresh_token(self):
        """Re-run the login handshake to obtain a fresh access token.

        The Omada access token is short-lived; when a call reports the token as
        expired we transparently refresh and retry once (see send_implement).
        """
        if self.session is None:
            raise RuncibleNotConnectedError(
                "Activate with self.connect() before refreshing the token")
        if self.omada_cid is None:
            self.omada_cid = self._get_controller_id()
        self.token = self._login()
        return self.token

    def _auth_headers(self):
        return {
            'Csrf-Token': self.token,
            'Content-Type': 'application/json',
        }

    # -- request mapping -----------------------------------------------------

    def send_implement(self, command):
        """Map a driver request to an Omada Northbound HTTP call.

        ``command`` is a dict describing the request:
            ``method`` -- HTTP verb (default ``GET``)
            ``path``   -- API path relative to ``/{omadacId}/api/v2``
                          (e.g. ``/sites/{siteId}/devices``)
            ``params`` -- optional query-string dict
            ``data``   -- optional JSON body dict

        Returns the parsed ``result`` payload from the JSON response. On a
        token-expired response the token is refreshed once and the call retried.
        """
        if self.session is None or self.token is None:
            raise RuncibleNotConnectedError(
                "You must activate the client with self.connect() before executing commands")
        if not isinstance(command, dict):
            raise RuncibleValidationError(
                msg=f"REST command must be a dict, got {type(command).__name__}: {command!r}")
        if 'path' not in command:
            raise RuncibleValidationError(
                msg=f"REST command missing required 'path' key: {command!r}")

        data = self._do_request(command)
        if self._token_expired(data):
            self.refresh_token()
            data = self._do_request(command)

        self._raise_for_errorcode(data, context=command.get('path'))
        return data.get('result')

    def _do_request(self, command):
        method = command.get('method', 'GET').upper()
        path = command['path']
        if not path.startswith('/'):
            path = '/' + path
        url = f"{self.base_url}/{self.omada_cid}/api/v2{path}"
        resp = self.session.request(
            method,
            url,
            headers=self._auth_headers(),
            params=command.get('params'),
            json=command.get('data'),
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        return self._decode(resp)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _decode(resp):
        try:
            return resp.json()
        except ValueError:
            raise RuncibleClientExecutionError(
                msg=f"Non-JSON response from Omada controller (status {resp.status_code}): "
                    f"{resp.text!r}",
                system=getattr(resp, 'url', None),
                command=None,
            )

    @staticmethod
    def _token_expired(data):
        return isinstance(data, dict) and data.get('errorCode') in TOKEN_EXPIRED_ERROR_CODES

    @staticmethod
    def _raise_for_errorcode(data, context=None):
        if not isinstance(data, dict):
            raise RuncibleClientExecutionError(
                msg=f"Unexpected Omada response payload: {data!r}",
                command=context)
        code = data.get('errorCode')
        if code not in (0, None):
            raise RuncibleClientExecutionError(
                msg=f"Omada API error {code}: {data.get('msg')}",
                command=context)
