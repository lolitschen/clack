import click
import os
import shutil

from environment import Environment


class SettingsCommands(object):

    @staticmethod
    def _get_and_check_name(env, name, action):
        if name is None:
            env.list()
            name = env.input("Please give the name of the config you want to {!s}".format(action))
        if not env.config.has_section(name):
            return env.abort(
                'The name you selected ({!s}) does not exist. Please try again'.format(name)
            )
        return name

    @staticmethod
    def add(*args, **kwargs):
        env = Environment(*args, **kwargs)
        env.check()
        env.echo('Answer the following questions to add a new set of API settings.')
        env.edit()
        env.save()
        env.echo("Done.")

    @staticmethod
    def default(name=None, *args, **kwargs):
        env = Environment(*args, **kwargs)
        name = SettingsCommands._get_and_check_name(env, name, 'use as default')
        env.set_default(name)
        env.echo('"{!s}" has been set as the default.'.format(name))

    @staticmethod
    def edit(name=None, *args, **kwargs):
        env = Environment(*args, **kwargs)
        name = SettingsCommands._get_and_check_name(env, name, 'edit')
        env.edit(update_for_name=name)
        env.save()
        env.echo("Done.")

    @staticmethod
    def list(*args, **kwargs):
        env = Environment(*args, **kwargs)
        env.list()

    @staticmethod
    def remove(name=None, *args, **kwargs):
        env = Environment(*args, **kwargs)
        name = SettingsCommands._get_and_check_name(env, name, 'remove')
        if not env.options.yes and not click.confirm('Are you sure you want to remove "{!s}"?'.format(name)):
            env.abort('OK.', error=False)
            return
        key = env.get(name, 'key')
        if key is not None:
            env.delete_secret(name, key, fail_silent=True)
        env.config.remove_section(name)
        env.save()
        env.echo('"{!s}" has been deleted'.format(name))
        return

    @staticmethod
    def show(name=None, *args, **kwargs):
        env = Environment(*args, **kwargs)
        name = SettingsCommands._get_and_check_name(env, name, 'show')
        env.echo("These are the settings for \"{!s}\":".format(name))
        env.api_settings(name)

    @staticmethod
    def purge(*args, **kwargs):
        env = Environment(*args, **kwargs)
        env.echo("You are about to delete all your API settings.")
        if not click.confirm("Are you sure?"):
            return env.abort("Ok.", error=False)
        env.echo("1. Removing API settings.")
        for section in env.sections:
            key = env.get(section, 'key')
            if key is not None:
                env.delete_secret(section, key, fail_silent=True)
            env.config.remove_section(section)
            env.echo("  - {!s}".format(section))
        env.echo("2. Removing generic settings")
        if env.config.has_section('etc'):
            env.config.remove_section('etc')
        env.echo("3. Removing config file. ")
        try:
            shutil.rmtree(os.path.dirname(env.config_path()))
        except OSError:
            return env.abort(
                'Could not remove the config directory ({!s}). Please remove it yourself to complete '
                'a full reset.'.format(os.path.dirname(env.config_path()))
            )
        env.echo("Done.")
