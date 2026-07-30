import copy

import yaml

from runcible.core.errors import RuncibleValidationError
from runcible.schedulers.scheduler import SchedulerBase
# Importing the concrete scheduler modules (rather than only the SchedulerBase
# above) is required so that they register themselves as attributes of the
# `runcible.schedulers` package before PluginRegistry.class_loader walks it --
# runcible.core.cli does the same import for the same reason.
import runcible.schedulers.naive  # noqa: F401


class RuncibleService:
    """
    High-level, UI-agnostic service layer over runcible's existing engine API
    (:class:`runcible.core.device.Device` / :class:`runcible.schedulers.scheduler.SchedulerBase`).

    This class owns no provider/driver logic of its own -- it loads a fabric
    configuration from one of runcible's existing datasources (a MergeDB
    database or a plain YAML file, mirroring ``runcible.core.cli.Cli``) and
    delegates all device construction, state loading, diffing, and execution
    to the existing scheduler/device engine. It exists purely to provide a
    stable, JSON-friendly surface that a web front end (or any other
    programmatic caller) can consume without reimplementing any provider
    logic.
    """

    #: Mirrors ``runcible.core.cli.mergedb_default_config`` so the web UI
    #: applies the same merge rules as the CLI when reading a MergeDB
    #: database.
    MERGEDB_DEFAULT_CONFIG = {
        'merge_rules': {
            'keyed_array': [
                {'path': [], 'attribute': 'vlans', 'key': 'id'},
                {'path': [], 'attribute': 'interfaces', 'key': 'name'},
                {'path': [], 'attribute': 'bonds', 'key': 'name'}
            ]
        }
    }

    def __init__(self, mergedb_database=None, yaml_path=None, config=None,
                 scheduler_factory=None):
        """
        :param mergedb_database:
            Path to the base directory of a MergeDB database, as accepted by
            ``runcible --mergedb-database``.

        :param yaml_path:
            Path to a plain YAML fabric definition file, as accepted by
            ``runcible --yaml``.

        :param config:
            A pre-loaded fabric configuration dict. Mutually exclusive with
            ``mergedb_database``/``yaml_path``, mainly useful for tests and
            embedding.

        :param scheduler_factory:
            Callable with the same signature as
            ``SchedulerBase.get_scheduler(fabric_config, device_regex)``,
            used to construct a scheduler for a given target. Defaults to
            ``SchedulerBase.get_scheduler``. Overridable for testing without
            requiring real device drivers/connections.

        :raises RuncibleValidationError:
            If zero or more than one datasource is specified.
        """
        if sum(bool(x) for x in (config is not None, mergedb_database, yaml_path)) != 1:
            raise RuncibleValidationError(
                "Exactly one of config, mergedb_database, or yaml_path must be specified"
            )
        if config is not None:
            self.fabric_config = config
        elif mergedb_database:
            # Imported lazily so that the web UI does not require mergedb to
            # be importable unless a MergeDB datasource is actually used.
            from mergedb.data_types.database import Database
            mdb = Database(mergedb_database, self.MERGEDB_DEFAULT_CONFIG)
            self.fabric_config = mdb.build()
        else:
            with open(yaml_path) as f:
                raw = f.read()
            self.fabric_config = yaml.safe_load(raw)

        self._scheduler_factory = scheduler_factory or SchedulerBase.get_scheduler

    def _get_scheduler(self, target='.*'):
        """
        Builds a scheduler (and, transitively, its devices) matching
        ``target``.

        A deep copy of the loaded fabric config is handed to the scheduler
        each time because ``SchedulerBase.__init__`` mutates the dict it is
        given (it pops the top-level ``meta`` key), and each call here must
        see the full, un-mutated fabric.
        """
        config_copy = copy.deepcopy(self.fabric_config)
        return self._scheduler_factory(config_copy, target)

    def list_devices(self, target='.*'):
        """
        :param target:
            Regular expression selecting device names, as used elsewhere in
            runcible (``runcible <target> ...``).

        :return:
            Sorted list of device names matching ``target``.
        """
        scheduler = self._get_scheduler(target)
        return sorted(device.name for device in scheduler.devices)

    def get_plan(self, target='.*'):
        """
        Loads current state and computes the desired-vs-current diff
        ("plan") for every device matching ``target``, without executing
        anything.

        :return:
            Dict keyed by device name, each value a dict with:
                - ``cstate``: the rendered current state of every module
                - ``needs_changes``: bool, whether any provider has pending needs
                - ``needs``: list of {"module": ..., "description": ...} dicts,
                  one per pending need (the desired-vs-current diff entries)
        """
        scheduler = self._get_scheduler(target)
        result = {}
        for device in scheduler.devices:
            device.plan(run_callbacks=False)
            needs = []
            for provider in device.providers:
                for need in provider.needed_actions:
                    needs.append({
                        'module': provider.provides_for.module_name,
                        'description': need.get_formatted_string(),
                    })
            result[device.name] = {
                'cstate': device.get_cstate(),
                'needs_changes': device.needs_changes,
                'needs': needs,
            }
        return result

    def execute(self, target='.*'):
        """
        Plans and then executes (applies) any pending changes for every
        device matching ``target``.

        :return:
            Dict keyed by device name, each value a dict with:
                - ``needs_changes``: bool, whether execution was attempted
                - ``completed``: list of formatted strings for needs that were
                  successfully applied
                - ``failed``: list of formatted strings for needs that could
                  not be applied
        """
        scheduler = self._get_scheduler(target)
        result = {}
        for device in scheduler.devices:
            device.plan(run_callbacks=False)
            completed = []
            failed = []
            if device.needs_changes:
                device.execute(run_callbacks=False)
                for provider in device.providers:
                    for need in provider.completed_actions:
                        completed.append(need.get_formatted_string())
                    for need in provider.failed_actions:
                        failed.append(need.get_formatted_string())
            result[device.name] = {
                'needs_changes': device.needs_changes,
                'completed': completed,
                'failed': failed,
            }
        return result
