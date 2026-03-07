"""Kubernetes Operator backend — manages Terminals via CRDs.

Instead of creating Pods/Services directly, this backend creates and manages
``Terminal`` custom resources.  A separate Kopf-based operator watches these
CRs and reconciles the underlying Pods, Services, and PVCs.
"""

import asyncio
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


class KubernetesOperatorBackend(Backend):
    """Manage terminal instances via Terminal CRDs.

    The backend creates/deletes ``Terminal`` custom resources in the
    configured namespace.  A Kopf operator running in the cluster watches
    these resources and manages the actual Pods, Services, and PVCs.
    """

    def __init__(self) -> None:
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

    @property
    def _group(self) -> str:
        return settings.kubernetes_crd_group

    @property
    def _version(self) -> str:
        return settings.kubernetes_crd_version

    @property
    def _plural(self) -> str:
        return "terminals"

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def provision(self, user_id: str) -> dict:
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)

        api_key = secrets.token_urlsafe(24)
        name = _sanitize_name(user_id)
        ns = settings.kubernetes_namespace

        cr = {
            "apiVersion": f"{self._group}/{self._version}",
            "kind": "Terminal",
            "metadata": {
                "name": name,
                "namespace": ns,
                "labels": {
                    "app.kubernetes.io/managed-by": "terminals",
                    "app.kubernetes.io/part-of": "open-terminal",
                    "openwebui.com/user-id": user_id,
                },
            },
            "spec": {
                "userId": user_id,
                "image": settings.kubernetes_image,
                "apiKey": api_key,
                "storage": {
                    "enabled": bool(settings.kubernetes_storage_size),
                    "size": settings.kubernetes_storage_size,
                    "storageClass": settings.kubernetes_storage_class or None,
                },
            },
        }

        try:
            created = await custom.create_namespaced_custom_object(
                group=self._group,
                version=self._version,
                namespace=ns,
                plural=self._plural,
                body=cr,
            )
            log.info("Created Terminal CR %s in %s", name, ns)
        except client.exceptions.ApiException as exc:
            if exc.status == 409:
                # Already exists — fetch it.
                log.debug("Terminal CR %s already exists", name)
                created = await custom.get_namespaced_custom_object(
                    group=self._group,
                    version=self._version,
                    namespace=ns,
                    plural=self._plural,
                    name=name,
                )
            else:
                raise

        instance_id = created["metadata"]["uid"]

        # Wait for the operator to set status.phase = Running.
        host = await self._wait_for_ready(name, ns, timeout=60)

        return {
            "instance_id": instance_id,
            "instance_name": name,
            "api_key": api_key,
            "host": host,
            "port": 8000,
        }

    async def start(self, instance_id: str) -> bool:
        """Signal the operator to bring the terminal back up.

        The operator watches for ``spec.replicas`` changes and
        creates/deletes the Pod accordingly.
        """
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)
        ns = settings.kubernetes_namespace

        name = await self._name_from_uid(instance_id)
        if name is None:
            return False

        try:
            await custom.patch_namespaced_custom_object(
                group=self._group,
                version=self._version,
                namespace=ns,
                plural=self._plural,
                name=name,
                body={"spec": {"replicas": 1}},
            )
            return True
        except client.exceptions.ApiException:
            return False

    async def teardown(self, instance_id: str) -> None:
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)
        ns = settings.kubernetes_namespace

        name = await self._name_from_uid(instance_id)
        if name is None:
            log.warning("No Terminal CR found for UID %s", instance_id)
            return

        try:
            await custom.delete_namespaced_custom_object(
                group=self._group,
                version=self._version,
                namespace=ns,
                plural=self._plural,
                name=name,
            )
            log.info("Deleted Terminal CR %s", name)
        except client.exceptions.ApiException:
            log.warning(
                "Could not delete Terminal CR %s (may already be gone)", name
            )

    async def status(self, instance_id: str) -> str:
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)
        ns = settings.kubernetes_namespace

        name = await self._name_from_uid(instance_id)
        if name is None:
            return "missing"

        try:
            cr = await custom.get_namespaced_custom_object(
                group=self._group,
                version=self._version,
                namespace=ns,
                plural=self._plural,
                name=name,
            )
            phase = cr.get("status", {}).get("phase", "Unknown")
            if phase == "Running":
                return "running"
            if phase in ("Provisioning", "Pending"):
                return "running"  # still coming up
            if phase == "Stopped":
                return "stopped"
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
        """Look up a Terminal CR name by its UID."""
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)
        ns = settings.kubernetes_namespace

        try:
            result = await custom.list_namespaced_custom_object(
                group=self._group,
                version=self._version,
                namespace=ns,
                plural=self._plural,
                label_selector="app.kubernetes.io/managed-by=terminals",
            )
            for item in result.get("items", []):
                if item["metadata"]["uid"] == uid:
                    return item["metadata"]["name"]
        except client.exceptions.ApiException:
            pass
        return None

    async def _wait_for_ready(
        self, name: str, namespace: str, timeout: int = 60
    ) -> str:
        """Poll the CR status until the operator reports it as Running.

        Returns the service hostname set by the operator.
        """
        api_client = await self._ensure_client()
        custom = client.CustomObjectsApi(api_client)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                cr = await custom.get_namespaced_custom_object(
                    group=self._group,
                    version=self._version,
                    namespace=namespace,
                    plural=self._plural,
                    name=name,
                )
                status = cr.get("status", {})
                if status.get("phase") == "Running" and status.get("host"):
                    return status["host"]
            except client.exceptions.ApiException:
                pass
            await asyncio.sleep(2)

        # Timed out — return the expected FQDN anyway; proxy will retry.
        log.warning(
            "Terminal CR %s did not reach Running in %ds, returning expected host",
            name,
            timeout,
        )
        return f"{name}.{namespace}.svc.cluster.local"
