# -*- coding: utf-8 -*-
from makerbot_tools.client import call
from makerbot_tools.crontab import Crontab
import subprocess
import bottle
import time
import glob
import os

upload_dir = os.path.expanduser('~/gcodes')
try:
    os.makedirs(upload_dir)
except OSError:
    # dir exist
    pass

dirname = os.path.abspath(os.path.dirname(__file__))

client = os.path.join(
    os.path.dirname(dirname),
    'bin', 'conveyor-client')

printer = os.path.join(
    os.path.dirname(dirname),
    'bin', 'print')

config = os.path.join(
    os.path.dirname(dirname),
    'conveyor-dev.conf')

bottle.TEMPLATE_PATH.append(
    os.path.join(dirname, 'views')
)
static_root = os.path.join(dirname, 'static')


def call_client(method, args=None):
    if args is None:
        args = {}
    method = {
        'printers': 'getprinters',
        'ports': 'getports',
        'jobs': 'getjobs',
    }.get(method, method)
    if method == 'connect':
        args = {
            'machine_name': None,
            'port_name': None,
            'driver_name': None,
            'profile_name': None,
            'persistent': False,
        }
    code, data = call(config, method, args)
    if code == 0:
        data = dict(success=True, result=data)
    else:
        data = dict(success=False)
    return data


def client_response(*args):
    def req():
        return call_client(*args)
    return req

for cmd in ('printers', 'profiles', 'jobs', 'drivers'):
    bottle.get('/api/' + cmd, callback=client_response(cmd))

for cmd in ('connect', 'disconnect'):
    bottle.get('/api/' + cmd, callback=client_response(cmd))


def ng(value):
    return '{{ %s }}' % value


@bottle.get('/')
@bottle.view('index')
def index():
    return {'ng': ng}


@bottle.get('/crons')
@bottle.view('cron')
def crons():
    filenames = []
    for filename in sorted(glob.glob(os.path.join(upload_dir, '*.gcode'))):
        basename = os.path.basename(filename)
        filenames.append(basename)

    crontab = Crontab(printer)
    crontab.read()

    return {'ng': ng, 'crontab': crontab, 'filenames': filenames}


@bottle.post('/crons')
def post_crons():
    tasks = []
    mapping = {}
    data = bottle.request.POST
    for k, v in data.items():
        if k.startswith('cron_') or k.startswith('file_'):
            k, i = k.split('_')
            task = mapping.setdefault(i, {})
            if k == 'file':
                v = os.path.join(upload_dir, v)
            task[k] = v
    tasks.extend([v for k, v in sorted(mapping.items())])
    if data.get('file'):
        tasks.append({'cron': data.get('cron'),
                      'file': os.path.join(upload_dir, data.get('file'))})
    crontab = Crontab(printer, upload_dir=upload_dir)
    crontab.write(tasks)
    return crons()


@bottle.get('/api/files')
def files():
    data = []
    for filename in sorted(glob.glob(os.path.join(upload_dir, '*.gcode'))):
        basename = os.path.basename(filename)
        data.append(dict(
            name=basename,
            print_url='/api/print/' + basename,
        ))
    return dict(files=data)


@bottle.get('/api/print/:filename')
def print_file(filename=None):
    p = subprocess.Popen(
        [client, 'print', '--has-start-end', filename],
        close_fds=True,
    )
    time.sleep(1)
    data = call_client('jobs')
    if p.poll() is None:
        # process working
        return dict(success=True, result=data)
    else:
        return dict(success=False, result=data)


@bottle.put('/upload')
def upload():
    fd = bottle.request.environ['wsgi.input']
    clength = bottle.request.content_length
    length = 0
    filename = fdout = None
    line = '-'
    while not line.startswith('------'):
        line = fd.readline()
        length += len(line)
        if length >= clength:
            bottle.abort(400)
    boundary = len(line) + 2
    while not line.startswith('Content-Disposition'):
        line = fd.readline()
        length += len(line)
        if length >= clength:
            bottle.abort(400)

    filename = line.split('filename=')[1].strip().strip('"')
    filename = os.path.basename(filename)
    filename = filename.replace(' ', '_')

    if not filename.endswith('.gcode'):
        bottle.abort(400)

    while line != '\r\n':
        line = fd.readline()
        length += len(line)
        if length >= clength:
            return dict(result=dict(files=['Invalid upload']))

    with open(os.path.join(upload_dir, filename), 'wb') as fdout:
        for line in fd:
            length += len(line)
            if length + boundary >= clength:
                break
            fdout.write(line)
    return files()


@bottle.route('/static/<path:path>')
def static(path):
    return bottle.static_file(path, static_root)


def make_app():
    bottle.debug(mode=False)
    return bottle.default_app()
