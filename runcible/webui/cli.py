import argparse
import os

from runcible.webui.app import create_app
from runcible.webui.service import RuncibleService


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Runs the runcible web UI: browse managed devices, view "
                     "desired-vs-current diffs/plans, and trigger runs."
    )
    parser.add_argument('--host', type=str,
                         default=os.environ.get('RUNCIBLE_WEBUI_HOST', '0.0.0.0'),
                         help="Interface to bind to. Can also be specified via "
                              "environment variable 'RUNCIBLE_WEBUI_HOST'")
    parser.add_argument('--port', type=int,
                         default=int(os.environ.get('RUNCIBLE_WEBUI_PORT', '8080')),
                         help="Port to listen on. Can also be specified via "
                              "environment variable 'RUNCIBLE_WEBUI_PORT'")
    parser.add_argument('--debug', action='store_true', default=False,
                         help="Run the Flask development server in debug mode")
    datasource_args = parser.add_argument_group("Datasources")
    datasource_args.add_argument('-m', '--mergedb-database', type=str,
                                  default=os.environ.get("MERGEDB_DATABASE", None),
                                  dest='mergedb_database',
                                  help="Path to the base directory of a MergeDB database. "
                                       "Can also be specified via environment variable "
                                       "'MERGEDB_DATABASE'")
    datasource_args.add_argument('-y', '--yaml', type=str,
                                  dest='yaml',
                                  default=os.environ.get("RUNCIBLE_YAML", None),
                                  help="Path to a yaml definition file. Can also be "
                                       "specified via environment variable "
                                       "'RUNCIBLE_YAML'")
    return parser.parse_args(argv)


def validate_args(args):
    if args.yaml and args.mergedb_database:
        raise SystemExit("Only one datasource can be specified")
    if not args.yaml and not args.mergedb_database:
        raise SystemExit("You must specify a datasource with -m or -y (or the "
                          "MERGEDB_DATABASE/RUNCIBLE_YAML environment variables)")


def main(argv=None):
    args = parse_args(argv)
    validate_args(args)
    service = RuncibleService(mergedb_database=args.mergedb_database, yaml_path=args.yaml)
    app = create_app(service)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
