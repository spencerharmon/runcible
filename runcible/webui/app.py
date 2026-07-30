from flask import Flask, abort, jsonify, render_template, request


def create_app(service):
    """
    Flask application factory for the runcible web UI.

    :param service:
        A :class:`runcible.webui.service.RuncibleService` instance (or any
        object implementing the same ``list_devices``/``get_plan``/
        ``execute`` interface) used to answer every route.
    """
    app = Flask(__name__)
    app.config['RUNCIBLE_SERVICE'] = service

    def _target_for(name):
        # Anchor the regex so that browsing/triggering a single device by
        # name never accidentally matches other devices sharing a prefix.
        return f'^{name}$'

    @app.get('/')
    def index():
        devices = service.list_devices()
        return render_template('index.html', devices=devices)

    @app.get('/devices/<path:name>')
    def device_detail(name):
        plan = service.get_plan(target=_target_for(name))
        if name not in plan:
            abort(404)
        return render_template('device.html', name=name, plan=plan[name])

    @app.post('/devices/<path:name>/run')
    def device_run(name):
        result = service.execute(target=_target_for(name))
        if name not in result:
            abort(404)
        return render_template('run_result.html', name=name, result=result[name])

    @app.get('/api/devices')
    def api_devices():
        target = request.args.get('target', '.*')
        return jsonify(service.list_devices(target=target))

    @app.get('/api/devices/plan')
    def api_plan():
        target = request.args.get('target', '.*')
        return jsonify(service.get_plan(target=target))

    @app.post('/api/devices/run')
    def api_run():
        target = request.args.get('target', '.*')
        return jsonify(service.execute(target=target))

    @app.get('/healthz')
    def healthz():
        return jsonify({'status': 'ok'})

    return app
