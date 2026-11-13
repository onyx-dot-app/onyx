"""Run local Craft processes against a shared remote cluster from a profile file.

The profile holds every cluster fact (context, account, region, namespaces).
This public repository ships no cluster names or account IDs.
"""

import ast
import base64
import contextlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, cast

from runtime import Cluster

TARGET = "craft-dev"
PROFILE_ENV = "CRAFT_DEV_PROFILE"
CONTEXT_ENV = "CRAFT_DEV_CONTEXT"
DEFAULT_API_PORT = 8080
DEFAULT_FRONTEND_URL = "http://localhost:3000"
# Deployed settings that a local process against a shared cluster must not use.
LOCAL_OVERRIDES = {"SENTRY_DSN": "", "PYTHONUNBUFFERED": "1"}
AGENT_PROBE = """import json, sys
from onyx.microvm.agent_client import MtlsHostAgentClientFactory
info = MtlsHostAgentClientFactory().client(sys.argv[1]).node_info()
print(json.dumps({"agent": info.agent_version, "vms": info.vm_count, "templates": len(info.templates)}))
"""


@dataclass(frozen=True)
class RemoteProfile:
    name: str
    context: str
    allowed_contexts: tuple[str, ...]
    namespace: str
    sandbox_namespace: str
    agent_namespace: str
    agent_selector: str
    agent_port: int
    aws_region: str
    eks_cluster: str
    kubeconfig: Path | None = None
    server: str | None = None
    aws_profile: str | None = None
    aws_account_id: str | None = None
    user_email: str | None = None
    telepresence_min_version: tuple[int, ...] = (2, 27, 4)
    local_env: dict[str, str] = field(default_factory=dict)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Profile key {key!r} must be a mapping")
    return value


def _text(
    section: dict[str, Any], key: str, where: str, default: str | None = None
) -> str:
    value = section.get(key, default)
    if not isinstance(value, str) or not value or value.startswith("<"):
        raise ValueError(f"Profile key {where}.{key} must be a non-placeholder string")
    return value


def _optional_text(section: dict[str, Any], key: str, where: str) -> str | None:
    if section.get(key) is None:
        return None
    return _text(section, key, where)


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        raise ValueError(f"Not a version: {text!r}")
    return tuple(int(part) for part in match.groups())


def parse_profile(data: object) -> RemoteProfile:
    """Validate a profile mapping; reject placeholders and unknown contexts."""
    if not isinstance(data, dict):
        raise ValueError("Profile must be a YAML mapping")
    data = cast(dict[str, Any], data)
    kube = _section(data, "kube")
    aws = _section(data, "aws")
    namespaces = _section(data, "namespaces")
    agent = _section(data, "agent")
    telepresence = _section(data, "telepresence")
    user = _section(data, "user")
    context = _text(kube, "context", "kube")
    allowed = kube.get("allowed_contexts", [context])
    if not isinstance(allowed, list) or not all(
        isinstance(c, str) and c for c in allowed
    ):
        raise ValueError("Profile key kube.allowed_contexts must be a list of strings")
    if context not in allowed:
        raise ValueError("Profile kube.context must be in kube.allowed_contexts")
    kubeconfig = _optional_text(kube, "kubeconfig", "kube")
    local_env = data.get("local_env", {})
    if not isinstance(local_env, dict) or not all(
        isinstance(k, str) and isinstance(v, str | int | bool)
        for k, v in local_env.items()
    ):
        raise ValueError("Profile key local_env must map names to scalar values")
    port = agent.get("port", 7443)
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("Profile key agent.port must be a TCP port")
    account = aws.get("account_id")
    return RemoteProfile(
        name=_text(data, "name", "profile", TARGET),
        context=context,
        allowed_contexts=tuple(allowed),
        kubeconfig=Path(kubeconfig).expanduser() if kubeconfig else None,
        server=_optional_text(kube, "server", "kube"),
        namespace=_text(namespaces, "app", "namespaces", "onyx"),
        sandbox_namespace=_text(namespaces, "sandbox", "namespaces", "onyx-sandboxes"),
        agent_namespace=_text(namespaces, "agent", "namespaces"),
        agent_selector=_text(
            agent,
            "selector",
            "agent",
            "app.kubernetes.io/component=craft-fc-host-agent",
        ),
        agent_port=port,
        aws_region=_text(aws, "region", "aws"),
        eks_cluster=_text(aws, "eks_cluster", "aws"),
        aws_profile=_optional_text(aws, "profile", "aws"),
        aws_account_id=None if account is None else str(account),
        user_email=_optional_text(user, "email", "user"),
        telepresence_min_version=parse_version(
            str(telepresence.get("min_version", "2.27.4"))
        ),
        local_env={
            str(k): str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in local_env.items()
        },
    )


