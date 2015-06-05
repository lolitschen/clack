# -*- coding: utf-8 -*-

import ast
import calendar
import click
import ConfigParser
import csv
import hashlib
import json
import os
import pprint
import re
import shutil
import textwrap
import time

from . import VERSION
from botrlib import Client as BotrClient
from account_client import API as ACCOUNT_API
from unified_client import UnifiedAPI


APP_NAME = 'Clack'
DEFAULTS = {
    'key': '',
    'secret': '',
    'host': 'api.jwplatform.com',
    'port': None,
    'method': 'POST',
}
DELEGATE_LOGIN_URL = '/delegate_login/'

QUIET = False


class AliasedGroup(click.Group):

    def get_command(self, ctx, cmd_name):
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        matches = [x for x in self.list_commands(ctx)
                   if x.startswith(cmd_name)]
        if not matches:
            return None
        elif len(matches) == 1:
            return click.Group.get_command(self, ctx, matches[0])
        ctx.fail('Too many matches: %s' % ', '.join(sorted(matches)))


def edit_environment(config, update=None, *args, **kwargs):
    defaults = {
        'api': 'ms1',
        'host': 'api.jwplatform.com',
        'key': None,
        'secret': None,
        'description': None,
    }
    if update is None:
        name = user_input(
            "First give a good name for the environment you're going to add. "
            "e.g. ms1-reseller for making calls as a reseller to the media "
            "services api",
            None,
            r'^[a-zA-Z0-9-_]{1,16}$',
            "Please note an environment name needs to consist only "
            "alphanumeric (and _ -) characters and be between 1 and 16 "
            "characters long. Please try again",
        )
    else:
        name = update
        for var in defaults:
            try:
                defaults[var] = config.get(name, var)
            except ConfigParser.NoOptionError:
                pass
    api = user_input(
        "What type of API is this?\n"
        "  ms1 : media services api (aka botr, jwplatform)\n"
        "  ac1 : account api version 1 (as used by account dashboard)\n"
        "  ac2 : account api version 2 (as used by unified dashboard)\n",
        defaults['api'],
        r'^ms1|ac1|ac2$',
        'Please choose a valid option and try again',
        wrap=False,
    )
    host = user_input(
        "Please provide the hostname for this environment",
        defaults['host'],
        r'^[a-zA-Z0-9-.]+\.(jwplatform|jwplayer|longtailvideo)\.com$',
        "The hostname is not correct, please try again",
    )
    key = user_input(
        "Please provide the API key for this user",
        defaults['key'],
        r'^[a-zA-Z0-9]{8,}$',
        "A API is alphanumeric and at least 8 characters long. "
        "Please try again",
    )
    secret = user_input(
        "Please provide the API secret for this user",
        defaults['secret'],
        r'^[a-zA-Z0-9]{20,}$',
        "A API is alphanumeric and at least 20 characters long. "
        "Please try again",
    )
    description = user_input(
        "Please add a description for this environment",
        defaults['description'],
    )
    if name and host and key and secret and update is None:
        config.add_section(name)
    if name and host and key and secret:
        config.set(name, 'key', key)
        config.set(name, 'secret', secret)
        config.set(name, 'host', host)
        config.set(name, 'description', description)
        config.set(name, 'api', api)
    return config


def call_ac1(key, secret, host, apicall, params, show_output=True):
    api = ACCOUNT_API(key, secret, host=host)
    params['api_format'] = 'json'
    resp = api.call(apicall, params)
    try:
        resp = json.loads(resp)
        if show_output:
            pprint.pprint(resp, indent=4)
        if resp['status'] == 'success':
            return True
        else:
            e("\nCALL FAILED PLEASE CHECK OUTPUT ABOVE!", force=show_output)
            return False
    except ValueError:
        e("%s" % resp, force=show_output)


def call_ac2(key, secret, host, apicall, method, params, show_output=True):
    apicall = "/v2/%s" % apicall
    api = UnifiedAPI(key, secret, host=host)
    resp = api.call(apicall, method, params)
    try:
        resp = json.loads(resp)
        if show_output:
            pprint.pprint(resp, indent=4)
        return True
    except ValueError:
        e("%s" % resp, force=show_output)
        return False


def call_ms1(key, secret, host, port, apicall, params, show_output=True):
    msa = BotrClient(
        key,
        secret,
        host=host,
        port=port,
        protocol='https',
        client='clack',
    )
    resp = msa.request(apicall, params)
    if params['api_format'] == 'py':
        if show_output:
            pprint.pprint(resp, indent=4)
        if resp['status'] == 'ok':
            return True
        else:
            return False
            e("\nCALL FAILED PLEASE CHECK OUTPUT ABOVE!")
    else:
        e("%s" % resp, force=show_output)
        return True


