# Omada Controller Fixtures

`controller_6_1_ssid.json` is a sanitized SSID response recorded by an
authenticated, read-only local-v2 inventory of controller 6.1.0.19 (apiVer 3).
Names and IDs are synthetic; `pskSetting.securityKey` was removed entirely.
All remaining settings retain their recorded structure and values. The AP
inventory projection in `test_omada_system_provider.py` has the same provenance;
its MAC and name are synthetic. Detail responses, other device types, populated
VLANs, and test security keys are simulated, not additional live captures.

The recorded SSID has numeric security 3, versionPsk 4, encryptionPsk 3, band 6,
no enable key, and default VLAN mode 0. The suite asserts that matching desired
state produces no write operations and that unrelated fields survive PATCH.

Schema references used to interpret and construct variants:

- [TP-Link schema snapshot: PSK settings](https://github.com/Tohaker/omada-go-sdk/blob/6f0bafa8fdb133d7917572100297b6276e47f1db/omada/docs/SsidPskSettingOpenApiVO.md)
- [VLAN custom settings](https://github.com/Tohaker/omada-go-sdk/blob/6f0bafa8fdb133d7917572100297b6276e47f1db/omada/docs/SsidVlanCustomSettingOpenApiVO.md)
- [SSID bands and security](https://github.com/Tohaker/omada-go-sdk/blob/6f0bafa8fdb133d7917572100297b6276e47f1db/omada/docs/CreateSsidOpenApiVO.md)
- [Local-v2 WLAN implementation](https://github.com/emanuelbesliu/terraform-provider-tplink-omada/blob/6bc71b310bc81a90f3ad32194ba8c17947bf79d6/internal/resources/wireless_network.go)
- [Local-v2 device rename routes](https://github.com/wncservices/terraform-provider-omada/blob/b0a018903f4136992b8bc6ebfa9d9871b238ac84/internal/omada/devices.go)

The public schema describes Open API; it is supporting evidence, not proof of
local-v2 write acceptance. No controller writes were performed for these tests.
In particular, populated VLAN variants are schema-based regression cases, not
recorded 6.1 write/read-back evidence.

Provider boundaries: versionPsk 4 means mixed WPA2/WPA3 except on 6-GHz-only
band 4, where it means WPA3. New SSIDs default to 2.4/5 GHz; updates preserve
bands and PMF. Unsupported band/security combinations fail rather than silently
downgrading security. Missing global enable state means enabled; disabling an
SSID without a returned `ssidEnable` field is rejected, not encoded as a hidden
SSID or an unrecognized `enable` flag. VLAN pools and unsupported security modes
fail closed because the neutral WLAN model cannot represent them.

Passphrase references may be `${WIFI_KEY}` directly or an existing alias in
`wifi_passphrases` whose value is `${WIFI_KEY}`. Literal metadata secrets are
rejected. Resolution uses `resolve_env` only when constructing a write; a no-op
does not need the secret. Passphrase-only rotation remains outside the diff.
