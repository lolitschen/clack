import click
import ConfigParser
import keyring
import json
import os
import pprint
import re
import sys

from distutils.version import StrictVersion
from pygments import highlight
from pygments import lexer
from pygments import token
from pygments.lexers import JsonLexer
from pygments.lexers import PythonLexer
from pygments.formatters import Terminal256Formatter
from pygments.formatters import TerminalFormatter
from pygments.styles import STYLE_MAP

from version import VERSION

try:
    import curses
except ImportError:
    curses = None  # Compiled w/o curses


APP_NAME = 'Clack'
DEFAULT_INDENT = 4
KEYRING_ID = 'com.github.rmnl.clack.'
TAB_SIZE = 4

COMMON_SETTINGS = {
    'color_scheme': {
        'default': 'monokai',
        'options': ['no-colors', ] + STYLE_MAP.keys(),
    },
    'output': {
        'default': 'json',
        'options': ['json', 'py'],
    },
    'verbosity': {
        'default': 'auto',
        'options': ['auto', 'quiet', 'verbose'],
    },
}

OUTPUT_OPTIONS = ['json', 'py']

API_DEFAULT_HOSTS = {
    'ms1': 'api.jwplatform.com',
    'ac2': 'api.jwplayer.com',
}

STYLES = {
    'heading': {
        'fg': 'black',
        'bg': 'yellow',
        'reverse': True,
    },
    'error': {
        'fg': 'white',
        'bg': 'red',
        'reverse': False,
    }
}

OUTPUT_LEXERS = {
    'json': JsonLexer,
    'py': PythonLexer,
}


class Options(object):
    """ Simple class to manage values in a dictionary as class properties.
    """

    def __init__(self, initial={}, **kwargs):
        self.options = dict(initial.items() + kwargs.items())

    def __getattr__(self, name):
        return self.get(name)

    def __setattr___(self, name, value):
        self.options[name] = value

    def dict(self):
        return self.options

    def get(self, name, default=None):
        return self.options.get(name, default)


