import unittest

from runcible.core.errors import RuncibleValidationError
from runcible.webui.service import RuncibleService


class FakeNeed:
    def __init__(self, description):
        self._description = description

    def get_formatted_string(self):
        return self._description


class FakeModule:
    def __init__(self, module_name):
        self.module_name = module_name


class FakeProvider:
    def __init__(self, module_name, needed=None, completed=None, failed=None):
        self.provides_for = FakeModule(module_name)
        self.needed_actions = needed or []
        self.completed_actions = completed or []
        self.failed_actions = failed or []


class FakeDevice:
    def __init__(self, name, providers=None, cstate=None, needs_changes=False,
                 execute_completes=True):
        self.name = name
        self.providers = providers or []
        self._cstate = cstate or {}
        self.needs_changes = needs_changes
        self.plan_called = False
        self.execute_called = False
        self._execute_completes = execute_completes

    def plan(self, run_callbacks=True):
        self.plan_called = True

    def get_cstate(self):
        return self._cstate

    def execute(self, run_callbacks=True):
        self.execute_called = True
        if self._execute_completes:
            for provider in self.providers:
                provider.completed_actions = provider.needed_actions
                provider.needed_actions = []


class FakeScheduler:
    def __init__(self, fabric_config, target):
        self.fabric_config = fabric_config
        self.target = target
        self.devices = fabric_config.get('devices', [])


def make_scheduler_factory(devices):
    def factory(fabric_config, target):
        fabric_config = dict(fabric_config)
        fabric_config['devices'] = devices
        return FakeScheduler(fabric_config, target)
    return factory


class TestRuncibleServiceConstruction(unittest.TestCase):

    def test_requires_exactly_one_datasource(self):
        with self.assertRaises(RuncibleValidationError):
            RuncibleService()

    def test_rejects_multiple_datasources(self):
        with self.assertRaises(RuncibleValidationError):
            RuncibleService(mergedb_database='/tmp/db', yaml_path='/tmp/foo.yaml')

    def test_accepts_preloaded_config(self):
        service = RuncibleService(config={'meta': {}})
        self.assertEqual(service.fabric_config, {'meta': {}})

    def test_loads_yaml_datasource(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as f:
            f.write("core:\n  meta: {}\n")
            path = f.name
        try:
            service = RuncibleService(yaml_path=path)
            self.assertEqual(service.fabric_config, {'core': {'meta': {}}})
        finally:
            os.unlink(path)


class TestRuncibleServiceDeviceOperations(unittest.TestCase):

    def setUp(self):
        self.device_no_changes = FakeDevice(
            'switch1',
            providers=[FakeProvider('system')],
            cstate={'system': {'hostname': 'switch1'}},
            needs_changes=False,
        )
        self.device_needs_changes = FakeDevice(
            'switch2',
            providers=[FakeProvider(
                'vlans',
                needed=[FakeNeed('vlans.10.name.SET: vlan10')],
            )],
            cstate={'vlans': []},
            needs_changes=True,
        )
        self.service = RuncibleService(
            config={'meta': {}},
            scheduler_factory=make_scheduler_factory(
                [self.device_no_changes, self.device_needs_changes]
            ),
        )

    def test_list_devices_returns_sorted_names(self):
        self.assertEqual(self.service.list_devices(), ['switch1', 'switch2'])

    def test_get_plan_reports_cstate_and_needs(self):
        plan = self.service.get_plan()
        self.assertTrue(self.device_no_changes.plan_called)
        self.assertTrue(self.device_needs_changes.plan_called)
        self.assertEqual(plan['switch1']['needs_changes'], False)
        self.assertEqual(plan['switch1']['needs'], [])
        self.assertEqual(plan['switch1']['cstate'], {'system': {'hostname': 'switch1'}})
        self.assertEqual(plan['switch2']['needs_changes'], True)
        self.assertEqual(plan['switch2']['needs'], [
            {'module': 'vlans', 'description': 'vlans.10.name.SET: vlan10'}
        ])

    def test_execute_only_executes_devices_that_need_changes(self):
        result = self.service.execute()
        self.assertFalse(self.device_no_changes.execute_called)
        self.assertTrue(self.device_needs_changes.execute_called)
        self.assertEqual(result['switch1']['needs_changes'], False)
        self.assertEqual(result['switch1']['completed'], [])
        self.assertEqual(result['switch2']['needs_changes'], True)
        self.assertEqual(result['switch2']['completed'], ['vlans.10.name.SET: vlan10'])
        self.assertEqual(result['switch2']['failed'], [])

    def test_execute_reports_failed_needs(self):
        failing_provider = FakeProvider(
            'vlans',
            needed=[FakeNeed('vlans.20.name.SET: vlan20')],
        )
        failing_device = FakeDevice(
            'switch3',
            providers=[failing_provider],
            needs_changes=True,
            execute_completes=False,
        )

        def execute_with_failure(run_callbacks=True):
            failing_device.execute_called = True
            failing_provider.failed_actions = failing_provider.needed_actions
            failing_provider.needed_actions = []

        failing_device.execute = execute_with_failure
        service = RuncibleService(
            config={'meta': {}},
            scheduler_factory=make_scheduler_factory([failing_device]),
        )
        result = service.execute()
        self.assertEqual(result['switch3']['completed'], [])
        self.assertEqual(result['switch3']['failed'], ['vlans.20.name.SET: vlan20'])

    def test_target_regex_is_forwarded_to_scheduler_factory(self):
        seen = {}

        def factory(fabric_config, target):
            seen['target'] = target
            return FakeScheduler(fabric_config, target)

        service = RuncibleService(config={'meta': {}}, scheduler_factory=factory)
        service.list_devices(target='^switch1$')
        self.assertEqual(seen['target'], '^switch1$')


if __name__ == '__main__':
    unittest.main()