def default_profile_path(root: Path) -> Path:
    """Find onyx-internal next to the main checkout, also from a worktree."""
    base = root
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        base = Path(common).parent
    except (OSError, subprocess.SubprocessError):
        pass
    return base.parent / "onyx-internal/dev/craft-dev.yaml"


def load_profile(root: Path, path: Path | None = None) -> RemoteProfile:
    import yaml

    if path is None and os.environ.get(PROFILE_ENV):
        path = Path(os.environ[PROFILE_ENV])
    path = (path or default_profile_path(root)).expanduser()
    if not path.is_file():
        raise ValueError(
            f"No {TARGET} profile at {path}; set {PROFILE_ENV} or pass --profile"
        )
    return parse_profile(yaml.safe_load(path.read_text()))


def select_context(profile: RemoteProfile, requested: str | None) -> str:
    """Use the profile context; accept another only when the profile lists it."""
    if not requested:
        return profile.context
    if requested not in profile.allowed_contexts:
        raise ValueError(
            f"Context {requested!r} is not in the {profile.name} profile; refusing to use it"
        )
    return requested


@dataclass(frozen=True)
class RemoteCluster(Cluster):
    kube_context: str = ""
    kubeconfig: Path | None = None
    server: str | None = None
    env_file_name: ClassVar[str] = f".vscode/.env.{TARGET}"

    @classmethod
    def from_profile(
        cls, root: Path, profile: RemoteProfile, context: str | None = None
    ) -> "RemoteCluster":
        return cls(
            root,
            profile.name,
            profile.namespace,
            profile.sandbox_namespace,
            kube_context=select_context(profile, context),
            kubeconfig=profile.kubeconfig,
            server=profile.server,
        )

    @property
    def context(self) -> str:
        return self.kube_context

    @property
    def kubectl(self) -> tuple[str, ...]:
        kubeconfig = ("--kubeconfig", str(self.kubeconfig)) if self.kubeconfig else ()
        return ("kubectl", *kubeconfig, "--context", self.kube_context)

    def pinned_environment(self, settings: dict[str, str]) -> dict[str, str]:
        """Keep the deployed sandbox backend; only the context is local."""
        pins = {"K8S_CONTEXT": self.kube_context}
        if self.kubeconfig:
            pins["KUBECONFIG"] = str(self.kubeconfig)
        for key in ("SANDBOX_BACKEND", "SANDBOX_NAMESPACE", "SANDBOX_RUNTIME"):
            if settings.get(key):
                pins[key] = settings[key]
        pins.setdefault("SANDBOX_NAMESPACE", self.sandbox_namespace)
        return pins

    def verify_server(self) -> None:
        """Refuse a context whose API server differs from the profile."""
        if not self.server:
            return
        actual = self.command(
            *self.kubectl,
            "config",
            "view",
            "--minify",
            "-o",
            "jsonpath={.clusters[0].cluster.server}",
        )
        if actual.rstrip("/") != self.server.rstrip("/"):
            raise ValueError(
                f"Context {self.kube_context!r} points at another API server; refusing to use it"
            )

    def local_environment(
        self,
        env_file: Path | None = None,
        *,
        profile_env: dict[str, str] | None = None,
        frontend_url: str = DEFAULT_FRONTEND_URL,
        settings: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Deployed env, then profile and local-only overrides, then the personal file."""
        deployed = self.deployment_env() if settings is None else settings
        merged = {
            **deployed,
            **(profile_env or {}),
            **LOCAL_OVERRIDES,
            "WEB_DOMAIN": frontend_url.rstrip("/"),
        }
        return self.environment(env_file, settings=merged)


@dataclass(frozen=True)
class SecretMount:
    volume: str
    secret: str
    mount_path: str
    sub_path: str | None
    items: tuple[tuple[str, str], ...]
    optional: bool


def container_spec(workload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pod = workload["spec"]["template"]["spec"]
    container = next((c for c in pod["containers"] if c["name"] == "api-server"), None)
    if container is None:
        raise ValueError("API deployment has no api-server container")
    return pod, container


def secret_mounts(workload: dict[str, Any]) -> tuple[list[SecretMount], list[str]]:
    """Return the api-server Secret mounts and the paths of its other mounts."""
    pod, container = container_spec(workload)
    volumes = {v["name"]: v for v in pod.get("volumes", [])}
    mounts: list[SecretMount] = []
    other: list[str] = []
    for mount in container.get("volumeMounts", []):
        secret = volumes.get(mount["name"], {}).get("secret")
        if secret is None:
            other.append(mount["mountPath"])
            continue
        mounts.append(
            SecretMount(
                volume=mount["name"],
                secret=secret["secretName"],
                mount_path=mount["mountPath"].rstrip("/"),
                sub_path=mount.get("subPath") or None,
                items=tuple((i["key"], i["path"]) for i in secret.get("items", [])),
                optional=bool(secret.get("optional", False)),
            )
        )
    return mounts, other


def mounted_files(mount: SecretMount, data: dict[str, bytes]) -> dict[str, bytes]:
    """Map the files a Secret volume shows in the pod to their contents."""
    if mount.items:
        files = {path: data[key] for key, path in mount.items if key in data}
    else:
        files = dict(data)
    for path in files:
        parts = PurePosixPath(path).parts
        if PurePosixPath(path).is_absolute() or ".." in parts or not parts:
            raise ValueError(f"Unsafe file path in Secret {mount.secret!r}")
    return files


def rewrite_paths(env: dict[str, str], mount: SecretMount, target: Path) -> list[str]:
    """Point env values at local copies of mounted Secret files."""
    changed: list[str] = []
    for key, value in env.items():
        if mount.sub_path is not None:
            if value == mount.mount_path:
                env[key] = str(target / mount.sub_path)
                changed.append(key)
        elif value == mount.mount_path or value.startswith(mount.mount_path + "/"):
            env[key] = str(target / value[len(mount.mount_path) :].lstrip("/"))
            changed.append(key)
    return changed


def pod_paths(env: dict[str, str], paths: list[str]) -> list[str]:
    """Names of env values that still point into a pod-only mount."""
    roots = [p.rstrip("/") for p in paths if p.rstrip("/")]
    return sorted(
        key
        for key, value in env.items()
        if any(value == r or value.startswith(r + "/") for r in roots)
    )


@contextlib.contextmanager
def secret_files(
    cluster: Cluster, env: dict[str, str], workload: dict[str, Any] | None = None
) -> Iterator[dict[str, str]]:
    """Copy mounted Secret files to a private temp dir that is removed on exit."""
    mounts, other = secret_mounts(workload or cluster.api_workload())
    result = dict(env)
    tmp = Path(tempfile.mkdtemp(prefix="craft-dev-"))
    os.chmod(tmp, 0o700)
    try:
        for index, mount in enumerate(mounts):
            raw = cluster.kube(
                "get", "secret", mount.secret, "--ignore-not-found", "-o", "json"
            )
            if not raw:
                if mount.optional:
                    continue
                raise ValueError(f"Missing secret {mount.secret!r}")
            data = {
                k: base64.b64decode(v, validate=True)
                for k, v in json.loads(raw).get("data", {}).items()
            }
            target = tmp / f"{index}-{mount.volume}"
            target.mkdir(mode=0o700)
            for path, content in mounted_files(mount, data).items():
                file = target / path
                file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                file.write_bytes(content)
                os.chmod(file, 0o600)
            changed = rewrite_paths(result, mount, target)
            print(
                f"Secret volume {mount.volume}: local files for {', '.join(changed) or 'no env values'}",
                file=sys.stderr,
                flush=True,
            )
        if stale := pod_paths(result, other):
            print(
                f"warning: these values point into pod-only mounts: {', '.join(stale)}",
                file=sys.stderr,
                flush=True,
            )
        yield result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def migration_ids(source: str) -> tuple[str, set[str]] | None:
    """Read a migration's revision and parents without importing it."""
    values: dict[str, object] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
            values[target.id] = ast.literal_eval(value)
    revision, parents = values.get("revision"), values.get("down_revision")
    if not isinstance(revision, str):
        return None
    if isinstance(parents, str):
        return revision, {parents}
    if isinstance(parents, tuple | list):
        return revision, {str(parent) for parent in parents}
    return revision, set()


def local_revisions(root: Path) -> tuple[set[str], set[str]]:
    """Return the checkout's Alembic heads and every revision it knows."""
    graph: dict[str, set[str]] = {}
    for path in sorted((root / "backend/alembic/versions").glob("*.py")):
        if ids := migration_ids(path.read_text()):
            graph[ids[0]] = ids[1]
    parents = set().union(*graph.values()) if graph else set()
    return set(graph) - parents, set(graph)


def db_revisions(env: dict[str, str]) -> set[str]:
    """Read the shared database's Alembic version in a read-only session."""
    import psycopg2

    if env.get("USE_IAM_AUTH", "").lower() == "true":
        raise ValueError("USE_IAM_AUTH is not supported by the head check")
    connection = psycopg2.connect(
        host=env.get("POSTGRES_HOST", "localhost"),
        port=int(env.get("POSTGRES_PORT") or 5432),
        user=env.get("POSTGRES_USER") or "postgres",
        password=env.get("POSTGRES_PASSWORD") or "",
        dbname=env.get("POSTGRES_DB") or "postgres",
        sslmode=env.get("POSTGRES_SSLMODE") or "prefer",
        sslrootcert=env.get("POSTGRES_SSLROOTCERT") or None,
        connect_timeout=10,
    )
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("select version_num from alembic_version")
            return {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()


def check_heads(local_heads: set[str], known: set[str], db: set[str]) -> None:
    """Refuse a checkout whose migrations differ from the shared database."""
    if db == local_heads:
        return
    if not db:
        raise ValueError("The shared database has no Alembic version; refusing to run")
    if db - known:
        raise ValueError(
            f"The shared database is at {', '.join(sorted(db))}, which this checkout does not have. "
            "Rebase on origin/main, or check out the deployed commit."
        )
    raise ValueError(
        f"This checkout has migrations the shared database has not run "
        f"(database {', '.join(sorted(db))}, checkout {', '.join(sorted(local_heads))}). "
        "The launcher never migrates a shared database. Redeploy the cluster with these "
        "migrations, or run a commit whose head matches the database."
    )


def require_heads_match(root: Path, env: dict[str, str]) -> None:
    heads, known = local_revisions(root)
    check_heads(heads, known, db_revisions(env))


def connect_hint(cluster: RemoteCluster) -> str:
    kubeconfig = f" --kubeconfig {cluster.kubeconfig}" if cluster.kubeconfig else ""
    return (
        f"run in a real terminal (it asks for sudo): telepresence connect{kubeconfig} "
        f"--context {cluster.kube_context} -n {cluster.namespace}"
    )


RECONNECT_HINT = "if connect hangs or the root daemon stops: telepresence quit -s, then connect again"


def telepresence_problem(
    status: dict[str, Any], context: str, namespace: str, server: str | None
) -> str | None:
    """Describe why the Telepresence connection does not fit the profile."""
    user = status.get("user_daemon", {})
    if user.get("status") != "Connected":
        return "Telepresence is not connected"
    if not status.get("root_daemon", {}).get("running", False):
        return "the Telepresence root daemon is not running"
    if user.get("kubernetes_context") != context:
        return "Telepresence is connected to another context"
    if server and user.get("kubernetes_server", "").rstrip("/") != server.rstrip("/"):
        return "Telepresence is connected to another API server"
    if user.get("namespace") != namespace:
        return f"Telepresence is connected to namespace {user.get('namespace')!r}, not {namespace!r}"
    return None


def telepresence_status(cluster: Cluster) -> dict[str, Any]:
    return json.loads(cluster.command("telepresence", "status", "--output", "json"))


def require_telepresence(cluster: RemoteCluster) -> None:
    problem = telepresence_problem(
        telepresence_status(cluster),
        cluster.kube_context,
        cluster.namespace,
        cluster.server,
    )
    if problem:
        raise ValueError(f"{problem}; {connect_hint(cluster)}")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(requested: int | None, free: Callable[[int], bool] = port_free) -> int:
    """Use the requested port, else 8080 when free, else any free port."""
    if requested is not None:
        return requested
    if free(DEFAULT_API_PORT):
        return DEFAULT_API_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def egress_allowed(ip: str, cidrs: list[str]) -> bool:
    address = ipaddress.ip_address(ip)
    return any(address in ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)


def has_global_ipv6() -> bool:
    """True when the OS would send IPv6 traffic to the internet (no packet sent)."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.connect(("2001:4860:4860::8888", 53))
            return ipaddress.ip_address(sock.getsockname()[0]).is_global
    except OSError:
        return False


def ipv4_egress(timeout: float = 10) -> str:
    with urllib.request.urlopen(  # noqa: S310 - fixed HTTPS URL
        "https://checkip.amazonaws.com", timeout=timeout
    ) as response:
        return str(ipaddress.IPv4Address(response.read().decode().strip()))


class Report:
    """Print PASS/WARN/FAIL lines; every FAIL gets one fix line."""

    def __init__(self) -> None:
        self.failures = 0

    def __call__(self, ok: bool | None, message: str, fix: str = "") -> bool:
        level = "PASS" if ok else ("WARN" if ok is None else "FAIL")
        self.failures += level == "FAIL"
        print(f"{level}: {message}", flush=True)
        if fix and level != "PASS":
            print(f"  fix: {fix}", flush=True)
        return bool(ok)


def probe(
    cwd: Path, *command: str, timeout: float = 20, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run a diagnostic command; never print its output."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def finish(report: Report) -> int:
    print(
        f"Doctor finished: {report.failures} failed check(s). No resources changed.",
        flush=True,
    )
    return int(report.failures > 0)


def aws_checks(root: Path, profile: RemoteProfile, report: Report) -> None:
    """SSO session, account, and IPv4 egress against the EKS endpoint allowlist."""
    aws_args = ("--profile", profile.aws_profile) if profile.aws_profile else ()
    login = "aws sso login" + (
        f" --profile {profile.aws_profile}" if profile.aws_profile else ""
    )
    result = probe(
        root, "aws", "sts", "get-caller-identity", "--output", "json", *aws_args
    )
    identity = json.loads(result.stdout) if result and result.returncode == 0 else None
    report(identity is not None, "AWS SSO session", login)
    if identity is not None and profile.aws_account_id:
        report(
            identity.get("Account") == profile.aws_account_id,
            "AWS account matches the profile",
            f"{login} with the account in the profile",
        )
    try:
        ip: str | None = ipv4_egress()
    except (OSError, ValueError):
        ip = None
    report(
        ip is not None,
        f"IPv4 egress: {ip or 'unknown'}",
        "check the network connection",
    )
    if identity is not None and ip is not None:
        result = probe(
            root,
            "aws",
            "eks",
            "describe-cluster",
            "--name",
            profile.eks_cluster,
            "--region",
            profile.aws_region,
            *aws_args,
            "--query",
            "cluster.resourcesVpcConfig.publicAccessCidrs",
            "--output",
            "json",
        )
        cidrs = json.loads(result.stdout) if result and result.returncode == 0 else None
        if cidrs is None:
            report(
                False,
                "Read the EKS endpoint allowlist",
                "check the SSO role in the profile",
            )
        else:
            report(
                egress_allowed(ip, cidrs),
                "IPv4 egress is in the EKS endpoint allowlist",
                "connect the VPN",
            )
    if has_global_ipv6():
        report(
            None,
            "IPv6 egress is on; it can bypass the VPN and time out kubectl",
            "networksetup -setv6off Wi-Fi (undo: networksetup -setv6automatic Wi-Fi)",
        )


def kube_checks(
    root: Path, profile: RemoteProfile, cluster: RemoteCluster, report: Report
) -> bool:
    """Context pin and read access to the namespaces the launcher uses."""
    update = (
        f"aws eks update-kubeconfig --name {profile.eks_cluster} --region {profile.aws_region}"
        f" --alias {cluster.kube_context}"
        + (f" --kubeconfig {profile.kubeconfig}" if profile.kubeconfig else "")
        + (f" --profile {profile.aws_profile}" if profile.aws_profile else "")
    )
    try:
        cluster.verify_server()
        pinned = True
    except (ValueError, subprocess.SubprocessError, OSError):
        pinned = False
    if not report(
        pinned, f"Kube context {cluster.kube_context} matches the profile", update
    ):
        return False
    access = True
    for verb, resource, namespace in (
        ("get", "deployments", profile.namespace),
        ("get", "secrets", profile.namespace),
        ("list", "pods", profile.agent_namespace),
    ):
        result = probe(
            root,
            *cluster.kubectl,
            "--request-timeout=10s",
            "auth",
            "can-i",
            verb,
            resource,
            "-n",
            namespace,
        )
        access &= report(
            result is not None and result.stdout.strip() == "yes",
            f"Kube access: {verb} {resource} in {namespace}",
            "connect the VPN, then check your SSO role" if result is None else update,
        )
    return access


def telepresence_checks(
    root: Path, profile: RemoteProfile, cluster: RemoteCluster, report: Report
) -> bool:
    """Client version, connection to the profile context, and manager version."""
    if not shutil.which("telepresence"):
        return False
    result = probe(root, "telepresence", "version")
    try:
        version: tuple[int, ...] | None = parse_version(result.stdout if result else "")
    except ValueError:
        version = None
    minimum = ".".join(map(str, profile.telepresence_min_version))
    report(
        version is not None and version >= profile.telepresence_min_version,
        f"Telepresence client {'.'.join(map(str, version)) if version else 'unknown'}"
        f" (needs {minimum} or later)",
        "brew upgrade telepresenceio/telepresence/telepresence-oss",
    )
    result = probe(root, "telepresence", "status", "--output", "json")
    try:
        status = json.loads(result.stdout) if result and result.returncode == 0 else {}
    except json.JSONDecodeError:
        status = {}
    problem = telepresence_problem(
        status, cluster.kube_context, cluster.namespace, cluster.server
    )
    connected = report(
        problem is None,
        f"Telepresence: {problem or 'connected'}",
        connect_hint(cluster) + "; " + RECONNECT_HINT,
    )
    manager = status.get("traffic_manager", {}).get("version", "")
    if connected and version is not None and manager:
        report(
            parse_version(manager)[:2] == version[:2] or None,
            f"Traffic manager {manager}",
            "install the client version that matches the traffic manager",
        )
    return connected


def agent_and_head_checks(
    root: Path,
    profile: RemoteProfile,
    cluster: RemoteCluster,
    env: dict[str, str],
    report: Report,
) -> None:
    """NodeInfo over mTLS to each host agent, then the Alembic head match."""
    pods = json.loads(
        cluster.kube(
            "get",
            "pods",
            "-l",
            profile.agent_selector,
            "-o",
            "json",
            namespace=profile.agent_namespace,
        )
    )["items"]
    ips = [p["status"]["podIP"] for p in pods if p.get("status", {}).get("podIP")]
    if not ips:
        report(
            False,
            "Host agent pods",
            f"check the agent DaemonSet in {profile.agent_namespace}",
        )
    child = {**env, "PYTHONPATH": str(root / "backend")}
    for ip in ips:
        result = probe(
            root / "backend",
            str(root / ".venv/bin/python"),
            "-c",
            AGENT_PROBE,
            f"{ip}:{profile.agent_port}",
            timeout=60,
            env=child,
        )
        info = json.loads(result.stdout) if result and result.returncode == 0 else None
        report(
            info is not None,
            f"Host agent {ip}: "
            + (
                f"NodeInfo over mTLS, agent {info['agent']}, {info['vms']} VMs"
                if info
                else "NodeInfo failed"
            ),
            f"check the NetworkPolicy that lets Telepresence reach port {profile.agent_port}; "
            + RECONNECT_HINT,
        )
    try:
        require_heads_match(root, env)
        report(True, "Checkout Alembic head matches the shared database")
    except Exception as exc:  # noqa: BLE001 - report any database failure as one line
        report(
            False,
            f"Alembic head check: {exc}",
            "match the checkout to the deployed migrations",
        )


def doctor(root: Path, profile_path: Path | None, context: str | None) -> int:
    """Check remote-cluster prerequisites without changing anything."""
    report = Report()
    try:
        profile = load_profile(root, profile_path)
        cluster = RemoteCluster.from_profile(root, profile, context)
    except (ValueError, OSError) as exc:
        report(
            False,
            f"{TARGET} profile: {exc}",
            f"set {PROFILE_ENV} to the profile file from onyx-internal",
        )
        return finish(report)
    report(True, f"{TARGET} profile: context {cluster.kube_context}")
    tools = {name: shutil.which(name) for name in ("aws", "kubectl", "telepresence")}
    for name, path in tools.items():
        report(bool(path), f"{name}: {path or 'missing from PATH'}", f"install {name}")
    if not tools["aws"] or not tools["kubectl"]:
        return finish(report)
    aws_checks(root, profile, report)
    if not kube_checks(root, profile, cluster, report):
        return finish(report)
    connected = telepresence_checks(root, profile, cluster, report)
    try:
        workload = cluster.api_workload()
        env = cluster.local_environment(profile_env=profile.local_env)
    except (ValueError, OSError, subprocess.SubprocessError):
        report(
            False,
            "Deployed api settings do not resolve",
            "check the api Deployment and its Secrets in the profile namespace",
        )
        return finish(report)
    report(True, f"Deployed api settings resolve ({len(env)} values)")
    if not connected:
        report(
            None, "Skipped the agent and database checks; connect Telepresence first"
        )
        return finish(report)
    with secret_files(cluster, env, workload) as resolved:
        agent_and_head_checks(root, profile, cluster, resolved, report)
    return finish(report)
