"""Open Terminal Operator — Kopf handlers for the Terminal CRD.

Watches ``Terminal`` custom resources (``terminals.openwebui.com/v1alpha1``)
and reconciles the underlying Kubernetes resources:

- **Pod** running the open-terminal container
- **Service** (ClusterIP) exposing port 8000
- **PVC** (optional) for persistent ``/home/user`` storage

The orchestrator creates/deletes Terminal CRs; this operator does the rest.
"""

import kopf
import kubernetes_asyncio as k8s
from kubernetes_asyncio import client, config

GROUP = "openwebui.com"
VERSION = "v1alpha1"
PLURAL = "terminals"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@kopf.on.startup()
async def configure(settings: kopf.OperatorSettings, **_):
    """Load K8s config at startup."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        await config.load_kube_config()
    settings.posting.level = kopf.INFO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner_ref(body: dict) -> list[dict]:
    """Build an ownerReferences list so child resources are garbage-collected."""
    return [
        {
            "apiVersion": f"{GROUP}/{VERSION}",
            "kind": "Terminal",
            "name": body["metadata"]["name"],
            "uid": body["metadata"]["uid"],
            "controller": True,
            "blockOwnerDeletion": True,
        }
    ]


def _labels(spec: dict) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": "open-terminal-operator",
        "app.kubernetes.io/part-of": "open-terminal",
        "openwebui.com/user-id": spec["userId"],
    }


async def _patch_status(name: str, namespace: str, status: dict):
    """Patch the Terminal CR status subresource."""
    async with k8s.client.ApiClient() as api:
        custom = client.CustomObjectsApi(api)
        await custom.patch_namespaced_custom_object_status(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=PLURAL,
            name=name,
            body={"status": status},
        )


# ---------------------------------------------------------------------------
# Create handler
# ---------------------------------------------------------------------------


@kopf.on.create(GROUP, VERSION, PLURAL)
async def on_create(spec, name, namespace, body, **_):
    """Provision a Pod + Service (+ optional PVC) for a new Terminal CR."""
    labels = _labels(spec)
    owner = _owner_ref(body)
    image = spec.get("image", "ghcr.io/open-webui/open-terminal:latest")
    api_key = spec["apiKey"]
    storage = spec.get("storage", {})

    await _patch_status(name, namespace, {"phase": "Provisioning"})

    async with k8s.client.ApiClient() as api:
        core = client.CoreV1Api(api)

        # ---- PVC (optional) ----------------------------------------------
        volumes = []
        volume_mounts = []

        if storage.get("enabled"):
            pvc = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(
                    name=name,
                    namespace=namespace,
                    labels=labels,
                    owner_references=owner,
                ),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    resources=client.V1VolumeResourceRequirements(
                        requests={"storage": storage.get("size", "1Gi")},
                    ),
                    **(
                        {"storage_class_name": storage["storageClass"]}
                        if storage.get("storageClass")
                        else {}
                    ),
                ),
            )
            try:
                await core.create_namespaced_persistent_volume_claim(namespace, pvc)
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

        # ---- Pod ---------------------------------------------------------
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels=labels,
                owner_references=owner,
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="open-terminal",
                        image=image,
                        ports=[client.V1ContainerPort(container_port=8000)],
                        env=[
                            client.V1EnvVar(
                                name="OPEN_TERMINAL_API_KEY", value=api_key
                            ),
                        ],
                        volume_mounts=volume_mounts or None,
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
                restart_policy="Always",
            ),
        )
        try:
            await core.create_namespaced_pod(namespace, pod)
        except client.exceptions.ApiException as exc:
            if exc.status != 409:
                await _patch_status(
                    name, namespace, {"phase": "Error", "message": str(exc)}
                )
                raise

        # ---- Service -----------------------------------------------------
        svc = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels=labels,
                owner_references=owner,
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"openwebui.com/user-id": spec["userId"]},
                ports=[client.V1ServicePort(port=8000, target_port=8000)],
            ),
        )
        try:
            await core.create_namespaced_service(namespace, svc)
        except client.exceptions.ApiException as exc:
            if exc.status != 409:
                raise

    host = f"{name}.{namespace}.svc.cluster.local"
    await _patch_status(
        name,
        namespace,
        {
            "phase": "Running",
            "podName": name,
            "serviceName": name,
            "host": host,
            "port": 8000,
        },
    )

    return {"message": f"Terminal {name} provisioned at {host}:8000"}


# ---------------------------------------------------------------------------
# Replicas field change (start / stop)
# ---------------------------------------------------------------------------


@kopf.on.field(GROUP, VERSION, PLURAL, field="spec.replicas")
async def on_replicas_change(spec, name, namespace, old, new, **_):
    """Handle spec.replicas changes for start/stop."""
    replicas = new or spec.get("replicas", 1)

    async with k8s.client.ApiClient() as api:
        core = client.CoreV1Api(api)

        if replicas == 0:
            # Stop — delete the Pod (Service stays for quick restart).
            try:
                await core.delete_namespaced_pod(name, namespace)
            except client.exceptions.ApiException:
                pass
            await _patch_status(name, namespace, {"phase": "Stopped"})

        elif replicas == 1:
            # Start — need to check if Pod exists, recreate if not.
            try:
                await core.read_namespaced_pod(name, namespace)
                # Pod exists, nothing to do.
                await _patch_status(name, namespace, {"phase": "Running"})
            except client.exceptions.ApiException:
                # Pod is gone — trigger a full re-provision by raising a
                # temporary error so Kopf retries via the create handler.
                # For simplicity, we recreate inline.
                labels = _labels(spec)
                image = spec.get("image", "ghcr.io/open-webui/open-terminal:latest")
                api_key = spec["apiKey"]
                storage = spec.get("storage", {})

                volumes = []
                volume_mounts = []
                if storage.get("enabled"):
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

                pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name=name,
                        namespace=namespace,
                        labels=labels,
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="open-terminal",
                                image=image,
                                ports=[
                                    client.V1ContainerPort(container_port=8000)
                                ],
                                env=[
                                    client.V1EnvVar(
                                        name="OPEN_TERMINAL_API_KEY",
                                        value=api_key,
                                    ),
                                ],
                                volume_mounts=volume_mounts or None,
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
                        restart_policy="Always",
                    ),
                )
                await core.create_namespaced_pod(namespace, pod)
                await _patch_status(name, namespace, {"phase": "Running"})


# ---------------------------------------------------------------------------
# Delete handler (cleanup is automatic via ownerReferences, but log it)
# ---------------------------------------------------------------------------


@kopf.on.delete(GROUP, VERSION, PLURAL)
async def on_delete(name, namespace, **_):
    """Log deletion — K8s garbage-collects child resources via ownerReferences."""
    kopf.info(
        {"metadata": {"name": name, "namespace": namespace}},
        reason="Deleted",
        message=f"Terminal {name} deleted, child resources will be garbage-collected.",
    )
