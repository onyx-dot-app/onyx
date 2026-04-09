"""Starts an interactive Jira session in an ipython terminal.

Script arguments support changing the server and a persistent authentication
over HTTP BASIC or Kerberos.
"""

from __future__ import annotations

import argparse
import configparser
import os
import sys
import webbrowser
from getpass import getpass
from urllib.parse import parse_qsl

import keyring
import requests
from oauthlib.oauth1 import SIGNATURE_HMAC_SHA1
from requests_oauthlib import OAuth1

from jira import JIRA, __version__

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".jira-python", "jirashell.ini")
SENTINEL = object()


def oauth_dance(server, consumer_key, key_cert_data, print_tokens=False, verify=None):
    if verify is None:
        verify = server.startswith("https")

    # step 1: get request tokens
    oauth = OAuth1(
        consumer_key, signature_method=SIGNATURE_HMAC_SHA1, rsa_key=key_cert_data
    )
    r = requests.post(
        server + "/plugins/servlet/oauth/request-token", verify=verify, auth=oauth
    )
    request = dict(parse_qsl(r.text))
    request_token = request.get("oauth_token", SENTINEL)
    request_token_secret = request.get("oauth_token_secret", SENTINEL)
    if request_token is SENTINEL or request_token_secret is SENTINEL:
        problem = request.get("oauth_problem")
        if problem is not None:
            message = f"OAuth error: {problem}"
        else:
            message = " ".join(f"{key}:{value}" for key, value in request.items())
        exit(message)

    if print_tokens:
        print("Request tokens received.")
        print(f"    Request token:        {request_token}")
        print(f"    Request token secret: {request_token_secret}")

    # step 2: prompt user to validate
    auth_url = f"{server}/plugins/servlet/oauth/authorize?oauth_token={request_token}"
    if print_tokens:
        print(f"Please visit this URL to authorize the OAuth request:\n\t{auth_url}")
    else:
        webbrowser.open_new(auth_url)
        print(
            "Your browser is opening the OAuth authorization for this client session."
        )

    approved = input(
        f"Have you authorized this program to connect on your behalf to {server}? (y/n)"
    )

    if approved.lower() != "y":
        exit(
            "Abandoning OAuth dance. Your partner faceplants. The audience boos. You feel shame."
        )

    # step 3: get access tokens for validated user
    oauth = OAuth1(
        consumer_key,
        signature_method=SIGNATURE_HMAC_SHA1,
        rsa_key=key_cert_data,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
    )
    r = requests.post(
        server + "/plugins/servlet/oauth/access-token", verify=verify, auth=oauth
    )
    access = dict(parse_qsl(r.text))

    if print_tokens:
        print("Access tokens received.")
        print(f"    Access token:        {access['oauth_token']}")
        print(f"    Access token secret: {access['oauth_token_secret']}")

    return {
        "access_token": access["oauth_token"],
        "access_token_secret": access["oauth_token_secret"],
        "consumer_key": consumer_key,
        "key_cert": key_cert_data,
    }


def process_config():
    if not os.path.exists(CONFIG_PATH):
        return {}, {}, {}, {}

    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_PATH)
    except configparser.ParsingError as err:
        print(f"Couldn't read config file at path: {CONFIG_PATH}\n{err}")
        raise

    if parser.has_section("options"):
        options = {}
        for option, value in parser.items("options"):
            if option in ("verify", "async"):
                value = parser.getboolean("options", option)  # type: ignore[assignment]
            options[option] = value
    else:
        options = {}

    if parser.has_section("basic_auth"):
        basic_auth = dict(parser.items("basic_auth"))
    else:
        basic_auth = {}

    if parser.has_section("oauth"):
        oauth = {}
        for option, value in parser.items("oauth"):
            if option in ("oauth_dance", "print_tokens"):
                value = parser.getboolean("oauth", option)  # type: ignore[assignment]
            oauth[option] = value
    else:
        oauth = {}

    if parser.has_section("kerberos_auth"):
        kerberos_auth = {}
        for option, value in parser.items("kerberos_auth"):
            if option in ("use_kerberos"):
                value = parser.getboolean("kerberos_auth", option)  # type: ignore[assignment]
            kerberos_auth[option] = value
    else:
        kerberos_auth = {}

    return options, basic_auth, oauth, kerberos_auth


