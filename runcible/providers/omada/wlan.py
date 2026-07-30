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
secret through the per-device ``wifi_passphrases`` map at emit time. The
controller never returns a configured passphrase, so a passphrase-only change is
not observable in current state and is intentionally excluded from the
convergence diff (documented limitation).
"""
from runcible.providers.provider import ProviderBase
from runcible.modules.wlan import (
    WLAN,
    WLANResources,
    SSIDResources,
    SSIDSecurityResources,
)
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.errors import RuncibleValidationError


# Vendor-neutral auth_mode -> Omada controller security payload fragment.
AUTH_MODE_TO_OMADA = {
    'open': {'security': 'open'},
    'wpa2_psk': {'security': 'wpa-personal', 'wpaMode': 'wpa2', 'encryption': 'aes'},
    'wpa3_psk': {'security': 'wpa-personal', 'wpaMode': 'wpa3', 'encryption': 'aes'},
    'wpa2_wpa3_psk': {'security': 'wpa-personal', 'wpaMode': 'wpa2wpa3', 'encryption': 'aes'},
}

# Reverse map (Omada wpaMode -> neutral auth_mode) for reading current state.
_WPA_MODE_TO_AUTH_MODE = {
    'wpa2': 'wpa2_psk',
    'wpa3': 'wpa3_psk',
    'wpa2wpa3': 'wpa2_wpa3_psk',
}


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

        The reference is looked up in the per-device ``wifi_passphrases`` map; an
        unresolvable reference is a validation error rather than leaking the raw
        reference as if it were the passphrase.
        """
        secrets = self.device.meta_device.get('wifi_passphrases') or {}
        if ref not in secrets:
            raise RuncibleValidationError(
                msg=f"Omada WLAN provider could not resolve passphrase_ref {ref!r}; "
                    f"add it to the per-device 'wifi_passphrases' config.")
        return secrets[ref]

    # -- payload construction (neutral -> Omada) ----------------------------

    def _security_payload(self, security):
        auth_mode = security.get(SSIDSecurityResources.AUTH_MODE)
        fragment = AUTH_MODE_TO_OMADA.get(auth_mode)
        if fragment is None:
            raise RuncibleValidationError(
                msg=f"Omada WLAN provider cannot map auth_mode {auth_mode!r}.")
        payload = dict(fragment)
        passphrase_ref = security.get(SSIDSecurityResources.PASSPHRASE_REF)
        if passphrase_ref and fragment['security'] != 'open':
            payload['pskString'] = self._resolve_passphrase(passphrase_ref)
        return payload

    def _ssid_payload(self, ssid):
        """Build the Omada SSID request body from a neutral SSID dict."""
        payload = {'name': ssid[SSIDResources.NAME]}
        payload['enable'] = ssid.get(SSIDResources.ENABLED, True)
        payload['broadcast'] = ssid.get(SSIDResources.BROADCAST, True)
        vlan_id = ssid.get(SSIDResources.VLAN_ID)
        if vlan_id is not None:
            payload['vlanEnable'] = True
            payload['vlanId'] = vlan_id
        else:
            payload['vlanEnable'] = False
        security = ssid.get(SSIDResources.SECURITY)
        if security:
            payload.update(self._security_payload(security))
        return payload

    # -- current-state parsing (Omada -> neutral) ---------------------------

    @staticmethod
    def _omada_to_auth_mode(omada_ssid):
        security = omada_ssid.get('security')
        if security in (None, 'open', 'none', 0):
            return 'open'
        wpa_mode = omada_ssid.get('wpaMode')
        return _WPA_MODE_TO_AUTH_MODE.get(wpa_mode, 'wpa2_psk')

    def _omada_to_neutral(self, omada_ssid):
        neutral = {SSIDResources.NAME: omada_ssid['name']}
        neutral[SSIDResources.ENABLED] = bool(omada_ssid.get('enable', True))
        neutral[SSIDResources.BROADCAST] = bool(omada_ssid.get('broadcast', True))
        if omada_ssid.get('vlanEnable') and omada_ssid.get('vlanId') is not None:
            neutral[SSIDResources.VLAN_ID] = omada_ssid['vlanId']
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
        ssids = []
        for omada_ssid in data:
            self._current_ids[omada_ssid['name']] = omada_ssid.get('id')
            ssids.append(self._omada_to_neutral(omada_ssid))
        return WLAN({WLANResources.SSIDS: ssids})

    # -- diff / reconciliation ----------------------------------------------

    @staticmethod
    def _normalize(ssid):
        """Comparable projection of a neutral SSID for convergence.

        Excludes the passphrase (the controller never returns it, so it cannot
        participate in the current-vs-desired diff).
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
                    'data': self._ssid_payload(ssid),
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