def config_path():
    return os.path.join(
        click.get_app_dir(APP_NAME, force_posix=True), 'config.ini'
    )


def e(m, force=False, wrap=True):
    """
    Shorthand for the click.echo function. Also checks if output is allowed.
    """
    if not QUIET or force:
        if isinstance(m, list) and len(m) == 2:
            if wrap:
                m[1] = "\n                          "\
                    .join(textwrap.wrap(m[1], 54))
            click.echo("%s: %s" % (
                '{:<19}'.format(m[0]), m[1]))
        else:
            if wrap:
                m = textwrap.fill(m, 80)
            click.echo(m)


def list_configs(config):
    try:
        default = config.get('etc', 'default')
    except (ConfigParser.NoSectionError, ConfigParser.NoOptionError):
        default = None
    e("The following environments are available:\n")
    sections = [s for s in config.sections() if not s == 'etc']
    if sections:
        e(['  CONFIG NAME', 'API, DESCRIPTION'])
        e([
            '------------------',
            '------------------------------------------------------'
        ])
        for i, section in enumerate(sections):
            description = 'no description'
            if section == default or (default is None and i < 1):
                section_str = "+ %s" % section
            else:
                section_str = "  %s" % section
            if config.has_option(section, 'description'):
                description = config.get(section, 'description')
            api = 'ms1'
            if config.has_option(section, 'api'):
                api = config.get(section, 'api')
            e([section_str, api + ", " + description])
        e("\nThe + marks the default environment.\n")
        return True
    else:
        e(
            "\n        NO CONFIGURATIONS FOUND\n"
            "\nPlease run 'clack add' to add configurations.",
            wrap=False
        )
        return False


def p(m, default=None, wrap=True):
    """
    Shorthand for click.echo, but with textwrapping.
    """
    if wrap:
        return click.prompt(textwrap.fill(m, 80), default=default)
    return click.prompt(m, default=default)


def read_config():
    cfg_file = config_path()
    config = ConfigParser.RawConfigParser(allow_no_value=True)
    config.read([cfg_file])
    return config


def save_config(config):
    with open(config_path(), 'wb') as cfp:
        config.write(cfp)


def unicode_csv_reader(utf8_data, dialect=csv.excel, **kwargs):
    csv_reader = csv.reader(utf8_data, dialect=dialect, **kwargs)
    for row in csv_reader:
        yield [unicode(cell, 'utf-8') for cell in row]


def user_input(question, default=None, regex=None, error=None, wrap=True):
    val = p(question, default=default, wrap=wrap)
    if not val and default:
        return default
    if regex is None:
        return val
    elif re.match(regex, val):
        return val
    if error is not None:
        e(error)
    return user_input(question, default, regex, error, wrap)


@click.group(
    cls=AliasedGroup,
    help="Clack is a Command Line Api Calling Kit based on Click",
    short_help="Clack is a Command Line Api Calling Kit based on Click",
    epilog="If this is your first time using clack, please run 'clack init' "
    "to initialize a config file. If you're comfortable enough you can edit "
    "this file directly. The location of the config file is:\n%s"
    % config_path(),
    # invoke_without_command=True,
)
@click.version_option(
    version=VERSION,
    message='Clack-%(version)s',
)
def clack():
    pass


@click.command(help="Add another environment/user combo")
def add(*args, **kwargs):
    config = read_config()
    e(
        'Answer the following questions to add a new '
        'environment/user combo'
    )
    config = edit_environment(config, *args, **kwargs)
    save_config(config)


clack.add_command(add)


@click.command(help="Make an api call")
@click.option(
    '--env', '-e',
    default="default",
    metavar="ENVIRONMENT",
    help='Choose your environment',
)
@click.option(
    '--api', '-a',
    help='Choose the api you want to make calls to',
    type=click.Choice(['ms1', 'ac1', 'ac2']),
    envvar='CLACK_API',
)
@click.option(
    '--key', '-k',
    help='Set a custom key for API Calls',
    metavar='KEY',
    envvar='CLACK_KEY',
)
@click.option(
    '--secret', '-s',
    help='Set a custom secret for API Calls',
    metavar='SECRET',
    envvar='CLACK_SECRET',
)
@click.option(
    '--host', '-h',
    help='Set a custom host for making API Calls',
    metavar='HOSTNAME',
    envvar='CLACK_HOST',
)
@click.option(
    '--format', '-f',
    help="Choose the format for the output. (Only works with ms1 api calls)",
    envvar='CLACK_FORMAT',
    default='py',
    type=click.Choice(['py', 'json', 'xml', 'php'])
)
@click.option(
    '--method', '-m',
    help="Choose the HTTP method for your call. "
    "(Only works with ac2 api calls)",
    envvar='CLACK_METHOD',
    default='post',
    type=click.Choice(['delete', 'get', 'post', 'put'])
)
@click.option(
    '--quiet', '-q',
    help='Make the script shut up, only ouputs result of call',
    is_flag=True,
)
@click.option(
    '--dry-run',
    help='Do all but making the actual call',
    is_flag=True,
)
@click.argument('apicall', required=True)
@click.argument('params', required=False)
def call(apicall=None, params=None, *args, **kwargs):
    global QUIET
    QUIET = kwargs.get('quiet', False)
    config = read_config()
    return _call(config, apicall, params, *args, **kwargs)

