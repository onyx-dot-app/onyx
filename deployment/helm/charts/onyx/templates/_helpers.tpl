{{/*
Expand the name of the chart.
*/}}
{{- define "onyx.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "onyx.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "onyx.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Build a child resource name as `<fullname>-<suffix>`, capped at 63 chars to
satisfy the Kubernetes DNS-1123 label limit that applies to Services, Pods,
Deployments, HPAs, etc. Names that fit are used as-is. Longer names are
truncated and get a short hash of the full name, so two suffixes that share a
prefix (e.g. celery-worker-docfetching / celery-worker-docprocessing) cannot
collapse onto the same truncated name. The result is deterministic, so every
caller that passes the same suffix renders the same name and cross-references
stay consistent. Always use this instead of
  {{ include "onyx.fullname" . }}-<suffix>
Callers must pass `(list . "<suffix>")`.
*/}}
{{- define "onyx.resourceName" -}}
{{- $ctx := index . 0 -}}
{{- $suffix := index . 1 -}}
{{- $name := printf "%s-%s" (include "onyx.fullname" $ctx) $suffix -}}
{{- if gt (len $name) 63 -}}
{{- printf "%s-%s" ($name | trunc 54 | trimSuffix "-") (sha256sum $name | trunc 8) -}}
{{- else -}}
{{- $name -}}
{{- end -}}
{{- end }}

{{/*
Common labels
*/}}
{{- define "onyx.labels" -}}
helm.sh/chart: {{ include "onyx.chart" . }}
{{ include "onyx.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "onyx.selectorLabels" -}}
app.kubernetes.io/name: {{ include "onyx.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "onyx.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "onyx.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Set secret name
*/}}
{{- define "onyx.secretName" -}}
{{- default .secretName .existingSecret }}
{{- end }}

{{/*
Create env vars from secrets (global secrets only — skips entries with allPods: false)
*/}}
{{- define "onyx.envSecrets" -}}
    {{- range $secretSuffix, $secretContent := .Values.auth }}
    {{- $allPods := or (not (hasKey $secretContent "allPods")) (ne (toString $secretContent.allPods) "false") }}
    {{- if and (ne $secretSuffix "metricsAuth") (ne (toString $secretContent.enabled) "false") ($secretContent.secretKeys) $allPods }}
    {{- range $name, $key := $secretContent.secretKeys }}
- name: {{ $name | upper | replace "-" "_" | quote }}
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $secretContent }}
      key: {{ default $name $key }}
    {{- end }}
    {{- end }}
    {{- end }}
{{- end }}

{{/*
Create env vars from secrets restricted to specific pods (entries with allPods: false)
*/}}
{{- define "onyx.envSecretsRestricted" -}}
    {{- range $secretSuffix, $secretContent := .Values.auth }}
    {{- $restricted := and (hasKey $secretContent "allPods") (eq (toString $secretContent.allPods) "false") }}
    {{- if and (ne $secretSuffix "metricsAuth") (ne (toString $secretContent.enabled) "false") ($secretContent.secretKeys) $restricted }}
    {{- range $name, $key := $secretContent.secretKeys }}
- name: {{ $name | upper | replace "-" "_" | quote }}
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $secretContent }}
      key: {{ default $name $key }}
    {{- end }}
    {{- end }}
    {{- end }}
{{- end }}

{{/*
Inject metrics auth only into pods that expose the protected endpoint.
*/}}
{{- define "onyx.metricsAuthEnv" -}}
    {{- $metricsAuth := .Values.auth.metricsAuth | default dict }}
    {{- if dig "enabled" false $metricsAuth }}
- name: METRICS_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $metricsAuth }}
      key: {{ default "METRICS_AUTH_TOKEN" (dig "secretKeys" "METRICS_AUTH_TOKEN" "" $metricsAuth) }}
    {{- end }}
{{- end }}

{{/*
Helpers for mounting a psql convenience script into pods.
*/}}
{{- define "onyx.pgInto.enabled" -}}
{{- if and .Values.tooling .Values.tooling.pgInto .Values.tooling.pgInto.enabled }}true{{- end }}
{{- end }}