def process_command_line():
    parser = argparse.ArgumentParser(
        description="Start an interactive Jira shell with the REST API."
    )
    jira_group = parser.add_argument_group("Jira server connection options")
    jira_group.add_argument(
        "-s",
        "--server",
        help="The Jira instance to connect to, including context path.",
    )
    jira_group.add_argument(
        "-r", "--rest-path", help="The root path of the REST API to use."
    )
    jira_group.add_argument("--auth-url", help="Path to URL to auth against.")
    jira_group.add_argument(
        "-v",
        "--rest-api-version",
        help="The version of the API under the specified name.",
    )

    jira_group.add_argument(
        "--no-verify", action="store_true", help="do not verify the ssl certificate"
    )

    basic_auth_group = parser.add_argument_group("BASIC auth options")
    basic_auth_group.add_argument(
        "-u", "--username", help="The username to connect to this Jira instance with."
    )
    basic_auth_group.add_argument(
        "-p", "--password", help="The password associated with this user."
    )
    basic_auth_group.add_argument(
        "-P",
        "--prompt-for-password",
        action="store_true",
        help="Prompt for the password at the command line.",
    )

    oauth_group = parser.add_argument_group("OAuth options")
    oauth_group.add_argument(
        "-od",
        "--oauth-dance",
        action="store_true",
        help="Start a 3-legged OAuth authentication dance with Jira.",
    )
    oauth_group.add_argument("-ck", "--consumer-key", help="OAuth consumer key.")
    oauth_group.add_argument(
        "-k",
        "--key-cert",
        help="Private key to sign OAuth requests with (should be the pair of the public key\
                                   configured in the Jira application link)",
    )
    oauth_group.add_argument(
        "-pt",
        "--print-tokens",
        action="store_true",
        help="Print the negotiated OAuth tokens as they are retrieved.",
    )

    oauth_already_group = parser.add_argument_group(
        "OAuth options for already-authenticated access tokens"
    )
    oauth_already_group.add_argument(
        "-at", "--access-token", help="OAuth access token for the user."
    )
    oauth_already_group.add_argument(
        "-ats", "--access-token-secret", help="Secret for the OAuth access token."
    )

    kerberos_group = parser.add_argument_group("Kerberos options")
    kerberos_group.add_argument(
        "--use-kerberos-auth", action="store_true", help="Use kerberos auth"
    )
    kerberos_group.add_argument(
        "--mutual-authentication",
        choices=["OPTIONAL", "DISABLED"],
        help="Mutual authentication",
    )
    args = parser.parse_args()

    options = {}
    if args.server:
        options["server"] = args.server

    if args.rest_path:
        options["rest_path"] = args.rest_path

    if args.auth_url:
        options["auth_url"] = args.auth_url

    if args.rest_api_version:
        options["rest_api_version"] = args.rest_api_version

    options["verify"] = True
    if args.no_verify:
        options["verify"] = False

    if args.prompt_for_password:
        args.password = getpass()

    basic_auth = {}
    if args.username:
        basic_auth["username"] = args.username

    if args.password:
        basic_auth["password"] = args.password

    key_cert_data = None
    if args.key_cert:
        with open(args.key_cert) as key_cert_file:
            key_cert_data = key_cert_file.read()

    oauth = {}
    if args.oauth_dance:
        oauth = {
            "oauth_dance": True,
            "consumer_key": args.consumer_key,
            "key_cert": key_cert_data,
            "print_tokens": args.print_tokens,
        }
    elif (
        args.access_token
        and args.access_token_secret
        and args.consumer_key
        and args.key_cert
    ):
        oauth = {
            "access_token": args.access_token,
            "oauth_dance": False,
            "access_token_secret": args.access_token_secret,
            "consumer_key": args.consumer_key,
            "key_cert": key_cert_data,
        }

    kerberos_auth = {"use_kerberos": args.use_kerberos_auth}

    if args.mutual_authentication:
        kerberos_auth["mutual_authentication"] = args.mutual_authentication

    return options, basic_auth, oauth, kerberos_auth


def get_config():
    options, basic_auth, oauth, kerberos_auth = process_config()

    cmd_options, cmd_basic_auth, cmd_oauth, cmd_kerberos_auth = process_command_line()

    options.update(cmd_options)
    basic_auth.update(cmd_basic_auth)
    oauth.update(cmd_oauth)
    kerberos_auth.update(cmd_kerberos_auth)

    return options, basic_auth, oauth, kerberos_auth


def handle_basic_auth(auth, server):
    if auth.get("password"):
        password = auth["password"]
        if input("Would you like to remember password in OS keyring? (y/n)") == "y":
            keyring.set_password(server, auth["username"], password)
    else:
        print("Getting password from keyring...")
        password = keyring.get_password(server, auth["username"])
        if not password:
            raise ValueError("No password provided!")
    return auth["username"], password


def main():
    try:
        try:
            get_ipython  # type: ignore[name-defined] # exists in ipython
        except NameError:
            pass
        else:
            sys.exit("Running ipython inside ipython isn't supported. :(")

        options, basic_auth, oauth, kerberos_auth = get_config()

        if basic_auth:
            basic_auth = handle_basic_auth(auth=basic_auth, server=options["server"])

        if oauth.get("oauth_dance") is True:
            oauth = oauth_dance(
                options["server"],
                oauth["consumer_key"],
                oauth["key_cert"],
                oauth["print_tokens"],
                options["verify"],
            )
        elif not all(
            (
                oauth.get("access_token"),
                oauth.get("access_token_secret"),
                oauth.get("consumer_key"),
                oauth.get("key_cert"),
            )
        ):
            oauth = None

        use_kerberos = kerberos_auth.get("use_kerberos", False)
        del kerberos_auth["use_kerberos"]

        jira = JIRA(
            options=options,
            basic_auth=basic_auth,
            kerberos=use_kerberos,
            kerberos_options=kerberos_auth,
            oauth=oauth,
        )

        import IPython

        # The top-level `frontend` package has been deprecated since IPython 1.0.
        if IPython.version_info[0] >= 1:
            from IPython.terminal.embed import InteractiveShellEmbed
        else:
            from IPython.frontend.terminal.embed import InteractiveShellEmbed

        ip_shell = InteractiveShellEmbed(
            banner1="<Jira Shell " + __version__ + " (" + jira.server_url + ")>"
        )
        ip_shell("*** Jira shell active; client is in 'jira'. Press Ctrl-D to exit.")
    except Exception as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    status = main()
    sys.exit(status)