clack.add_command(call)


@click.command(help="Make a batch of api calls.")
@click.option(
    '--env', '-e',
    default="default",
    metavar="ENVIRONMENT",
    help='Choose your environment',
)
@click.option(
    '--api', '-a',
    help='Choose the api you want to make calls to',
    type=click.Choice(['ms1', 'ac1', 'ac2']),
    envvar='CLACK_API',
)
@click.option(
    '--key', '-k',
    help='Set a custom key for API Calls',
    metavar='KEY',
    envvar='CLACK_KEY',
)
@click.option(
    '--secret', '-s',
    help='Set a custom secret for API Calls',
    metavar='SECRET',
    envvar='CLACK_SECRET',
)
@click.option(
    '--host', '-h',
    help='Set a custom host for making API Calls',
    metavar='HOSTNAME',
    envvar='CLACK_HOST',
)
@click.option(
    '--method', '-m',
    help="Choose the HTTP method for your call. "
    "(Only works with ac2 api calls)",
    envvar='CLACK_METHOD',
    default='post',
    type=click.Choice(['delete', 'get', 'post', 'put'])
)
@click.option(
    '--verbose', '-v',
    help="Make the output more verbose and return the complete response of "
    "each API call. By default only a success status will be returned.",
    is_flag=True,
)
@click.option(
    '--dry-run',
    help='Do all but making the actual call',
    is_flag=True,
)
@click.argument(
    'csvfile',
    required=True,
    type=click.Path()  # encoding='utf-8')
)
@click.argument('apicall', required=True)
@click.argument('params', required=True)
def batch(csvfile=None, apicall=None, params=None, *args, **kwargs):
    global QUIET
    QUIET = not kwargs.get('verbose', False)
    config = read_config()
    variables = re.findall(r'(<<(\w+)>>)', params)
    table = unicode_csv_reader(open(csvfile, 'r'))
    header = []
    for columns in table:
        if not header:
            header = columns
            continue
        prms = params
        values = {}
        for i, val in enumerate(columns):
            values[header[i]] = val
        for search_for, name in variables:
            replace_with = values.get(name, False)
            if replace_with:
                prms = prms.replace(search_for, replace_with)
        ok = _call(config, apicall, prms, True, *args, **kwargs)
        ok = 'ok   ' if ok else 'error'
        e("- %s: %s" % (ok, prms), force=True)

clack.add_command(batch)


def _call(config, apicall=None, params=None, resp=False, *args, **kwargs):
    env = kwargs.get('env', 'default')

    if env == 'default':
        try:
            env = config.get('etc', 'default')
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError):
            try:
                env = config.sections()[0]
            except IndexError:
                pass

    def _get(name):
        val = kwargs.get(name, None)
        if val is not None:
            return val
        if config.has_option(env, name):
            return config.get(env, name)
        return DEFAULTS.get(name, None)

    api = _get('api')
    key = _get('key')
    secret = _get('secret')
    host = _get('host')

    if not api or not key or not secret or not host:
        e(
            "There is not enough information to make an API call."
            "Setup your configuration correctly or provide the correct "
            "command line options. Run 'clack --help' for more info. "
            "Aborting now.",
            force=True
        )
        return

    if params is not None:
        try:
            params = ast.literal_eval(params)
        except:
            e('We failed interpreting your params')
            e("%s" % params)
            return
        if not isinstance(params, dict):
            e("Your params where malformatted. Aborting now", force=True)
            return
    else:
        params = {}

    if api == 'ms1':
        params['api_format'] = kwargs.get('format', 'py')

    e("Environment is %s" % env)

    e('\n---------------------------------------------\n', wrap=False)
    e(['api', api])
    e(['key', key])
    e(['secret', secret])
    e(['host', host])
    e(['call', apicall])
    if api == 'ac2':
        method = _get('method')
        e(['method', method])
    e(['params', "%s" % params])
    e('\n---------------------------------------------\n', wrap=False)

    if kwargs.get('dry_run', False):
        e("Only doing a dry run. Exiting now", force=True)
        return

    verbose = kwargs.get('verbose', True)
    if api == 'ac1':
        ok = call_ac1(key, secret, host, apicall, params, show_output=verbose)
    elif api == 'ac2':
        ok = call_ac2(key, secret, host, apicall, method, params,
                      show_output=verbose)
    else:
        ok = call_ms1(key, secret, host, _get('port'), apicall, params,
                      show_output=verbose)
    e('\n---------------------------------------------\n', wrap=False)
    e('Done.')
    if resp:
        return ok
    return


