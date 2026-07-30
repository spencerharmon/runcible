from unittest import TestCase

from runcible.modules.wlan import WLAN, WLANResources, SSIDResources, SSIDSecurityResources
from runcible.core.errors import RuncibleValidationError


VALID_DSTATE = {
    WLANResources.SSIDS: [
        {
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.ENABLED: True,
            SSIDResources.BROADCAST: True,
            SSIDResources.VLAN_ID: 20,
            SSIDResources.SECURITY: {
                SSIDSecurityResources.AUTH_MODE: 'wpa2_psk',
                SSIDSecurityResources.PASSPHRASE_REF: 'vault://wifi/corp-wifi',
            }
        },
        {
            SSIDResources.NAME: 'guest-wifi',
            SSIDResources.ENABLED: True,
            SSIDResources.BROADCAST: False,
            SSIDResources.VLAN_ID: 30,
            SSIDResources.SECURITY: {
                SSIDSecurityResources.AUTH_MODE: 'open',
            }
        }
    ]
}


class TestWLANModuleValidation(TestCase):

    def test_valid_dstate_parses(self):
        wlan = WLAN(VALID_DSTATE)
        self.assertEqual(len(wlan.ssids), 2)
        self.assertEqual(wlan.ssids[0][SSIDResources.NAME], 'corp-wifi')
        self.assertEqual(wlan.ssids[0][SSIDResources.VLAN_ID], 20)
        self.assertEqual(
            wlan.ssids[0][SSIDResources.SECURITY][SSIDSecurityResources.AUTH_MODE],
            'wpa2_psk'
        )
        self.assertEqual(wlan.ssids[1][SSIDResources.NAME], 'guest-wifi')

    def test_unknown_top_level_key_rejected(self):
        dstate = dict(VALID_DSTATE)
        dstate['not_a_real_attribute'] = True
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_missing_name(self):
        dstate = {WLANResources.SSIDS: [{SSIDResources.VLAN_ID: 20}]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_name_wrong_type(self):
        dstate = {WLANResources.SSIDS: [{SSIDResources.NAME: 123}]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_unknown_key_rejected(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            'bogus_key': 'nope',
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_vlan_id_wrong_type(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.VLAN_ID: 'not-an-int',
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_enabled_wrong_type(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.ENABLED: 'yes',
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_security_missing_auth_mode(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.SECURITY: {SSIDSecurityResources.PASSPHRASE_REF: 'vault://x'},
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_security_unknown_auth_mode_rejected(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.SECURITY: {SSIDSecurityResources.AUTH_MODE: 'wep'},
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_security_unknown_key_rejected(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.SECURITY: {
                SSIDSecurityResources.AUTH_MODE: 'wpa2_psk',
                'bogus_key': 'nope',
            },
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssid_security_wrong_type(self):
        dstate = {WLANResources.SSIDS: [{
            SSIDResources.NAME: 'corp-wifi',
            SSIDResources.SECURITY: 'not-a-dict',
        }]}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)

    def test_ssids_wrong_sub_type_rejected(self):
        dstate = {WLANResources.SSIDS: ['not-a-dict']}
        with self.assertRaises(RuncibleValidationError):
            WLAN(dstate)
