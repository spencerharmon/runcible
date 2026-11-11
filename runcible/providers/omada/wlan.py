"""Omada WLAN/SSID provider.

Reconciles the vendor-neutral :class:`~runcible.modules.wlan.WLAN` module against
the TP-Link Omada controller's Northbound API. It reads the site's current SSIDs,
diffs them (by SSID name) against the desired module state, and emits the ordered,
idempotent list of Northbound API operations that reconciles the two --
creating new SSIDs, updating changed ones (including their VLAN binding), and
deleting the ones the desired state no longer declares. When the controller
already matches the desired state it emits NOTHING (a no-op).

Each "API operation" is exactly the request dict the ``rest`` protocol
(:class:`~runcible.protocols.rest_protocol.RestProtocol`) consumes -- ``method`` /
``path`` (relative to ``/{omadacId}/api/v2``) / optional ``data`` -- so
``fix_needs`` just hands each op to ``device.send_command``.

Site scope is resolved by the driver's ``pre_plan``/``pre_exec`` hooks and left on
the device under the ``omada_site`` key; the SSID group is delivered through the
per-device meta config as ``wlan_group`` (the Omada WLAN-group id the SSIDs live
under). Neither is defaulted -- a missing value is a validation error.

Security mapping: the vendor-neutral ``auth_mode`` values map to Omada's
controller security schema via :data:`AUTH_MODE_TO_OMADA`. A passphrase is never
carried in the module in cleartext -- ``passphrase_ref`` is resolved to the real
secret through a runtime ``${NAME}`` reference (directly or through the per-device
``wifi_passphrases`` map). Passphrases are deliberately excluded from the diff;
a passphrase-only change does not cause an update. Existing controller settings,
including any returned security key, are preserved on PATCH.
"""
from copy import deepcopy
import re

from runcible.providers.provider import ProviderBase
from runcible.modules.wlan import (
    WLAN,
    WLANResources,
    SSIDResources,
    SSIDSecurityResources,
)
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.errors import RuncibleValidationError
from runcible.protocols.config import resolve_env


# Vendor-neutral auth_mode -> Omada controller security payload fragment.
AUTH_MODE_TO_OMADA = {
    'open': {'security': 0},
    'wpa2_psk': {'security': 3, 'pskSetting': {'versionPsk': 2, 'encryptionPsk': 3}},
    'wpa3_psk': {'security': 3, 'pskSetting': {'versionPsk': 4, 'encryptionPsk': 3}},
    'wpa2_wpa3_psk': {'security': 3, 'pskSetting': {'versionPsk': 4, 'encryptionPsk': 3}},
}


# Identity/metadata and derived flags returned on GET but not writable
# settings. The local-v2 update contract rejects raw GET objects (-1001), so
# these are stripped from every PATCH/POST body; the SSID id lives in the path.
RESPONSE_ONLY_FIELDS = frozenset({
    'id', 'idInt', 'index', 'site', 'wlanId', 'resource',
    'vlanEnable', 'portalEnable', 'accessEnable',
})