{{- define "onyx.pgInto.configMapName" -}}
{{- include "onyx.resourceName" (list . "pginto") -}}
{{- end }}

{{- define "onyx.pgInto.checksumAnnotation" -}}
{{- if (include "onyx.pgInto.enabled" .) }}
checksum/pginto: {{ include (print $.Template.BasePath "/tooling-pginto-configmap.yaml") . | sha256sum }}
{{- end }}
{{- end }}

{{- define "onyx.pgInto.volumeMount" -}}
{{- if (include "onyx.pgInto.enabled" .) }}
- name: pginto-script
  mountPath: {{ default "/usr/local/bin/pginto" .Values.tooling.pgInto.mountPath }}
  subPath: pginto
  readOnly: true
{{- end }}
{{- end }}

{{- define "onyx.pgInto.volume" -}}
{{- if (include "onyx.pgInto.enabled" .) }}
- name: pginto-script
  configMap:
    name: {{ include "onyx.pgInto.configMapName" . }}
    defaultMode: 0755
{{- end }}
{{- end }}

{{- define "onyx.renderVolumeMounts" -}}
{{- $pginto := include "onyx.pgInto.volumeMount" .ctx -}}
{{- $ca := include "onyx.customCACerts.volumeMount" .ctx -}}
{{- $postgresTls := include "onyx.postgresTls.volumeMount" .ctx -}}
{{- $redisTls := include "onyx.redisTls.volumeMount" .ctx -}}
{{- $existing := .volumeMounts -}}
{{- if or $pginto $ca $postgresTls $redisTls $existing -}}
volumeMounts:
{{- if $pginto }}
{{ $pginto | nindent 2 }}
{{- end }}
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- if $postgresTls }}
{{ $postgresTls | nindent 2 }}
{{- end }}
{{- if $redisTls }}
{{ $redisTls | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{- define "onyx.renderVolumes" -}}
{{- $pginto := include "onyx.pgInto.volume" .ctx -}}
{{- $ca := include "onyx.customCACerts.volume" .ctx -}}
{{- $postgresTls := include "onyx.postgresTls.volume" .ctx -}}
{{- $redisTls := include "onyx.redisTls.volume" .ctx -}}
{{- $existing := .volumes -}}
{{- if or $pginto $ca $postgresTls $redisTls $existing -}}
volumes:
{{- if $pginto }}
{{ $pginto | nindent 2 }}
{{- end }}
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- if $postgresTls }}
{{ $postgresTls | nindent 2 }}
{{- end }}
{{- if $redisTls }}
{{ $redisTls | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{/*
Return the configured autoscaling engine; defaults to HPA when unset.
*/}}
{{- define "onyx.autoscaling.engine" -}}
{{- $engine := default "hpa" .Values.autoscaling.engine -}}
{{- $engine | lower -}}
{{- end }}

{{/*
"true" when ENABLE_CRAFT is set in configMap, empty otherwise.
*/}}
{{- define "onyx.craftEnabled" -}}
{{- if eq (toString (index .Values.configMap "ENABLE_CRAFT" | default "")) "true" -}}true{{- end -}}
{{- end }}

{{/*
Sandbox container image and pull policy. Shared by the sandbox-pod PodTemplate
and the image-prepull DaemonSet: the prepull only pins layers the sandbox pods
actually use if both resolve to the identical reference, and a drift here is
invisible (the DaemonSet looks healthy while every sandbox still cold-pulls).
*/}}
{{- define "onyx.sandboxImage" -}}
{{- (index .Values.configMap "SANDBOX_CONTAINER_IMAGE") | default (printf "onyxdotapp/sandbox:%s" (.Values.global.version | default .Chart.AppVersion)) -}}
{{- end }}

{{- define "onyx.sandboxImagePullPolicy" -}}
{{- (index .Values.configMap "SANDBOX_IMAGE_PULL_POLICY") | default .Values.global.pullPolicy -}}
{{- end }}

{{- define "onyx.sandboxProxyHost" -}}
{{- (index .Values.configMap "SANDBOX_PROXY_HOST") | default (printf "%s.%s.svc.cluster.local" (include "onyx.resourceName" (list . "sandbox-proxy")) .Release.Namespace) -}}
{{- end }}

{{- define "onyx.sandboxProxyPort" -}}
8080
{{- end }}

{{- define "onyx.sandboxPushDaemonPort" -}}
8731
{{- end }}

{{/* Sandbox egress-proxy env. Mirrors _proxy_main_container_env_vars(). */}}
{{- define "onyx.sandboxProxyEnv" -}}
{{- $proxyUrl := printf "http://sandbox-proxy:%v" .proxyPort }}
- { name: HTTPS_PROXY, value: "{{ $proxyUrl }}" }
- { name: HTTP_PROXY, value: "{{ $proxyUrl }}" }
- { name: https_proxy, value: "{{ $proxyUrl }}" }
- { name: http_proxy, value: "{{ $proxyUrl }}" }
- { name: NO_PROXY, value: "127.0.0.1,localhost" }
- { name: no_proxy, value: "127.0.0.1,localhost" }
- { name: NODE_EXTRA_CA_CERTS, value: "{{ .caBundleFile }}" }
- { name: REQUESTS_CA_BUNDLE, value: "{{ .caBundleFile }}" }
- { name: SSL_CERT_FILE, value: "{{ .caBundleFile }}" }
- { name: AWS_CA_BUNDLE, value: "{{ .caBundleFile }}" }
- { name: CURL_CA_BUNDLE, value: "{{ .caBundleFile }}" }
- { name: GIT_SSL_CAINFO, value: "{{ .caBundleFile }}" }
{{- end }}

{{/*
"true" when custom CA certificates are configured, empty otherwise.
*/}}
{{- define "onyx.customCACerts.enabled" -}}
{{- if and .Values.customCACerts .Values.customCACerts.enabled -}}true{{- end -}}
{{- end }}

{{/*
Volume sourcing the custom CA certificates from a Secret or ConfigMap.
*/}}
{{- define "onyx.customCACerts.volume" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
{{- if and .Values.customCACerts.secretName .Values.customCACerts.configMapName -}}
{{- fail "customCACerts.secretName and customCACerts.configMapName are mutually exclusive; set exactly one" -}}
{{- end -}}
{{- if .Values.customCACerts.secretName -}}
- name: custom-ca-certs
  secret:
    secretName: {{ .Values.customCACerts.secretName }}
{{- else if .Values.customCACerts.configMapName -}}
- name: custom-ca-certs
  configMap:
    name: {{ .Values.customCACerts.configMapName }}
{{- else -}}
{{- fail "customCACerts.enabled is true but neither customCACerts.secretName nor customCACerts.configMapName is set" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Mount for the custom CA certificates. update-ca-certificates picks up
PEM files with a .crt suffix from /usr/local/share/ca-certificates.
*/}}
{{- define "onyx.customCACerts.volumeMount" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
- name: custom-ca-certs
  mountPath: /usr/local/share/ca-certificates
  readOnly: true
{{- end -}}
{{- end }}

{{/*
Env vars so Python HTTP clients (which default to certifi's bundle) trust
the system bundle regenerated by update-ca-certificates.
*/}}
{{- define "onyx.customCACerts.env" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
- name: REQUESTS_CA_BUNDLE
  value: /etc/ssl/certs/ca-certificates.crt
- name: SSL_CERT_FILE
  value: /etc/ssl/certs/ca-certificates.crt
{{- end -}}
{{- end }}

{{/*
Items to prepend to an exec-form container command so update-ca-certificates
runs first; sh passes the original command through via "$0" "$@".
Emits a single line ending with a comma.
*/}}
{{- define "onyx.customCACerts.commandPrefix" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
"/bin/sh", "-c", "update-ca-certificates && exec \"$0\" \"$@\"",
{{- end -}}
{{- end }}

{{/*
"true" when PostgreSQL TLS settings and a CA certificate source are configured.
*/}}
{{- define "onyx.postgresTls.enabled" -}}
{{- if and .Values.postgresTls .Values.postgresTls.enabled }}true{{- end -}}
{{- end }}

{{/*
Volume sourcing the PostgreSQL server CA. The backend validates the configured
path at startup, so mount exactly the configured key at its expected filename.
*/}}
{{- define "onyx.postgresTls.volume" -}}
{{- if include "onyx.postgresTls.enabled" . -}}
{{- $tls := .Values.postgresTls -}}
{{- if and $tls.caSecretName $tls.caConfigMapName -}}
{{- fail "postgresTls.caSecretName and postgresTls.caConfigMapName are mutually exclusive; set exactly one" -}}
{{- end -}}
{{- $caPath := $tls.caMountPath | default "/etc/postgres-ca/ca.crt" -}}
{{- $caKey := $tls.caKey | default "ca.crt" -}}
- name: postgres-ca
  {{- if $tls.caSecretName }}
  secret:
    secretName: {{ $tls.caSecretName }}
    items:
      - key: {{ $caKey }}
        path: {{ base $caPath }}
  {{- else if $tls.caConfigMapName }}
  configMap:
    name: {{ $tls.caConfigMapName }}
    items:
      - key: {{ $caKey }}
        path: {{ base $caPath }}
  {{- else -}}
  {{- fail "postgresTls.enabled is true but neither postgresTls.caSecretName nor postgresTls.caConfigMapName is set" -}}
  {{- end }}
{{- end -}}
{{- end }}

{{/* Mount for the PostgreSQL server CA. */}}
{{- define "onyx.postgresTls.volumeMount" -}}
{{- if include "onyx.postgresTls.enabled" . -}}
{{- $caPath := .Values.postgresTls.caMountPath | default "/etc/postgres-ca/ca.crt" -}}
- name: postgres-ca
  mountPath: {{ dir $caPath }}
  readOnly: true
{{- end -}}
{{- end }}

{{/*
"true" when Redis TLS settings and a CA certificate source are configured.
*/}}
{{- define "onyx.redisTls.enabled" -}}
{{- $tls := .Values.redisTls | default dict -}}
{{- if hasKey $tls "enabled" -}}
{{- if eq (toString (index $tls "enabled")) "true" }}true{{- end -}}
{{- end -}}
{{- end }}

{{/*
Redis hostname verification defaults to enabled. Only an explicit Boolean false
disables it; missing, null, and invalid values keep the secure default.
*/}}
{{- define "onyx.redisTls.checkHostname" -}}
{{- $tls := .Values.redisTls | default dict -}}
{{- $checkHostname := index $tls "checkHostname" -}}
{{- if kindIs "bool" $checkHostname -}}
{{- $checkHostname -}}
{{- else -}}
true
{{- end -}}
{{- end }}

{{/*
Volume sourcing the Redis server CA. The backend uses the configured path for
REDIS_SSL_CA_CERTS, so mount exactly the configured key at its expected name.
*/}}
{{- define "onyx.redisTls.volume" -}}
{{- if include "onyx.redisTls.enabled" . -}}
{{- $tls := .Values.redisTls | default dict -}}
{{- if and $tls.caSecretName $tls.caConfigMapName -}}
{{- fail "redisTls.caSecretName and redisTls.caConfigMapName are mutually exclusive; set exactly one" -}}
{{- end -}}
{{- $caPath := $tls.caMountPath | default "/etc/ssl/certs/redis-ca.crt" -}}
{{- $caKey := $tls.caKey | default "ca.crt" -}}
- name: redis-ca
  {{- if $tls.caSecretName }}
  secret:
    secretName: {{ $tls.caSecretName }}
    items:
      - key: {{ $caKey }}
        path: {{ base $caPath }}
  {{- else if $tls.caConfigMapName }}
  configMap:
    name: {{ $tls.caConfigMapName }}
    items:
      - key: {{ $caKey }}
        path: {{ base $caPath }}
  {{- else -}}
  {{- fail "redisTls.enabled is true but neither redisTls.caSecretName nor redisTls.caConfigMapName is set" -}}
  {{- end }}
{{- end -}}
{{- end }}

{{/* Mount for the Redis server CA. */}}
{{- define "onyx.redisTls.volumeMount" -}}
{{- if include "onyx.redisTls.enabled" . -}}
{{- $tls := .Values.redisTls | default dict -}}
{{- $caPath := $tls.caMountPath | default "/etc/ssl/certs/redis-ca.crt" -}}
- name: redis-ca
  mountPath: {{ $caPath }}
  subPath: {{ base $caPath }}
  readOnly: true
{{- end -}}
{{- end }}

{{/*
Model-server variant of the custom-CA env. The model servers run on a distroless
image with no shell to run update-ca-certificates, so instead of pointing at the
merged system store they hand the mount directory to the Python entrypoint, which
concatenates the mounted roots with certifi's public roots at startup. Any key
name(s) under the mount work, and the roots stay additive to the public roots.
*/}}
{{- define "onyx.customCACerts.modelServerEnv" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
- name: ONYX_CUSTOM_CA_CERTS_DIR
  value: /etc/onyx/certs
{{- end -}}
{{- end }}

{{/*
Model-server variant of the custom-CA mount: mounts the bundle directory the
entrypoint reads (no update-ca-certificates step) at the path the env above names.
*/}}
{{- define "onyx.customCACerts.modelServerVolumeMount" -}}
{{- if include "onyx.customCACerts.enabled" . -}}
- name: custom-ca-certs
  mountPath: /etc/onyx/certs
  readOnly: true
{{- end -}}
{{- end }}

{{/*
Render a volumeMounts block for the model servers, combining pod-specific mounts
with the model-server custom-CA mount.
Usage: include "onyx.modelServer.volumeMountsWithCA" (dict "ctx" . "volumeMounts" <list>)
*/}}
{{- define "onyx.modelServer.volumeMountsWithCA" -}}
{{- $ca := include "onyx.customCACerts.modelServerVolumeMount" .ctx -}}
{{- $existing := .volumeMounts -}}
{{- if or $ca $existing -}}
volumeMounts:
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{/*
Render a volumes block combining pod-specific volumes with the model-server
custom-CA volume. Usage: include "onyx.modelServer.volumesWithCA" (dict "ctx" . "volumes" <list>)
*/}}
{{- define "onyx.modelServer.volumesWithCA" -}}
{{- $ca := include "onyx.customCACerts.volume" .ctx -}}
{{- $existing := .volumes -}}
{{- if or $ca $existing -}}
volumes:
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{/*
Render a volumeMounts block combining pod-specific mounts with the custom CA
mount. Usage: include "onyx.volumeMountsWithCA" (dict "ctx" . "volumeMounts" <list>)
*/}}
{{- define "onyx.volumeMountsWithCA" -}}
{{- $ca := include "onyx.customCACerts.volumeMount" .ctx -}}
{{- $postgresTls := include "onyx.postgresTls.volumeMount" .ctx -}}
{{- $redisTls := include "onyx.redisTls.volumeMount" .ctx -}}
{{- $existing := .volumeMounts -}}
{{- if or $ca $postgresTls $redisTls $existing -}}
volumeMounts:
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- if $postgresTls }}
{{ $postgresTls | nindent 2 }}
{{- end }}
{{- if $redisTls }}
{{ $redisTls | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{/*
Render a volumes block combining pod-specific volumes with the custom CA
volume. Usage: include "onyx.volumesWithCA" (dict "ctx" . "volumes" <list>)
*/}}
{{- define "onyx.volumesWithCA" -}}
{{- $ca := include "onyx.customCACerts.volume" .ctx -}}
{{- $postgresTls := include "onyx.postgresTls.volume" .ctx -}}
{{- $redisTls := include "onyx.redisTls.volume" .ctx -}}
{{- $existing := .volumes -}}
{{- if or $ca $postgresTls $redisTls $existing -}}
volumes:
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- if $ca }}
{{ $ca | nindent 2 }}
{{- end }}
{{- if $postgresTls }}
{{ $postgresTls | nindent 2 }}
{{- end }}
{{- if $redisTls }}
{{ $redisTls | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{/* Set = used as-is, empty = chart default, null = no probe (Helm drops null keys). */}}
{{- define "onyx.readinessProbe" -}}
{{- if hasKey .values "readinessProbe" }}
{{- with (.values.readinessProbe | default (merge (dict "periodSeconds" 10 "timeoutSeconds" 5 "failureThreshold" 3) .handler)) }}
readinessProbe:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
{{- end }}

{{/* Native sleep action: the web image has no shell or sleep binary. */}}
{{- define "onyx.preStopSleep" -}}
{{- $seconds := int (.values.preStopSleepSeconds | default 0) }}
{{- if and (gt $seconds 0) (semverCompare ">=1.30.0-0" .ctx.Capabilities.KubeVersion.Version) }}
lifecycle:
  preStop:
    sleep:
      seconds: {{ $seconds }}
{{- end }}
{{- end }}

{{/*
Whether the chart runs the bundled object store. Unset follows minio.enabled, so
an install on external object storage (minio.enabled: false) is left as it is.
*/}}
{{- define "onyx.objectStore.enabled" -}}
{{- $objectStore := .Values.objectStore | default dict -}}
{{- if kindIs "bool" $objectStore.enabled -}}
{{- $objectStore.enabled -}}
{{- else -}}
{{- .Values.minio.enabled | default false -}}
{{- end -}}
{{- end }}

{{/*
objectStore values over the defaults below. `helm upgrade --reuse-values` swaps
the chart's values.yaml for the old release's values, which have no objectStore,
so the templates must not depend on values.yaml for these keys.
*/}}
{{- define "onyx.objectStore.values" -}}
{{- $minioPersistence := .Values.minio.persistence | default dict -}}
{{- $defaults := dict
  "image" (dict "repository" "chrislusf/seaweedfs" "tag" "4.47@sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882" "pullPolicy" "IfNotPresent")
  "service" (dict "port" 8333)
  "persistence" (dict "size" (dig "size" "30Gi" $minioPersistence) "storageClass" (dig "storageClass" "" $minioPersistence) "annotations" dict)
  "resources" (dict "requests" (dict "cpu" "100m" "memory" "256Mi") "limits" (dict "memory" "2Gi"))
  "podSecurityContext" (dict "runAsNonRoot" true "runAsUser" 1000 "runAsGroup" 1000 "fsGroup" 1000 "fsGroupChangePolicy" "OnRootMismatch" "seccompProfile" (dict "type" "RuntimeDefault"))
  "securityContext" (dict "allowPrivilegeEscalation" false "readOnlyRootFilesystem" true "capabilities" (dict "drop" (list "ALL")))
  "podAnnotations" dict
  "podLabels" dict
  "nodeSelector" dict
  "tolerations" list
  "affinity" dict
  "priorityClassName" ""
  "legacyCopy" (dict "enabled" true "settleSeconds" 600 "workers" 16 "backoffLimit" 20 "resources" (dict "requests" (dict "cpu" "100m" "memory" "256Mi") "limits" (dict "memory" "1Gi")) "nodeSelector" dict "tolerations" list "affinity" dict)
-}}
{{- $user := .Values.objectStore | default dict -}}
{{- $merged := mergeOverwrite $defaults (deepCopy $user) -}}
{{- /* A merge cannot clear a default, and OpenShift needs podSecurityContext: {}. */ -}}
{{- range $key := list "podSecurityContext" "securityContext" "resources" -}}
{{- if hasKey $user $key -}}
{{- $_ := set $merged $key (get $user $key) -}}
{{- end -}}
{{- end -}}
{{- $userCopy := $user.legacyCopy | default dict -}}
{{- if hasKey $userCopy "resources" -}}
{{- $_ := set $merged.legacyCopy "resources" $userCopy.resources -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end }}

{{/* The bundled object store's Service name and S3 endpoint. */}}
{{- define "onyx.objectStore.endpoint" -}}
{{- $objectStore := include "onyx.objectStore.values" . | fromYaml -}}
{{- printf "http://%s:%v" (include "onyx.resourceName" (list . "object-store")) $objectStore.service.port -}}
{{- end }}

{{/* The app's S3 key pair, which is also the object store's admin identity. */}}
{{- define "onyx.objectStore.credentialEnv" -}}
{{- $auth := .ctx.Values.auth.objectstorage -}}
- name: {{ .prefix }}_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $auth }}
      key: {{ $auth.secretKeys.S3_AWS_ACCESS_KEY_ID | default "s3_aws_access_key_id" }}
- name: {{ .prefix }}_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $auth }}
      key: {{ $auth.secretKeys.S3_AWS_SECRET_ACCESS_KEY | default "s3_aws_secret_access_key" }}
{{- end }}

{{/* The legacy-minio-copy Job's pod. Scheduling falls back to api's. */}}
{{- define "onyx.objectStore.legacyCopyPod" -}}
{{- $ctx := .ctx -}}
{{- $copy := .copy -}}
# Without the chart version, so a chart-only upgrade keeps the same Job name.
metadata:
  labels:
    {{- include "onyx.selectorLabels" $ctx | nindent 4 }}
    app: legacy-minio-copy
spec:
  restartPolicy: OnFailure
  {{- with $ctx.Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  serviceAccountName: {{ include "onyx.serviceAccountName" $ctx }}
  securityContext:
    {{- toYaml $ctx.Values.api.podSecurityContext | nindent 4 }}
  {{- with ($copy.nodeSelector | default $ctx.Values.api.nodeSelector) }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with ($copy.affinity | default $ctx.Values.api.affinity) }}
  affinity:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with ($copy.tolerations | default $ctx.Values.api.tolerations) }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  containers:
    - name: legacy-minio-copy
      image: "{{ $ctx.Values.api.image.repository }}:{{ $ctx.Values.api.image.tag | default $ctx.Values.global.version }}"
      imagePullPolicy: {{ $ctx.Values.global.pullPolicy }}
      command: ["python", "-m", "onyx.file_store.legacy_copy"]
      # The same config and secrets as the app, so the copy reaches both stores as it does.
      envFrom:
        - configMapRef:
            name: {{ $ctx.Values.config.envConfigMapName }}
        {{- with $ctx.Values.extraEnvFromSecret }}
        - secretRef:
            name: {{ . }}
        {{- end }}
      env:
        {{- include "onyx.envSecrets" $ctx | nindent 8 }}
        {{- with include "onyx.customCACerts.env" $ctx }}
        {{- . | nindent 8 }}
        {{- end }}
        {{- with $ctx.Values.api.extraEnv }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
        - name: LEGACY_COPY_SETTLE_SECONDS
          value: {{ $copy.settleSeconds | quote }}
        - name: LEGACY_COPY_WORKERS
          value: {{ $copy.workers | quote }}
      resources:
        {{- toYaml $copy.resources | nindent 8 }}
      securityContext:
        {{- toYaml $ctx.Values.api.securityContext | nindent 8 }}
      # The api's files too, such as a CA bundle its extraEnv points at.
      {{- $tmpMount := dict "name" "tmp" "mountPath" "/tmp" }}
      {{- include "onyx.renderVolumeMounts" (dict "ctx" $ctx "volumeMounts" (prepend ($ctx.Values.api.volumeMounts | default list) $tmpMount)) | nindent 6 }}
  {{- $tmpVolume := dict "name" "tmp" "emptyDir" dict }}
  {{- include "onyx.renderVolumes" (dict "ctx" $ctx "volumes" (prepend ($ctx.Values.api.volumes | default list) $tmpVolume)) | nindent 2 }}
{{- end }}