@click.command(help="Edit an existing environment/user combo")
@click.argument(
    'name',
    metavar='CONFIG_NAME',
    required=False,
)
def edit(name=None, *args, **kwargs):
    config = read_config()
    if not name:
        list_configs(config)
        name = p(
            "\nPlease give the name of the config you want to update"
        )
    if not config.has_section(name):
        e(
            'The config you selected (%s) does not exist. Please try again'
            % name
        )
        return
    config = edit_environment(config, name)
    save_config(config)
    e('Config "%s" has been updated' % name)


clack.add_command(edit)


@click.command(help="Initialize your config file")
@click.option(
    '--force',
    is_flag=True,
)
def init(force, *args, **kwargs):
    e("Initializing your config file")
    path = click.get_app_dir(APP_NAME, force_posix=True)
    if os.path.exists(path):
        if force:
            try:
                shutil.rmtree(path)
            except:
                e(
                    "There already is a config and the script cannot remove "
                    "it. Please do so manually and rerun this command. You "
                    "need to delete the directory %s" % path
                )
                return
        else:
            e(
                'There already is a config. Please use the "--force" option '
                'to force a new config setup'
            )
            return
    os.mkdir(path)
    config = ConfigParser.RawConfigParser(allow_no_value=True)
    e(
        'Please answer the following question to add your first '
        'environment/user combo'
    )
    config = edit_environment(config, *args, **kwargs)
    save_config(config)


clack.add_command(init)


@click.command("ls", help="List all available environment/user combos")
def ls():
    config = read_config()
    return list_configs(config)


clack.add_command(ls)


@click.command(
    "rm",
    help="Remove an existing environment/user combo"
)
@click.argument(
    'name',
    metavar='CONFIG_NAME',
    required=False,
)
def remove(name=None, *args, **kwargs):
    config = read_config()
    if not name:
        if list_configs(config):
            name = p(
                "\nPlease give the name of the config you want to delete"
            )
        else:
            e(
                'In other words there are no configurations to remove. '
                'Aborting now.'
            )
            return
    if not config.has_section(name):
        e(
            'The config you selected (%s) does not exist. Please try again'
            % name
        )
        return
    if click.confirm('You are about to delete "%s". Are you sure?' % name):
        config.remove_section(name)
        save_config(config)
        e('Config "%s" has been successfully deleted' % name)
    else:
        e('Aborted')
    return


clack.add_command(remove)


@click.command(
    "set",
    help="Set the config you want to use by default"
)
@click.argument(
    'name',
    metavar='CONFIG_NAME',
    required=False,
)
def set_default(name=None, *args, **kwargs):
    config = read_config()
    if not name:
        if list_configs(config):
            name = p(
                "\nPlease give the name of the config you want to set as "
                "default"
            )
        else:
            e('You cannot set a default configuration this way.')
            return
    if not config.has_section(name):
        e(
            'The config you selected (%s) does not exist. Please try again'
            % name
        )
        return
    if not config.has_section('etc'):
        config.add_section('etc')
    config.set('etc', 'default', name)
    save_config(config)
    e('Config "%s" has been set as the default config' % name)

clack.add_command(set_default)


@click.command(
    "delegate",
    help="Create a deferred login link for JW Platform",
)
@click.option(
    '--host', '-h',
    help='Set a custom host for making API Calls',
    metavar='HOSTNAME',
    envvar='CLACK_HOST',
    default='dashboard.jwplatform.com',
)
@click.argument(
    "key",
    metavar='KEY',
    required=True,
    # help="The API key for this user",
)
@click.argument(
    "secret",
    metavar='SECRET',
    required=True,
    # help="The API secret for this user",
)
@click.argument(
    "duration",
    metavar='SECS',
    required=False,
    # help="The the validity of the key in seconds.",
    type=click.INT,
    default=300,
)
def delegate(key, secret, duration, host):
    """
        This function creates a delegate login url to
        automatically log users into the platform dashboard.
    """
    timestamp = calendar.timegm(time.gmtime()) + duration
    query_string = "account_key=%s&auth_key=%s" % (key, key)

    # if redirect is not None:
    #     query_string += "&redirect=%s" % urllib.quote_plus(redirect)

    timestamp_query = "&timestamp=%s" % (timestamp)
    signature = hashlib.sha1(query_string + timestamp_query + secret)\
        .hexdigest()

    query_string += "&signature=%s" % signature
    query_string += timestamp_query

    e("http://%s%s?%s" % (host, DELEGATE_LOGIN_URL, query_string))

clack.add_command(delegate)