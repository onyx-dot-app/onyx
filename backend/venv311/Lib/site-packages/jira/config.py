"""Config handler.

This module allows people to keep their jira server credentials outside their script,
in a configuration file that is not saved in the source control.

Also, this simplifies the scripts by not having to write the same initialization code for each script.
"""

from __future__ import annotations

import configparser
import logging
import os
import sys

from jira.client import JIRA


def get_jira(
    profile: str | None = None,
    url: str = "http://localhost:2990",
    username: str = "admin",
    password: str = "admin",
    appid=None,
    autofix=False,
    verify: bool | str = True,
):
    """Return a JIRA object by loading the connection details from the `config.ini` file.

    Args:
        profile (Optional[str]): The name of the section from config.ini file that stores server config url/username/password
        url (str): URL of the Jira server
        username (str): username to use for authentication
        password (str): password to use for authentication
        appid: appid
        autofix: autofix
        verify (Union[bool, str]): True to indicate whether SSL certificates should be verified or
            str path to a CA_BUNDLE file or directory with certificates of trusted CAs. (Default: ``True``)

    Returns:
        JIRA: an instance to a JIRA object.

    Raises:
        EnvironmentError

    Usage:

        >>> from jira.config import get_jira
        >>>
        >>> jira = get_jira(profile='jira')

    Also create a `config.ini` like this and put it in current directory, user home directory or PYTHONPATH.

    .. code-block:: none

        [jira]
        url=https://jira.atlassian.com
        # only the `url` is mandatory
        user=...
        pass=...
        appid=...
        verify=...

    """

    def findfile(path):
        """Find the file named path in the sys.path.

        Returns the full path name if found, None if not found
        """
        paths = [".", os.path.expanduser("~")]
        paths.extend(sys.path)
        for dirname in paths:
            possible = os.path.abspath(os.path.join(dirname, path))
            if os.path.isfile(possible):
                return possible
        return None

    if isinstance(verify, bool):
        verify = "yes" if verify else "no"
    else:
        verify = verify

    config = configparser.ConfigParser(
        defaults={
            "user": None,
            "pass": None,
            "appid": appid,
            "autofix": autofix,
            "verify": verify,
        },
        allow_no_value=True,
    )

    config_file = findfile("config.ini")
    if config_file:
        logging.debug(f"Found {config_file} config file")

    if not profile:
        if config_file:
            config.read(config_file)
            try:
                profile = config.get("general", "default-jira-profile")
            except configparser.NoOptionError:
                pass

    if profile:
        if config_file:
            config.read(config_file)
            url = config.get(profile, "url")
            username = config.get(profile, "user")
            password = config.get(profile, "pass")
            appid = config.get(profile, "appid")
            autofix = config.get(profile, "autofix")
            try:
                verify = config.getboolean(profile, "verify")
            except ValueError:
                verify = config.get(profile, "verify")
        else:
            raise OSError(
                f"{__name__} was not able to locate the config.ini file in current directory, user home directory or PYTHONPATH."
            )

    options = JIRA.DEFAULT_OPTIONS
    options["server"] = url
    options["autofix"] = autofix
    options["appid"] = appid
    options["verify"] = verify

    return JIRA(options=options, basic_auth=(username, password))
    # self.jira.config.debug = debug