class Environment(object):
    """ Class contains miscellaneous functions for dealing with all settings
        user in- and output.
    """

    color_scheme = COMMON_SETTINGS['color_scheme']['default']
    output = COMMON_SETTINGS['output']['default']
    verbosity = COMMON_SETTINGS['verbosity']['default']

    is_windows = 'win32' in str(sys.platform).lower()
    stdout_isatty = sys.stdout.isatty()
    term_colors = 256
    term_width, term_height = click.get_terminal_size()

    def __init__(self, command="settings", *args, **kwargs):
        self.command = command
        # Initialize the config and the options
        self.options = Options(**kwargs)
        self.config = ConfigParser.RawConfigParser(allow_no_value=True)
        self.config.read([Environment.config_path()])
        # Set the default settings:
        for key in COMMON_SETTINGS:
            # First the setting per call, then the default settings
            val = kwargs.get(key)
            setattr(self, key, self.get('etc', key, COMMON_SETTINGS.get(key)['default']) if val is None else val)
        self.use_colors = (self.color_scheme != 'no-colors' and
                           self.stdout_isatty and
                           not self.options.no_formatting and
                           not self.is_windows)
        # Set the number of colors of the terminal
        if not self.is_windows and curses:
            try:
                curses.setupterm()
                self.term_colors = curses.tigetnum('colors')
            except curses.error:
                pass
        # Check the config file version and upgrade if necessary
        self.check_and_upgrade_config()

    # Config file management

    @property
    def default(self):
        """ Returns the set of API settings that was marked as default
        """
        fallback = self.sections[0] if len(self.sections) > 0 else None
        return self.get('etc', 'env', self.get('etc', 'default', fallback))

    @property
    def sections(self):
        """ Returns a list of sections in the config file
        """
        return [s for s in self.config.sections() if not s == 'etc']

    def check_and_upgrade_config(self):
        version = self.get('etc', 'version', '0.0.1')
        upgrades = []

        if StrictVersion(version) < StrictVersion('0.4.0'):
            upgrades.append('Moving secrets/passwords from config file to keyring for:')
            for section in self.sections:
                key = self.get(section, 'key')
                secret = self.get(section, 'secret')
                if key and secret:
                    self.set_secret(section, key, secret)
                    self.set(section, 'secret', None)
                    upgrades.append('- {!s}'.format(section))

        if StrictVersion(version) < StrictVersion('0.5.0'):
            upgrades.append('Removing ac1 configurations because that API no longer exists')
            for section in self.sections:
                api = self.get(section, 'api')
                if not api == 'ac1':
                    continue
                key = self.get(section, 'key')
                self.config.remove_section(section)
                if key:
                    self.delete_secret(section, key)
                upgrades.append('- Removed: {!s}'.format(section))
            if not self.get('etc', 'default') in self.sections:
                self.set('etc', 'default', self.sections[0] if self.sections else None)

        if StrictVersion(version) < StrictVersion('2.0.0b3'):
            upgrades.append('Renaming default to env.')
            default = self.get('etc', 'default')
            if default is not None:
                self.set('etc', 'default', None)
                self.set('etc', 'env', default)
            upgrades.append('Adding defaults.')
            for opt in COMMON_SETTINGS:
                self.set('etc', opt, COMMON_SETTINGS[opt]['default'])

        if len(upgrades) > 0:
            self.set('etc', 'version', VERSION)
            self.save()
            if version == '0.0.1':
                self.echo("Created your config file.", style="heading")
            else:
                self.echo('Upgraded your config file to the latest version.', style='heading')
                self.echo(upgrades)

    @staticmethod
    def config_path():
        """ Returns the path of the config file.
        """
        return os.path.join(
            click.get_app_dir(APP_NAME, force_posix=True), 'config.ini'
        )

    def get(self, section, key, fallback=None):
        """ Get a value in the config file for `key` in `section` with
            `fallback` value if the `key` cannot be found.
        """
        if self.config.has_section(section) and self.config.has_option(section, key):
            return self.config.get(section, key)
        return fallback

    def set(self, section, key, value):
        if value is None:
            if self.get(section, key) is not None:
                self.config.remove_option(section, key)
            return
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, value)

    def save(self):
        """ Save the config file
        """
        with open(Environment.config_path(), 'wb') as cfp:
            self.config.write(cfp)

    def check(self):
        """ Check if the config file exists and create it if it doesn't
        """
        path = click.get_app_dir(APP_NAME, force_posix=True)
        if os.path.exists(path) and os.access(path, os.W_OK):
            return None
        elif os.path.exists(path):
            return self.abort(
                'Clack must be able to write to directory {!s}, if you want to use a config file.'.format(path)
            )
        # Check if the homedir is writable.
        if not os.access(os.path.dirname(path), os.W_OK):
            return self.abort(
                'Clack wants to create the directory {!s}. This directory is used to store the config file. '
                'You can also create it yourself.'.format(path)
            )
        # Create the directory.
        self.echo(
            "Creating clack's config directory: {!s} ".format(path)
        )
        os.mkdir(path)
        return None

    # Keyring management

    def _keyring_id(self, section_name):
        """ Returns the keyring id for a section/set of settings
        """
        return '{!s}{!s}'.format(KEYRING_ID, section_name)

    def get_secret(self, name, key):
        """ Get the secret for section `name` and key `key` from the user's keyring
        """
        return keyring.get_password('{!s}{!s}'.format(KEYRING_ID, name), key)

    def set_secret(self, name, key, secret):
        """ Set the secret for section `name` and key `key` in the user's keyring
        """
        keyring.set_password('{!s}{!s}'.format(KEYRING_ID, name), key, secret)

    def delete_secret(self, name, key, fail_silent=False):
        """ Delete the secret for section `name` and key `key` from the user's keyring
        """
        try:
            keyring.delete_password('{!s}{!s}'.format(KEYRING_ID, name), key)
        except keyring.errors.PasswordDeleteError as e:
            if not fail_silent:
                raise e

    # Terminal output

    def abort(self, msg, error=True):
        if error:
            self.echo("Error:", style='error', force=True)
        self.echo(msg, force=True)
        self.echo('Aborting.', force=True)
        sys.exit(1)

    def echo(self, msg, force=False, style=None, *args, **kwargs):
        """ Outputs a message `msg` to the the stdout
        """
        if not self.command == 'settings' and not force:
            if self.stdout_isatty and self.verbosity == 'quiet':
                return
            elif not self.stdout_isatty and not self.verbosity != 'verbose':
                return
        # Stringify the message
        if isinstance(msg, list):
            for line in msg:
                self.echo(line, force=force, *args, **kwargs)
        else:
            if style is not None and STYLES.get(style) is not None:
                msg = ("{:<" + str(self.term_width) + "}").format(msg)
                msg = self.style(msg, fg=STYLES[style]['fg'], bg=STYLES[style]['bg'],
                                 reverse=STYLES[style]['reverse'])
            if not isinstance(msg, basestring):
                msg = "{!s}".format(msg)
            click.echo(msg, *args, **kwargs)

    def style(self, text, *args, **kwargs):
        """ Returns click.style function if colors are allowed.
        """
        return click.style(text, *args, **kwargs) if self.use_colors else text

    def create_table(self, columns, headers=None, max_width=80, div=":"):
        """ Create a table of key and value pairs based on a list of tuples or a
            dictionary
        """
        # determine max_length
        columns = [(k, columns[k]) for k in columns] if isinstance(columns, dict) else columns
        max_length = len(headers[0]) if headers is not None else 2
        for left, right in columns:
            max_length = len(left) if len(left) > max_length else max_length
        if headers is not None:
            columns.insert(0, (max_length * "-", (max_width - max_length - len(div) - 2) * "-"))
            columns.insert(0, headers)
        lines = ["", ]
        for left, right in columns:
            right = "********" if left == 'secret' else right
            lines.append(("{:<" + str(max_length + 1) + "}{!s} {!s}").format(left, div, right))
        lines.append("")
        return lines

    def output_response(self, resp):
        if self.options.no_formatting:
            output = resp if isinstance(resp, basestring) else "{!s}".format(resp)
            return self.echo(output, force=True)
        resp_dict = resp if isinstance(resp, dict) else json.loads(resp)
        if self.output == 'py':
            output = pprint.pformat(resp_dict, indent=DEFAULT_INDENT, width=10, depth=None)
        else:
            output = json.dumps(
                obj=resp_dict,
                sort_keys=True,
                ensure_ascii=False,
                indent=DEFAULT_INDENT
            )
        return self.echo(self.colorize(output), force=True)

    def colorize(self, data):
        """ Give the terminal output some nice colors
        """
        if not self.use_colors:
            return data
        # Determine the type of terminal formatter to use
        if self.term_colors == 256:
            formatter = Terminal256Formatter(style=self.color_scheme)
        else:
            formatter = TerminalFormatter(style=self.color_scheme)

        if isinstance(data, list):
            return [highlight(line, TableLexer(), formatter).strip() for line in data]
        else:
            return highlight(data, OUTPUT_LEXERS[self.output](), formatter).strip()
        return data

    # User input

    def input(self, question, *args, **kwargs):
        """ Ask for user input
        """
        question = question if isinstance(question, basestring) else "{!s}".format(question)
        return click.prompt(question, *args, **kwargs)

    def validated_input(self, question, regex=None, options=None, error_msg=None, *args, **kwargs):
        """ Ask for user input and validate the input agains regular expression `regex`.
            Display error `error_msg if the regex does not match.
        """
        if options is not None and isinstance(options, list):
            options = [str(o) for o in options]
            question = "{!s}\n[{!s}]".format(question, "|".join(options))
        val = self.input(question, *args, **kwargs)
        if not val and kwargs.get('default'):
            return kwargs['default']
        if regex is None and options is None:
            return val
        elif options and isinstance(options, list) and val in options:
            return val
        elif regex and re.match(regex, val):
            return val
        if error_msg is not None:
            self.echo(error_msg)
        return self.validated_input(question, regex=regex, error_msg=error_msg, *args, **kwargs)

    # Settings commands

    def edit(self, update_for_name=None, *args, **kwargs):
        """ Edit a batch of settings.
            Invoked by: clack settings edit
        """
        if update_for_name is None:
            name = self.validated_input(
                "You should give a recognizable name for the api settings you're about to add. "
                "e.g. ms1-reseller for making calls as a reseller to the media services api",
                default=None,
                regex=r'^(?!etc)[a-zA-Z0-9-_]{1,16}$',
                error_msg="A name for a set of settings can only contain alphanumeric (and _ -) characters "
                          "and should be between 1 and 16 characters long (The name \"etc\" is not allowed).",
            )
            api = self.validated_input(
                "What type of API is this?\n"
                "- ms1 : media services api (aka botr, jwplatform)\n"
                "- ac2 : account api version 2 (as used by unified dashboard)\n",
                default=None,
                options=['ms1', 'ac2'],
                error_msg='Please choose a valid option and try again',
            )
            host = API_DEFAULT_HOSTS[api]
            key = None
            description = None
        else:
            name = update_for_name
            api = self.get(name, 'api')
            host = self.get(name, 'host', API_DEFAULT_HOSTS[api])
            key = self.get(name, 'key')
            description = self.get(name, 'description')
        host = self.validated_input(
            "What's the hostname for this api?",
            default=host,
            regex=r'^(http[s]{0,1}:\/\/)*[a-zA-Z0-9-.]+\.(jwplatform|jwplayer|longtailvideo|ltv)\.(com|dev)$',
            error_msg="The hostname is not correct, please try again",
        )
        verify_ssl = 'yes'
        if host.startswith('https://') and not click.confirm(
            'You have defined a https host. Do you wish to verify the SSL certificates'
        ):
            verify_ssl = 'no'
        if api == 'ac2':
            key = self.validated_input("What's the login/email for the user?", default=key)
            secret = self.validated_input(
                "What's the password? Please note that the password is stored in your system's keyring. "
                "You can also leave it empty and you will be prompted for your password with each api call",
                default="",
                hide_input=True,
            )
            is_admin = 'no'
            if key.find('@') < 0 and click.confirm(
                'Did you just enter credentials for making admin calls to the account api?'
            ):
                is_admin = 'yes'
        else:
            key = self.validated_input(
                "What's the API key for this user",
                default=key,
                regex=r'^[a-zA-Z0-9]{8,}$',
                error_msg="A API is alphanumeric and at least 8 characters long. "
                          "Please try again",
            )
            secret = self.validated_input(
                "What's API secret for this user? Please note that the secret is stored in your system's keyring. "
                "You can also leave this empty and you will be prompted for your secret with each api call.",
                default="",
                regex=r'^[a-zA-Z0-9]{20,}$|^$',
                error_msg="A API is alphanumeric and at least 20 characters long. "
                          "Please try again",
                hide_input=True,
            )
        description = self.validated_input(
            "You can add a description to make it easier to identify this set of api settings.",
            default=description,
        )
        if name and host and key:
            self.set(name, 'key', key)
            self.set(name, 'host', host)
            self.set(name, 'description', description)
            self.set(name, 'api', api)
            self.set(name, 'verify_ssl', verify_ssl)
            if api == 'ac2':
                self.set(name, 'is_admin', is_admin)
        if name and key and secret:
            self.set_secret(name, key, secret)
        elif name and key and self.get_secret(name, key):
            self.delete_secret(name, key)
        if len(self.sections) <= 1 or click.confirm('Do you want to make these settings the default settings?'):
            self.set('etc', 'env', name)

    def list(self):
        """ List all sets op API settings.
            Invoked by: clack settings list
        """
        if self.sections:
            headers = ('  CONFIG NAME', 'API, DESCRIPTION')
            sections, columns = sorted(self.sections), []
            for i, section in enumerate(sections):
                marker = "+" if self.default == section else " "
                left = "{!s} {!s}".format(marker, section)
                sections[i] = left
                description = self.get(section, 'description', 'no description')
                api = api = self.get(section, 'api', 'ms1')
                right = "{!s}, {!s}".format(api, description)
                columns.append((left, right))
            self.echo("The following API settings are available:")
            table = self.create_table(columns, headers=headers)
            # self.echo(table[:3] + self.colorize(table[3:]))
            self.echo(self.colorize(table))
            self.echo("+ marks the default environment.")
            self.echo("")
        else:
            self.echo('No saved settings found, please run "clack settings add" to add settings.')

    def api_settings(self, name, secret=True):
        """ Show a specific set of settings.
            Invoked by: clack settings show
        """
        keys = ['description', 'api', 'host', 'key']
        columns = [(key, self.get(name, key)) for key in keys]
        # secret is a special case.
        columns.append((
            'secret',
            8 * '*' if secret or self.get_secret(name, self.get(name, 'secret')) else 'Input at runtime.',
        ))
        self.echo(self.create_table(columns))


class TableLexer(lexer.RegexLexer):
    """Simplified lexer for Pygments that handles the lines in the table.
    """
    name = 'Table'
    aliases = ['table']
    filenames = ['*.table']
    tokens = {
        'root': [
            # Table line
            (r'(-+ : -+)', lexer.bygroups(
                token.Text,
            )),
            (r'(.*?)( *: *)(.+)(,?)(.*?)', lexer.bygroups(
                token.Keyword,  # Right
                token.Text,
                token.Name.Attribute,  # Left before comma
                token.Text,
                token.String  # Left after comma
            ))
        ]
    }