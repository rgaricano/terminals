"""Kubernetes backend — provisions Open Terminal as Pods via the K8s API."""

import logging
import re
import secrets
from typing import Optional

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiClient

from terminals.backends.base import Backend
from terminals.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DNS_SAFE = re.compile(r"[^a-z0-9-]")


def _sanitize_name(user_id: str) -> str:
    """Convert a user ID to a DNS-safe K8s resource name."""
    name = _DNS_SAFE.sub("-", user_id.lower()).strip("-")[:53]
    return f"terminal-{name}"


def _parse_labels() -> dict[str, str]:
    """Parse ``TERMINALS_KUBERNETES_LABELS`` into a dict."""
    labels: dict[str, str] = {}
    if not settings.kubernetes_labels:
        return labels
    for pair in settings.kubernetes_labels.split(","):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip()
    return labels


def _base_labels(user_id: str) -> dict[str, str]:
    """Standard labels applied to every resource we create."""
    labels = {
        "app.kubernetes.io/managed-by": "terminals",
        "app.kubernetes.io/part-of": "open-terminal",
        "openwebui.com/user-id": user_id,
    }
    labels.update(_parse_labels())
    return labels


class KubernetesBackend(Backend):
    """Manage terminal instances as Kubernetes Pods + Services."""

    def __init__(self) -> None:
        super().__init__()
        self._api_client: Optional[ApiClient] = None

    async def _ensure_client(self) -> ApiClient:
        if self._api_client is None:
            if settings.kubernetes_kubeconfig:
                await config.load_kube_config(
                    config_file=settings.kubernetes_kubeconfig
                )
            else:
                config.load_incluster_config()
            self._api_client = ApiClient()
        return self._api_client

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def provision(
        self,
        user_id: str,
        policy_id: str = "default",
        spec: dict | None = None,
    ) -> dict:
        api_client = await self._ensure_client()
        core = client.CoreV1Api(api_client)
        s = spec or {}

        api_key = secrets.token_urlsafe(24)
        base_name = _sanitize_name(user_id)
        policy_slug = _DNS_SAFE.sub("-", policy_id.lower()).strip("-")[:20]
        name = f"{base_name}-{policy_slug}" if policy_id != "default" else base_name
        ns = settings.kubernetes_namespace
        labels = _base_labels(user_id)
        labels["openwebui.com/policy"] = policy_slug

        image = s.get("image", settings.kubernetes_image)
        storage_mode = s.get("storage_mode", settings.kubernetes_storage_mode)
        storage_size = s.get("storage", settings.kubernetes_storage_size)

        # ---- Env vars ----------------------------------------------------
        env_vars = [
            client.V1EnvVar(name="OPEN_TERMINAL_API_KEY", value=api_key),
        ]
        policy_env = s.get("env", {})
        for k, v in policy_env.items():
            env_vars.append(client.V1EnvVar(name=k, value=str(v)))

        # Egress filtering is handled inside the container (dnsmasq + ipset +
        # iptables + capsh) triggered by OPEN_TERMINAL_ALLOWED_DOMAINS env var.
        has_egress_policy = "OPEN_TERMINAL_ALLOWED_DOMAINS" in policy_env

        # ---- Resource requirements ---------------------------------------
        resource_reqs = None
        limits = {}
        if s.get("cpu_limit"):
            limits["cpu"] = s["cpu_limit"]
        if s.get("memory_limit"):
            limits["memory"] = s["memory_limit"]
        if limits:
            resource_reqs = client.V1ResourceRequirements(limits=limits)

        # ---- Storage (3 modes) -------------------------------------------
        volumes = []
        volume_mounts = []
        affinity = None
        shared_pvc_name = f"terminals-shared-{ns}"

        if storage_size:
            if storage_mode == "per-user":
                # Each user gets their own PVC
                pvc = client.V1PersistentVolumeClaim(
                    metadata=client.V1ObjectMeta(name=name, namespace=ns, labels=labels),
                    spec=client.V1PersistentVolumeClaimSpec(
                        access_modes=["ReadWriteOnce"],
                        resources=client.V1VolumeResourceRequirements(
                            requests={"storage": storage_size},
                        ),
                        **(
                            {"storage_class_name": settings.kubernetes_storage_class}
                            if settings.kubernetes_storage_class
                            else {}
                        ),
                    ),
                )
                try:
                    await core.create_namespaced_persistent_volume_claim(ns, pvc)
                    log.info("Created PVC %s in %s", name, ns)
                except client.exceptions.ApiException as exc:
                    if exc.status != 409:
                        raise
                volumes.append(
                    client.V1Volume(
                        name="home",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=name,
                        ),
                    )
                )
                volume_mounts.append(
                    client.V1VolumeMount(name="home", mount_path="/home/user"),
                )

            elif storage_mode == "shared":
                # Single RWX PVC shared across all users, subPath per user
                await self._ensure_shared_pvc(core, ns, shared_pvc_name, storage_size, "ReadWriteMany")
                volumes.append(
                    client.V1Volume(
                        name="home",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=shared_pvc_name,
                        ),
                    )
                )
                volume_mounts.append(
                    client.V1VolumeMount(
                        name="home",
                        mount_path="/home/user",
                        sub_path=user_id,
                    ),
                )

            elif storage_mode == "shared-rwo":
                # Single RWO PVC, all pods on same node via affinity
                await self._ensure_shared_pvc(core, ns, shared_pvc_name, storage_size, "ReadWriteOnce")
                volumes.append(
                    client.V1Volume(
                        name="home",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=shared_pvc_name,
                        ),
                    )
                )
                volume_mounts.append(
                    client.V1VolumeMount(
                        name="home",
                        mount_path="/home/user",
                        sub_path=user_id,
                    ),
                )
                # Pin all terminal pods to the same node as the PVC
                affinity = client.V1Affinity(
                    pod_affinity=client.V1PodAffinity(
                        required_during_scheduling_ignored_during_execution=[
                            client.V1PodAffinityTerm(
                                label_selector=client.V1LabelSelector(
                                    match_labels={
                                        "app.kubernetes.io/managed-by": "terminals",
                                    }
                                ),
                                topology_key="kubernetes.io/hostname",
                            )
                        ]
                    )
                )

        # ---- Pod ---------------------------------------------------------
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(name=name, namespace=ns, labels=labels),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="open-terminal",
                        image=image,
                        ports=[client.V1ContainerPort(container_port=8000)],
                        env=env_vars,
                        volume_mounts=volume_mounts or None,
                        resources=resource_reqs,
                        security_context=client.V1SecurityContext(
                            capabilities=client.V1Capabilities(
                                add=["NET_ADMIN"],
                            ),
                        ) if has_egress_policy else None,
                        readiness_probe=client.V1Probe(
                            http_get=client.V1HTTPGetAction(
                                path="/health", port=8000
                            ),
                            initial_delay_seconds=3,
                            period_seconds=5,
                        ),
                    )
                ],
                volumes=volumes or None,
                affinity=affinity,
                restart_policy="Always",
            ),
        )

        try:
            created = await core.create_namespaced_pod(ns, pod)
            log.info("Created Pod %s in %s (policy=%s, storage=%s)", name, ns, policy_id, storage_mode)
        except client.exceptions.ApiException as exc:
            if exc.status == 409:
                log.info("Pod %s already exists, replacing", name)
                await core.delete_namespaced_pod(name, ns)
                created = await core.create_namespaced_pod(ns, pod)
            else:
                raise

        instance_id = created.metadata.uid

        # ---- Service -----------------------------------------------------
        svc = client.V1Service(
            metadata=client.V1ObjectMeta(name=name, namespace=ns, labels=labels),
            spec=client.V1ServiceSpec(
                type=settings.kubernetes_service_type,
                selector={
                    "openwebui.com/user-id": user_id,
                    "openwebui.com/policy": policy_slug,
                },
                ports=[
                    client.V1ServicePort(port=8000, target_port=8000),
                ],
            ),
        )
        try:
            await core.create_namespaced_service(ns, svc)
            log.info("Created Service %s in %s", name, ns)
        except client.exceptions.ApiException as exc:
            if exc.status != 409:
                raise

        host = f"{name}.{ns}.svc.cluster.local"

        # Wait for the pod to be ready before returning.
        await self._wait_until_pod_ready(core, name, ns, timeout=60)

        return {
            "instance_id": instance_id,
            "instance_name": name,
            "api_key": api_key,
            "host": host,
            "port": 8000,
        }

    async def _wait_until_pod_ready(
        self,
        core: client.CoreV1Api,
        name: str,
        ns: str,
        timeout: int = 60,
    ) -> None:
        """Poll until the pod's readiness probe passes."""
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                pod = await core.read_namespaced_pod(name, ns)
                conditions = pod.status.conditions or []
                for c in conditions:
                    if c.type == "Ready" and c.status == "True":
                        log.info("Pod %s is ready", name)
                        return
            except client.exceptions.ApiException:
                pass
            await asyncio.sleep(1)
        log.warning("Pod %s did not become ready within %ds", name, timeout)

    async def start(self, instance_id: str) -> bool:
        current = await self.status(instance_id)
        if current == "running":
            return True
        # Pods can't be restarted — caller should re-provision.
        return False

    async def teardown(self, instance_id: str) -> None:
        api_client = await self._ensure_client()
        core = client.CoreV1Api(api_client)
        ns = settings.kubernetes_namespace

        # Find the pod by UID to get the name.
        name = await self._name_from_uid(instance_id)
        if name is None:
            log.warning("No pod found for UID %s", instance_id)
            return

        # Delete Pod.
        try:
            await core.delete_namespaced_pod(name, ns)
            log.info("Deleted Pod %s", name)
        except client.exceptions.ApiException:
            log.warning("Could not delete Pod %s (may already be gone)", name)

        # Delete Service.
        try:
            await core.delete_namespaced_service(name, ns)
            log.info("Deleted Service %s", name)
        except client.exceptions.ApiException:
            log.warning("Could not delete Service %s", name)

        # Note: PVC is intentionally kept for data persistence.

    async def status(self, instance_id: str) -> str:
        api_client = await self._ensure_client()
        core = client.CoreV1Api(api_client)
        ns = settings.kubernetes_namespace

        name = await self._name_from_uid(instance_id)
        if name is None:
            return "missing"

        try:
            pod = await core.read_namespaced_pod(name, ns)
            phase = pod.status.phase  # Pending, Running, Succeeded, Failed, Unknown
            if phase == "Running":
                return "running"
            if phase in ("Pending",):
                return "running"  # still starting up
            return "stopped"
        except client.exceptions.ApiException:
            return "missing"

    async def close(self) -> None:
        if self._api_client is not None:
            await self._api_client.close()
            self._api_client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _name_from_uid(self, uid: str) -> Optional[str]:
        """Look up a Pod name by its UID."""
        api_client = await self._ensure_client()
        core = client.CoreV1Api(api_client)
        ns = settings.kubernetes_namespace

        try:
            pods = await core.list_namespaced_pod(
                ns, label_selector="app.kubernetes.io/managed-by=terminals"
            )
            for pod in pods.items:
                if pod.metadata.uid == uid:
                    return pod.metadata.name
        except client.exceptions.ApiException:
            pass
        return None

    async def _ensure_shared_pvc(
        self,
        core: client.CoreV1Api,
        ns: str,
        name: str,
        size: str,
        access_mode: str,
    ) -> None:
        """Create the shared PVC if it doesn't already exist."""
        pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=ns,
                labels={
                    "app.kubernetes.io/managed-by": "terminals",
                    "app.kubernetes.io/part-of": "open-terminal",
                },
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=[access_mode],
                resources=client.V1VolumeResourceRequirements(
                    requests={"storage": size},
                ),
                **(
                    {"storage_class_name": settings.kubernetes_storage_class}
                    if settings.kubernetes_storage_class
                    else {}
                ),
            ),
        )
        try:
            await core.create_namespaced_persistent_volume_claim(ns, pvc)
            log.info("Created shared PVC %s in %s (%s)", name, ns, access_mode)
        except client.exceptions.ApiException as exc:
            if exc.status != 409:
                raise
