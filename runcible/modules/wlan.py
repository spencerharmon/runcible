from runcible.modules.module import Module
from runcible.core.need import NeedOperation as Op
from runcible.core.errors import RuncibleValidationError


class WLANResources(object):
    SSIDS = 'ssids'


class SSIDResources(object):
    """
    Vendor-neutral keys accepted inside each entry of WLAN.ssids. These are intentionally shaped so any
    AP driver/provider (Omada, Unifi, ...) can map them to its own controller-specific API/config
    schema.
    """
    NAME = 'name'
    ENABLED = 'enabled'
    BROADCAST = 'broadcast'
    VLAN_ID = 'vlan_id'
    SECURITY = 'security'

    REQUIRED = {
        NAME: str,
    }

    OPTIONAL = {
        ENABLED: bool,
        BROADCAST: bool,
        VLAN_ID: int,
        SECURITY: dict,
    }


class SSIDSecurityResources(object):
    """
    Vendor-neutral keys accepted inside a SSID's security dict.
    """
    AUTH_MODE = 'auth_mode'
    PASSPHRASE_REF = 'passphrase_ref'

    # The set of vendor-neutral auth modes any AP driver/provider must be able to map to its own
    # controller-specific security profile.
    ALLOWED_AUTH_MODES = {'open', 'wpa2_psk', 'wpa3_psk', 'wpa2_wpa3_psk'}

    REQUIRED = {
        AUTH_MODE: str,
    }

    OPTIONAL = {
        # A reference (e.g. a secret-store key or path), never the passphrase itself in cleartext.
        PASSPHRASE_REF: str,
    }


class WLAN(Module):
    module_name = 'wlan'
    identifier_attribute = None

    configuration_attributes = {
        WLANResources.SSIDS: {
            'type': list,
            'sub_type': dict,
            'allowed_operations': [Op.SET, Op.ADD, Op.DELETE, Op.CLEAR],
            'examples': [[{
                'name': 'corp-wifi',
                'enabled': True,
                'broadcast': True,
                'vlan_id': 20,
                'security': {'auth_mode': 'wpa2_psk', 'passphrase_ref': 'vault://wifi/corp-wifi'}
            }]],
            'description': 'A list of vendor-neutral SSID/WLAN definitions. Each entry is a dict; see '
                           'SSIDResources for the accepted keys.'
        }
    }

    def validate(self, dictionary: dict):
        validated_config = super().validate(dictionary)
        ssids = validated_config.get(WLANResources.SSIDS)
        if ssids:
            for ssid in ssids:
                self.validate_ssid(ssid)
        return validated_config

    @staticmethod
    def validate_ssid(ssid: dict):
        """
        Validates a single entry of the ssids list against the vendor-neutral SSID schema.

        :param ssid:
            A dict representing a single SSID/WLAN
        :raises RuncibleValidationError:
            If the ssid dict is malformed
        """
        if not isinstance(ssid, dict):
            raise RuncibleValidationError(f"Each entry of {WLANResources.SSIDS} must be a dict, got {ssid}")

        allowed_keys = set(SSIDResources.REQUIRED.keys()) | set(SSIDResources.OPTIONAL.keys())
        for key in ssid.keys():
            if key not in allowed_keys:
                raise RuncibleValidationError(f"Key {key} not defined in WLAN ssid schema")

        for key, expected_type in SSIDResources.REQUIRED.items():
            if key not in ssid:
                raise RuncibleValidationError(f"WLAN ssid is missing required attribute {key}")
            if not isinstance(ssid[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {ssid[key]} of key {key} in WLAN ssid must be a {expected_type}"
                )

        for key, expected_type in SSIDResources.OPTIONAL.items():
            if key in ssid and not isinstance(ssid[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {ssid[key]} of key {key} in WLAN ssid must be a {expected_type}"
                )

        security = ssid.get(SSIDResources.SECURITY)
        if security is not None:
            WLAN.validate_security(security)

    @staticmethod
    def validate_security(security: dict):
        """
        Validates a SSID's security dict against the vendor-neutral security schema.

        :param security:
            A dict representing a single SSID's security configuration
        :raises RuncibleValidationError:
            If the security dict is malformed
        """
        if not isinstance(security, dict):
            raise RuncibleValidationError(f"{SSIDResources.SECURITY} must be a dict, got {security}")

        allowed_keys = set(SSIDSecurityResources.REQUIRED.keys()) | set(SSIDSecurityResources.OPTIONAL.keys())
        for key in security.keys():
            if key not in allowed_keys:
                raise RuncibleValidationError(f"Key {key} not defined in WLAN ssid security schema")

        for key, expected_type in SSIDSecurityResources.REQUIRED.items():
            if key not in security:
                raise RuncibleValidationError(f"WLAN ssid security is missing required attribute {key}")
            if not isinstance(security[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {security[key]} of key {key} in WLAN ssid security must be a {expected_type}"
                )

        for key, expected_type in SSIDSecurityResources.OPTIONAL.items():
            if key in security and not isinstance(security[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {security[key]} of key {key} in WLAN ssid security must be a {expected_type}"
                )

        auth_mode = security.get(SSIDSecurityResources.AUTH_MODE)
        if auth_mode not in SSIDSecurityResources.ALLOWED_AUTH_MODES:
            raise RuncibleValidationError(
                f"Value {auth_mode} of key {SSIDSecurityResources.AUTH_MODE} in WLAN ssid security "
                f"must be one of {SSIDSecurityResources.ALLOWED_AUTH_MODES}"
            )

    def determine_needs(self, other):
        needs_list = super().determine_needs(other)
        return needs_list

    def __repr__(self):
        return "<Runcible Module: wlan>"
