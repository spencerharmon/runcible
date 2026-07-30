import unittest

from runcible.webui.app import create_app


class StubService:
    def __init__(self, devices=None, plans=None, execute_results=None):
        self._devices = devices or []
        self._plans = plans or {}
        self._execute_results = execute_results or {}
        self.last_list_target = None
        self.last_plan_target = None
        self.last_execute_target = None

    def list_devices(self, target='.*'):
        self.last_list_target = target
        if target == '.*':
            return list(self._devices)
        return [d for d in self._devices if d == target.strip('^$')]

    def get_plan(self, target='.*'):
        self.last_plan_target = target
        if target == '.*':
            return dict(self._plans)
        name = target.strip('^$')
        return {name: self._plans[name]} if name in self._plans else {}

    def execute(self, target='.*'):
        self.last_execute_target = target
        name = target.strip('^$')
        return {name: self._execute_results[name]} if name in self._execute_results else {}


class TestRuncibleWebApp(unittest.TestCase):

    def setUp(self):
        self.service = StubService(
            devices=['switch1', 'switch2'],
            plans={
                'switch1': {'cstate': {'system': {'hostname': 'switch1'}},
                            'needs_changes': False, 'needs': []},
                'switch2': {'cstate': {'vlans': []},
                            'needs_changes': True,
                            'needs': [{'module': 'vlans', 'description': 'vlans.10.name.SET: vlan10'}]},
            },
            execute_results={
                'switch2': {'needs_changes': True, 'completed': ['vlans.10.name.SET: vlan10'],
                            'failed': []},
            },
        )
        self.app = create_app(self.service)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_healthz(self):
        resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'status': 'ok'})

    def test_index_lists_devices(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('switch1', body)
        self.assertIn('switch2', body)

    def test_device_detail_shows_plan(self):
        resp = self.client.get('/devices/switch2')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('vlans.10.name.SET: vlan10', body)
        self.assertEqual(self.service.last_plan_target, '^switch2$')

    def test_device_detail_404s_for_unknown_device(self):
        resp = self.client.get('/devices/nosuchdevice')
        self.assertEqual(resp.status_code, 404)

    def test_device_run_triggers_execute_and_shows_result(self):
        resp = self.client.post('/devices/switch2/run')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('vlans.10.name.SET: vlan10', body)
        self.assertEqual(self.service.last_execute_target, '^switch2$')

    def test_device_run_404s_for_unknown_device(self):
        resp = self.client.post('/devices/nosuchdevice/run')
        self.assertEqual(resp.status_code, 404)

    def test_api_devices_returns_json_list(self):
        resp = self.client.get('/api/devices')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), ['switch1', 'switch2'])
        self.assertEqual(self.service.last_list_target, '.*')

    def test_api_devices_forwards_target_query_param(self):
        resp = self.client.get('/api/devices?target=%5Eswitch1%24')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.service.last_list_target, '^switch1$')

    def test_api_plan_returns_json(self):
        resp = self.client.get('/api/devices/plan')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('switch1', data)
        self.assertIn('switch2', data)
        self.assertEqual(data['switch2']['needs_changes'], True)

    def test_api_run_executes_and_returns_json(self):
        resp = self.client.post('/api/devices/run?target=%5Eswitch2%24')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['switch2']['completed'], ['vlans.10.name.SET: vlan10'])


if __name__ == '__main__':
    unittest.main()
