"""Omada driver.

Drives TP-Link Omada-managed devices through the Omada controller's
Northbound/controller API rather than a shell session, so its transport is the
HTTP-based ``rest`` protocol (:class:`RestProtocol`) instead of ssh/serial.

Omada controller sessions are per-site: after authenticating to the controller
a caller must select the target site before issuing device-scoped requests.
The lifecycle hooks below express that -- ``pre_plan_tasks`` /
``pre_exec_tasks`` resolve and select the configured site so both the read
(plan) and write (exec) phases operate against the right site scope.

This module is the driver skeleton. The per-module providers are wired into
``module_provider_map`` by their respective tasks; it starts empty here, the
same way the ``edgeos`` driver skeleton did.
"""
from runcible.protocols.rest_protocol import RestProtocol
from runcible.drivers.driver import DriverBase
from runcible.providers.omada.wlan import OmadaWLANProvider


class OmadaDriver(DriverBase):
    driver_name = "omada"

    # Per-module Omada provider wiring, keyed by module name (as it appears in
    # the device's dstate). Providers live under ``runcible/providers/omada/``.
    module_provider_map = {
        "wlan": OmadaWLANProvider,
    }

    protocol_map = {
        "rest": RestProtocol
    }

    @staticmethod
    def _select_site(device):
        """Resolve and select the controller site for this device.

        Omada Northbound sessions are per-site: the controller authenticates
        globally but every device-scoped request is issued against a selected
        site. The site is delivered through runcible's normal per-device meta
        config as the ``site`` key; the resolved site is stored on the device so
        subsequent provider requests can reference it.
        """
        site = device.meta_device.get('site')
        device.store('omada_site', site)
        return site

    @staticmethod
    def pre_plan_tasks(device):
        """Select the controller site before reading device state."""
        OmadaDriver._select_site(device)

    @staticmethod
    def pre_exec_tasks(device):
        """Select the controller site before applying any changes."""
        OmadaDriver._select_site(device)
