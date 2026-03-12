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
Validate path segments used for projected secret file paths.
*/}}
{{- define "onyx.secretPathSegment" -}}
{{- $segment := . | toString -}}
{{- if or (contains "/" $segment) (contains "\\" $segment) (contains ".." $segment) -}}
{{- fail (printf "Invalid secret path segment %q: must not contain '/', '\\\\', or '..'" $segment) -}}
{{- end -}}
{{- $segment -}}
{{- end }}

{{/*
Create env vars from secrets
*/}}
{{- define "onyx.envSecrets" -}}
    {{- $secretFilesEnabled := include "onyx.secretsAsFiles.enabled" . }}
    {{- $secretFilesMountPath := include "onyx.secretsAsFiles.mountPath" . }}
    {{- range $secretSuffix, $secretContent := .Values.auth }}
    {{- if and (kindIs "map" $secretContent) (ne $secretContent.enabled false) ($secretContent.secretKeys) }}
    {{- range $name, $key := $secretContent.secretKeys }}
    {{- $envVarName := $name | upper | replace "-" "_" }}
    {{- $secretKey := default $name $key }}
    {{- $safeSecretSuffix := include "onyx.secretPathSegment" $secretSuffix }}
    {{- $safeSecretKey := include "onyx.secretPathSegment" $secretKey }}
    {{- if $secretFilesEnabled }}
- name: {{ printf "%s_FILE" $envVarName | quote }}
  value: {{ printf "%s/%s/%s" $secretFilesMountPath $safeSecretSuffix $safeSecretKey | quote }}
    {{- else }}
- name: {{ $envVarName | quote }}
  valueFrom:
    secretKeyRef:
      name: {{ include "onyx.secretName" $secretContent }}
      key: {{ $secretKey }}
    {{- end }}
    {{- end }}
    {{- end }}
    {{- end }}
{{- end }}

{{/*
Secret file mounting helpers.
*/}}
{{- define "onyx.secretsAsFiles.enabled" -}}
{{- if and .Values.secretsAsFiles .Values.secretsAsFiles.enabled }}true{{- end }}
{{- end }}

{{- define "onyx.secretsAsFiles.mountPath" -}}
{{- if and .Values.secretsAsFiles .Values.secretsAsFiles.mountPath -}}
{{- .Values.secretsAsFiles.mountPath -}}
{{- else -}}
/etc/onyx-secrets
{{- end }}
{{- end }}

{{- define "onyx.secretsAsFiles.volumeMounts" -}}
{{- if (include "onyx.secretsAsFiles.enabled" .) }}
{{- $mountPath := include "onyx.secretsAsFiles.mountPath" . }}
{{- range $secretSuffix, $secretContent := .Values.auth }}
{{- if and (kindIs "map" $secretContent) (ne $secretContent.enabled false) ($secretContent.secretKeys) }}
{{- $safeSecretSuffix := include "onyx.secretPathSegment" $secretSuffix }}
- name: {{ printf "auth-secret-%s" ($secretSuffix | lower | replace "_" "-") }}
  mountPath: {{ printf "%s/%s" $mountPath $safeSecretSuffix | quote }}
  readOnly: true
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{- define "onyx.secretsAsFiles.volumes" -}}
{{- if (include "onyx.secretsAsFiles.enabled" .) }}
{{- range $secretSuffix, $secretContent := .Values.auth }}
{{- if and (kindIs "map" $secretContent) (ne $secretContent.enabled false) ($secretContent.secretKeys) }}
- name: {{ printf "auth-secret-%s" ($secretSuffix | lower | replace "_" "-") }}
  secret:
    secretName: {{ include "onyx.secretName" $secretContent }}
    items:
    {{- range $name, $key := $secretContent.secretKeys }}
    {{- $safeSecretKey := include "onyx.secretPathSegment" (default $name $key) }}
      - key: {{ default $name $key }}
        path: {{ $safeSecretKey }}
    {{- end }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Helpers for mounting a psql convenience script into pods.
*/}}
{{- define "onyx.pgInto.enabled" -}}
{{- if and .Values.tooling .Values.tooling.pgInto .Values.tooling.pgInto.enabled }}true{{- end }}
{{- end }}

{{- define "onyx.pgInto.configMapName" -}}
{{- printf "%s-pginto" (include "onyx.fullname" .) -}}
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
{{- $secretFiles := include "onyx.secretsAsFiles.volumeMounts" .ctx -}}
{{- $existing := .volumeMounts -}}
{{- if or $pginto $secretFiles $existing -}}
volumeMounts:
{{- if $pginto }}
{{ $pginto | nindent 2 }}
{{- end }}
{{- if $secretFiles }}
{{ $secretFiles | nindent 2 }}
{{- end }}
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}

{{- define "onyx.renderVolumes" -}}
{{- $pginto := include "onyx.pgInto.volume" .ctx -}}
{{- $secretFiles := include "onyx.secretsAsFiles.volumes" .ctx -}}
{{- $existing := .volumes -}}
{{- if or $pginto $secretFiles $existing -}}
volumes:
{{- if $pginto }}
{{ $pginto | nindent 2 }}
{{- end }}
{{- if $secretFiles }}
{{ $secretFiles | nindent 2 }}
{{- end }}
{{- if $existing }}
{{ toYaml $existing | nindent 2 }}
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
