import os
import unittest
from unittest import mock

from runcible.webui.cli import main, parse_args, validate_args


class TestParseArgs(unittest.TestCase):

    def setUp(self):
        # Ensure environment variables from a developer's shell never leak
        # into these tests.
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        for var in ('RUNCIBLE_WEBUI_HOST', 'RUNCIBLE_WEBUI_PORT',
                    'MERGEDB_DATABASE', 'RUNCIBLE_YAML'):
            os.environ.pop(var, None)

    def tearDown(self):
        self._env_patch.stop()

    def test_defaults(self):
        args = parse_args(['-y', 'fabric.yaml'])
        self.assertEqual(args.host, '0.0.0.0')
        self.assertEqual(args.port, 8080)
        self.assertFalse(args.debug)
        self.assertEqual(args.yaml, 'fabric.yaml')
        self.assertIsNone(args.mergedb_database)

    def test_env_var_defaults(self):
        os.environ['RUNCIBLE_WEBUI_HOST'] = '127.0.0.1'
        os.environ['RUNCIBLE_WEBUI_PORT'] = '9090'
        os.environ['MERGEDB_DATABASE'] = '/var/db'
        args = parse_args([])
        self.assertEqual(args.host, '127.0.0.1')
        self.assertEqual(args.port, 9090)
        self.assertEqual(args.mergedb_database, '/var/db')

    def test_explicit_args_override_env(self):
        os.environ['RUNCIBLE_WEBUI_PORT'] = '9090'
        args = parse_args(['--port', '1234', '-y', 'f.yaml'])
        self.assertEqual(args.port, 1234)


class TestValidateArgs(unittest.TestCase):

    def test_rejects_no_datasource(self):
        args = parse_args([])
        with self.assertRaises(SystemExit):
            validate_args(args)

    def test_rejects_both_datasources(self):
        args = parse_args(['-y', 'f.yaml', '-m', '/var/db'])
        with self.assertRaises(SystemExit):
            validate_args(args)

    def test_accepts_single_datasource(self):
        args = parse_args(['-y', 'f.yaml'])
        validate_args(args)  # should not raise


class TestMain(unittest.TestCase):

    @mock.patch('runcible.webui.cli.create_app')
    @mock.patch('runcible.webui.cli.RuncibleService')
    def test_main_wires_service_and_app_together(self, mock_service_cls, mock_create_app):
        mock_service = mock_service_cls.return_value
        mock_app = mock_create_app.return_value

        main(['-y', 'fabric.yaml', '--host', '127.0.0.1', '--port', '9999'])

        mock_service_cls.assert_called_once_with(
            mergedb_database=None, yaml_path='fabric.yaml'
        )
        mock_create_app.assert_called_once_with(mock_service)
        mock_app.run.assert_called_once_with(host='127.0.0.1', port=9999, debug=False)

    def test_main_exits_without_a_datasource(self):
        with self.assertRaises(SystemExit):
            main([])


if __name__ == '__main__':
    unittest.main()