class OmadaWLANProvider(ProviderBase):
    """Provider for the ``wlan`` module on Omada-managed sites."""

    provides_for = WLAN
    supported_attributes = [
        WLANResources.SSIDS,
    ]

    def __init__(self, device_instance, dstate):
        # Name -> Omada SSID id, populated by get_cstate; needed to address
        # update/delete operations at their per-SSID path.
        self._current_ids = None
        self._current_ssids = {}
        super().__init__(device_instance, dstate)

    # -- path / config helpers ----------------------------------------------

    def _base_path(self):
        """The site+group-scoped SSID collection path.

        Site comes from the driver-selected ``omada_site`` device store key; the
        WLAN group id comes from the per-device ``wlan_group`` meta config. Both
        are required -- a missing value is a validation error, never guessed.
        """
        site = self.device.retrieve('omada_site')
        if not site:
            raise RuncibleValidationError(
                msg="Omada WLAN provider requires a selected site (omada_site); "
                    "none was resolved for this device.")
        group = self.device.meta_device.get('wlan_group')
        if not group:
            raise RuncibleValidationError(
                msg="Omada WLAN provider requires the 'wlan_group' meta config "
                    "(the Omada WLAN-group id the SSIDs live under).")
        return f"/sites/{site}/setting/wlans/{group}/ssids"

    def _resolve_passphrase(self, ref):
        """Resolve a passphrase_ref to the real secret via per-device config.

        Named aliases remain supported, but their values must be runtime env
        references, not literal secrets stored in device metadata.
        """
        secrets = self.device.meta_device.get('wifi_passphrases') or {}
        reference = secrets.get(ref, ref)
        if not isinstance(reference, str) or not re.fullmatch(
                r'\$\{[A-Za-z_][A-Za-z0-9_]*\}', reference):
            raise RuncibleValidationError(
                msg="Omada passphrase_ref must resolve to a ${NAME} environment reference.")
        value = resolve_env(reference, key='passphrase_ref')
        if not value:
            raise RuncibleValidationError(msg="Omada passphrase_ref resolved to an empty secret.")
        return value

    # -- payload construction (neutral -> Omada) ----------------------------

    def _ssid_payload(self, ssid, current=None):
        """Merge owned fields into the controller object, never a reduced PATCH."""
        payload = ({k: deepcopy(v) for k, v in current.items()
                    if k not in RESPONSE_ONLY_FIELDS}
                   if current is not None else {
            'band': 3, 'deviceType': 3, 'guestNetEnable': False,
            'pmfMode': 2, 'enable11r': False, 'mloEnable': False,
        })
        payload['name'] = ssid[SSIDResources.NAME]
        enabled = ssid.get(SSIDResources.ENABLED, True)
        if 'ssidEnable' in payload:
            payload['ssidEnable'] = enabled
        elif not enabled:
            raise RuncibleValidationError(
                msg="This Omada SSID schema has no global enable setting; "
                    "disabling requires per-AP overrides, not an 'enable' field.")
        payload['broadcast'] = ssid.get(SSIDResources.BROADCAST, True)
        vlan_id = ssid.get(SSIDResources.VLAN_ID)
        if current is None or vlan_id != self._vlan_id(current):
            payload['vlanSetting'] = {'mode': 0, 'customConfig': {}}
            if vlan_id is not None:
                if not 1 <= vlan_id <= 4094:
                    raise RuncibleValidationError(msg="Omada VLAN ID must be between 1 and 4094.")
                payload['vlanSetting'] = {
                    'mode': 1, 'customConfig': {'customMode': 1, 'vlanId': vlan_id}}
            payload.pop('vlanId', None)

        security = ssid.get(SSIDResources.SECURITY) or {}
        auth_mode = security.get(SSIDSecurityResources.AUTH_MODE, 'open')
        # versionPsk=4 is mixed WPA2/WPA3 except on a 6-GHz-only SSID.
        if (auth_mode == 'wpa3_psk' and payload['band'] != 4 or
                auth_mode == 'wpa2_wpa3_psk' and payload['band'] == 4 or
                auth_mode in ('open', 'wpa2_psk') and payload['band'] & 4):
            raise RuncibleValidationError(
                msg="Requested Omada security mode cannot be encoded on the existing bands.")
        if current is None or auth_mode != self._omada_to_auth_mode(current):
            fragment = deepcopy(AUTH_MODE_TO_OMADA[auth_mode])
            payload['security'] = fragment['security']
            if 'pskSetting' in fragment:
                payload.setdefault('pskSetting', {}).update(fragment['pskSetting'])
            else:
                payload.pop('pskSetting', None)
        ref = security.get(SSIDSecurityResources.PASSPHRASE_REF)
        if auth_mode != 'open':
            if ref:
                payload['pskSetting']['securityKey'] = self._resolve_passphrase(ref)
            elif current is None or current['security'] != 3:
                raise RuncibleValidationError(
                    msg="Creating a PSK SSID requires a passphrase_ref.")
        return payload

    # -- current-state parsing (Omada -> neutral) ---------------------------

    @staticmethod
    def _omada_to_auth_mode(omada_ssid):
        security = omada_ssid.get('security')
        if security == 0:
            return 'open'
        if security == 3:
            version = omada_ssid.get('pskSetting', {}).get('versionPsk')
            if version == 2:
                return 'wpa2_psk'
            if version == 4:
                return 'wpa3_psk' if omada_ssid.get('band') == 4 else 'wpa2_wpa3_psk'
        raise RuncibleValidationError(msg="Omada SSID security mode is not representable by WLAN.")

    @staticmethod
    def _vlan_id(omada_ssid):
        setting = omada_ssid.get('vlanSetting', {})
        if setting.get('mode') == 0:
            return None
        custom = setting.get('customConfig', {})
        vlan = None
        if setting.get('mode') == 1:
            if custom.get('customMode') == 1:
                vlan = custom.get('vlanPoolIds') or custom.get('vlanId')
            elif custom.get('customMode') == 0:
                vlan = OmadaWLANProvider._network_vlan(custom)
        if isinstance(vlan, str) and vlan.isdecimal():
            vlan = int(vlan)
        if type(vlan) is not int or not 1 <= vlan <= 4094:
            raise RuncibleValidationError(
                msg="Omada VLAN setting is not a single VLAN representable by WLAN.")
        return vlan

    @staticmethod
    def _network_vlan(custom):
        """Decode a by-network binding to its single VLAN, or None.

        ``lanNetworkVlanIds`` (network -> VLAN list) supersedes the legacy
        ``lanNetworkId``/``bridgeVlan`` pair and needs no ``lanNetworkId``. The
        whole mapping is inspected: anything other than exactly one distinct
        VLAN across all networks is a pool the neutral model cannot represent.
        """
        mapping = custom.get('lanNetworkVlanIds')
        found = set()
        if mapping:
            if not isinstance(mapping, dict):
                return None
            for vlans in mapping.values():
                if not isinstance(vlans, list):
                    return None
                found.update(vlans)
            if len(mapping) != 1:
                return None
        legacy = custom.get('bridgeVlan')
        if legacy is not None:
            found.add(legacy)
        if len(found) != 1:
            return None
        return next(iter(found))

    def _omada_to_neutral(self, omada_ssid):
        neutral = {SSIDResources.NAME: omada_ssid['name']}
        neutral[SSIDResources.ENABLED] = bool(omada_ssid.get('ssidEnable', True))
        neutral[SSIDResources.BROADCAST] = bool(omada_ssid.get('broadcast', True))
        vlan = self._vlan_id(omada_ssid)
        if vlan is not None:
            neutral[SSIDResources.VLAN_ID] = vlan
        neutral[SSIDResources.SECURITY] = {
            SSIDSecurityResources.AUTH_MODE: self._omada_to_auth_mode(omada_ssid),
        }
        return neutral

    def get_cstate(self):
        """Read the site's current SSIDs from the Northbound API."""
        result = self.device.send_command({'method': 'GET', 'path': self._base_path()})
        if isinstance(result, dict):
            data = result.get('data', [])
        else:
            data = result or []
        self._current_ids = {}
        self._current_ssids = {}
        ssids = []
        for omada_ssid in data:
            self._current_ids[omada_ssid['name']] = omada_ssid.get('id')
            self._current_ssids[omada_ssid['name']] = deepcopy(omada_ssid)
            ssids.append(self._omada_to_neutral(omada_ssid))
        return WLAN({WLANResources.SSIDS: ssids})

    # -- diff / reconciliation ----------------------------------------------

    @staticmethod
    def _normalize(ssid):
        """Comparable projection of a neutral SSID for convergence.

        Excludes the passphrase: a runtime reference is not comparable to the
        controller's returned (potentially masked or omitted) securityKey.
        """
        security = ssid.get(SSIDResources.SECURITY) or {}
        return {
            SSIDResources.NAME: ssid.get(SSIDResources.NAME),
            SSIDResources.ENABLED: ssid.get(SSIDResources.ENABLED, True),
            SSIDResources.BROADCAST: ssid.get(SSIDResources.BROADCAST, True),
            SSIDResources.VLAN_ID: ssid.get(SSIDResources.VLAN_ID),
            SSIDSecurityResources.AUTH_MODE: security.get(SSIDSecurityResources.AUTH_MODE, 'open'),
        }

    def generate_operations(self):
        """Ordered, idempotent Northbound ops that reconcile cstate -> dstate.

        Order: creates, then updates, then deletes. Returns ``[]`` (no-op) when
        the controller already matches the desired state.
        """
        if self._current_ids is None:
            self.load_module_cstate()
        desired = {s[SSIDResources.NAME]: s for s in (getattr(self.dstate, WLANResources.SSIDS, None) or [])}
        current = {s[SSIDResources.NAME]: s for s in (getattr(self.cstate, WLANResources.SSIDS, None) or [])}
        base = self._base_path()
        ops = []
        for name, ssid in desired.items():
            if name not in current:
                ops.append({'method': 'POST', 'path': base, 'data': self._ssid_payload(ssid)})
        for name, ssid in desired.items():
            if name in current and self._normalize(ssid) != self._normalize(current[name]):
                ops.append({
                    'method': 'PATCH',
                    'path': f"{base}/{self._current_ids.get(name)}",
                    'data': self._ssid_payload(ssid, self._current_ssids[name]),
                })
        for name in current:
            if name not in desired:
                ops.append({'method': 'DELETE', 'path': f"{base}/{self._current_ids.get(name)}"})
        return ops

    def determine_needs(self):
        """A single SET need stands in for a non-empty reconciliation."""
        if self.generate_operations():
            self.needed_actions = [Need('wlan', WLANResources.SSIDS, Op.SET)]
        else:
            self.needed_actions = []

    def fix_needs(self):
        for op in self.generate_operations():
            self.device.send_command(op)
        for need in list(self.needed_actions):
            self.complete(need)
