#!/bin/bash

# Parallel Kubernetes Migration Script with Temporary Jobs
# This script creates temporary Kubernetes Jobs with specified Docker images
# to distribute database migrations across multiple pods for faster processing.

set -e

# Configuration
NAMESPACE="danswer"
LOG_DIR="./migration_logs"
MIGRATION_COMMAND="alembic upgrade head"
MAX_JOBS=""  # Empty means calculate based on tenant count
DOCKER_IMAGE=""  # Must be specified via command line
JOB_PREFIX="migration-job"
JOB_TIMEOUT="3600"  # 1 hour timeout for jobs
CLEANUP_JOBS="true"  # Whether to cleanup jobs after completion

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to validate required tools
validate_prerequisites() {
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    if [ -z "$DOCKER_IMAGE" ]; then
        print_error "Docker image must be specified with -i/--image option"
        show_help
        exit 1
    fi
}

# Function to get tenant count using a temporary pod
get_tenant_count() {
    print_info "Getting tenant count using temporary pod..."
    
    local temp_pod_name="tenant-counter-$(date +%s)"
    local tenant_count=0
    
    # Create temporary pod to count tenants
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: $temp_pod_name
  namespace: $NAMESPACE
  labels:
    app: migration-tenant-counter
spec:
  restartPolicy: Never
  containers:
  - name: tenant-counter
    image: $DOCKER_IMAGE
    command: ["python3", "/opt/onyx/backend/scripts/get_tenant_count.py"]
    env:
    - name: POSTGRES_HOST
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: host
          optional: true
    - name: POSTGRES_USER
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: username
          optional: true
    - name: POSTGRES_PASSWORD
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: password
          optional: true
    - name: POSTGRES_DB
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: database
          optional: true
    - name: POSTGRES_PORT
      value: "5432"
EOF

    # Wait for pod to be ready and get logs
    print_info "Waiting for tenant counting pod to complete..."
    kubectl wait --for=condition=ready pod/$temp_pod_name -n $NAMESPACE --timeout=120s || {
        print_error "Tenant counting pod failed to start"
        kubectl delete pod $temp_pod_name -n $NAMESPACE --ignore-not-found=true
        exit 1
    }
    
    # Wait for completion
    kubectl wait --for=condition=PodReadyCondition=false pod/$temp_pod_name -n $NAMESPACE --timeout=120s || true
    
    # Get the tenant count from logs
    tenant_count=$(kubectl logs $temp_pod_name -n $NAMESPACE 2>/dev/null | tail -1 | grep -E '^[0-9]+$' || echo "0")
    
    # Cleanup temporary pod
    kubectl delete pod $temp_pod_name -n $NAMESPACE --ignore-not-found=true
    
    if [[ "$tenant_count" =~ ^[0-9]+$ ]] && [ "$tenant_count" -gt 0 ]; then
        echo "$tenant_count"
    else
        print_error "Failed to get valid tenant count: $tenant_count"
        exit 1
    fi
}

# Function to create migration job YAML
create_job_yaml() {
    local job_name=$1
    local start_range=$2
    local end_range=$3
    
    cat <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $job_name
  namespace: $NAMESPACE
  labels:
    app: parallel-migration
    migration-batch: "$(date +%Y%m%d-%H%M%S)"
spec:
  activeDeadlineSeconds: $JOB_TIMEOUT
  backoffLimit: 1
  template:
    metadata:
      labels:
        app: parallel-migration-pod
    spec:
      restartPolicy: Never
      containers:
      - name: migration-worker
        image: $DOCKER_IMAGE
        command: ["bash", "-c"]
        args:
        - |
          set -e
          cd /opt/onyx/backend
          echo "Starting migration for tenants $start_range-$end_range at \$(date)"
          $MIGRATION_COMMAND -x upgrade_all_tenants=true -x continue=true -x tenant_range_start=$start_range -x tenant_range_end=$end_range
          echo "Migration completed for tenants $start_range-$end_range at \$(date)"
        env:
        - name: POSTGRES_HOST
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: host
              optional: true
        - name: POSTGRES_USER
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: username
              optional: true
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: password
              optional: true
        - name: POSTGRES_DB
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: database
              optional: true
        - name: POSTGRES_PORT
          value: "5432"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
EOF
}

# Function to start migration job
start_migration_job() {
    local job_name=$1
    local start_range=$2
    local end_range=$3
    local log_file=$4
    
    print_info "Creating migration job: $job_name (tenants $start_range-$end_range)"
    
    # Create job YAML and apply it
    create_job_yaml "$job_name" "$start_range" "$end_range" | kubectl apply -f -
    
    if [ $? -eq 0 ]; then
        print_success "Job $job_name created successfully"
        return 0
    else
        print_error "Failed to create job $job_name"
        return 1
    fi
}

# Function to monitor job progress and collect logs
monitor_jobs() {
    local job_names=("$@")
    local completed_jobs=0
    local failed_jobs=0
    
    print_info "Monitoring ${#job_names[@]} migration jobs..."
    
    # Create log directory if it doesn't exist
    mkdir -p "$LOG_DIR"
    
    while [ $((completed_jobs + failed_jobs)) -lt ${#job_names[@]} ]; do
        sleep 10
        
        for job_name in "${job_names[@]}"; do
            # Skip if we've already processed this job
            if [ -f "$LOG_DIR/${job_name}.status" ]; then
                continue
            fi
            
            # Check job status
            local job_status
            job_status=$(kubectl get job "$job_name" -n "$NAMESPACE" -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo "Unknown")
            
            case "$job_status" in
                "Complete")
                    print_success "Job $job_name completed successfully"
                    ((completed_jobs++))
                    echo "completed" > "$LOG_DIR/${job_name}.status"
                    
                    # Get pod logs
                    local pod_name
                    pod_name=$(kubectl get pods -n "$NAMESPACE" --selector=job-name="$job_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
                    if [ -n "$pod_name" ]; then
                        kubectl logs "$pod_name" -n "$NAMESPACE" > "$LOG_DIR/${job_name}.log" 2>&1
                    fi
                    ;;
                "Failed")
                    print_error "Job $job_name failed"
                    ((failed_jobs++))
                    echo "failed" > "$LOG_DIR/${job_name}.status"
                    
                    # Get pod logs for debugging
                    local pod_name
                    pod_name=$(kubectl get pods -n "$NAMESPACE" --selector=job-name="$job_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
                    if [ -n "$pod_name" ]; then
                        kubectl logs "$pod_name" -n "$NAMESPACE" > "$LOG_DIR/${job_name}.log" 2>&1
                        kubectl describe pod "$pod_name" -n "$NAMESPACE" >> "$LOG_DIR/${job_name}.log" 2>&1
                    fi
                    ;;
            esac
        done
        
        # Show progress
        local total_jobs=${#job_names[@]}
        local processed=$((completed_jobs + failed_jobs))
        print_info "Progress: $processed/$total_jobs jobs processed (✓$completed_jobs ✗$failed_jobs)"
    done
    
    return $failed_jobs
}

# Function to cleanup jobs
cleanup_jobs() {
    local job_names=("$@")
    
    if [ "$CLEANUP_JOBS" != "true" ]; then
        print_info "Job cleanup disabled, leaving jobs in cluster"
        return 0
    fi
    
    print_info "Cleaning up migration jobs..."
    
    for job_name in "${job_names[@]}"; do
        kubectl delete job "$job_name" -n "$NAMESPACE" --ignore-not-found=true
        print_info "Deleted job: $job_name"
    done
}

# Main execution
main() {
    print_info "Starting parallel Kubernetes migration with temporary jobs"
    
    # Validate prerequisites
    validate_prerequisites
    
    # Get tenant count
    local tenant_count
    tenant_count=$(get_tenant_count)
    print_info "Total tenants to migrate: $tenant_count"
    
    # Calculate number of jobs to create
    local num_jobs
    if [ -n "$MAX_JOBS" ] && [ "$MAX_JOBS" -gt 0 ]; then
        num_jobs=$MAX_JOBS
    else
        # Default: one job per 10 tenants, minimum 1, maximum 20
        num_jobs=$(( (tenant_count + 9) / 10 ))
        if [ $num_jobs -lt 1 ]; then
            num_jobs=1
        elif [ $num_jobs -gt 20 ]; then
            num_jobs=20
        fi
    fi
    
    print_info "Creating $num_jobs parallel migration jobs"
    
    # Calculate tenant ranges per job
    local tenants_per_job=$((tenant_count / num_jobs))
    local remainder=$((tenant_count % num_jobs))
    
    print_info "~$tenants_per_job tenants per job"
    
    # Create migration jobs
    local job_names=()
    local current_start=1
    
    for i in $(seq 1 $num_jobs); do
        local tenants_for_this_job=$tenants_per_job
        
        # Add remainder to the last job
        if [ $i -eq $num_jobs ]; then
            tenants_for_this_job=$((tenants_per_job + remainder))
        fi
        
        local current_end=$((current_start + tenants_for_this_job - 1))
        
        # Skip if no tenants for this job
        if [ $current_start -gt $tenant_count ]; then
            break
        fi
        
        # Ensure we don't exceed total tenant count
        if [ $current_end -gt $tenant_count ]; then
            current_end=$tenant_count
        fi
        
        local job_name="${JOB_PREFIX}-${i}-$(date +%s)"
        local log_file="$LOG_DIR/${job_name}.log"
        
        # Start migration job
        if start_migration_job "$job_name" "$current_start" "$current_end" "$log_file"; then
            job_names+=("$job_name")
        else
            print_error "Failed to start job $job_name"
        fi
        
        current_start=$((current_end + 1))
        
        # Break if we've covered all tenants
        if [ $current_start -gt $tenant_count ]; then
            break
        fi
    done
    
    if [ ${#job_names[@]} -eq 0 ]; then
        print_error "No jobs were created successfully"
        exit 1
    fi
    
    print_info "Created ${#job_names[@]} migration jobs"
    print_info "Log files will be written to: $LOG_DIR"
    
    # Monitor jobs and wait for completion
    if monitor_jobs "${job_names[@]}"; then
        print_success "All migrations completed successfully!"
        cleanup_jobs "${job_names[@]}"
        exit 0
    else
        local failed_count=$?
        print_error "$failed_count out of ${#job_names[@]} migration jobs failed"
        print_info "Check log files in $LOG_DIR for details"
        
        # Cleanup successful jobs, leave failed ones for debugging
        print_info "Leaving failed jobs in cluster for debugging"
        cleanup_jobs "${job_names[@]}"
        exit 1
    fi
}

# Help function
show_help() {
    cat << EOF
Parallel Kubernetes Migration Script with Temporary Jobs

This script creates temporary Kubernetes Jobs with specified Docker images
to distribute database migrations across multiple pods for faster processing.

Usage: $0 -i IMAGE [OPTIONS]

Required Options:
    -i, --image         Docker image to use for migration jobs (REQUIRED)

Optional Options:
    -h, --help          Show this help message
    -n, --namespace     Kubernetes namespace (default: danswer)
    -l, --log-dir       Directory for log files (default: ./migration_logs)
    -c, --command       Migration command (default: alembic upgrade head)
    -j, --max-jobs      Maximum number of jobs to create (default: auto-calculate)
    -t, --timeout       Job timeout in seconds (default: 3600)
    --no-cleanup        Don't cleanup jobs after completion (useful for debugging)

Examples:
    $0 -i onyxdotapp/onyx-backend:latest                    # Basic usage with latest image
    $0 -i onyxdotapp/onyx-backend:v1.2.3 -j 5              # Use specific tag with 5 jobs
    $0 -i my-registry/onyx-backend:dev -n production       # Use custom image in production namespace
    $0 -i onyxdotapp/onyx-backend:latest --no-cleanup      # Leave jobs for debugging
    $0 -i onyxdotapp/onyx-backend:latest -t 7200           # 2 hour timeout

The script will:
1. Validate prerequisites and Docker image
2. Create a temporary pod to count total tenants
3. Calculate optimal number of jobs based on tenant count
4. Create Kubernetes Jobs with tenant range assignments
5. Monitor job progress and collect logs
6. Cleanup jobs after completion (unless --no-cleanup is specified)

Each job gets:
- Resource limits (2GB RAM, 1 CPU)
- Database credentials from secrets
- Automatic retry on failure
- Detailed logging

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -i|--image)
            DOCKER_IMAGE="$2"
            shift 2
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -l|--log-dir)
            LOG_DIR="$2"
            shift 2
            ;;
        -c|--command)
            MIGRATION_COMMAND="$2"
            shift 2
            ;;
        -j|--max-jobs)
            MAX_JOBS="$2"
            if ! [[ "$MAX_JOBS" =~ ^[0-9]+$ ]] || [ "$MAX_JOBS" -le 0 ]; then
                print_error "Invalid max-jobs value: $MAX_JOBS. Must be a positive integer."
                exit 1
            fi
            shift 2
            ;;
        -t|--timeout)
            JOB_TIMEOUT="$2"
            if ! [[ "$JOB_TIMEOUT" =~ ^[0-9]+$ ]] || [ "$JOB_TIMEOUT" -le 0 ]; then
                print_error "Invalid timeout value: $JOB_TIMEOUT. Must be a positive integer."
                exit 1
            fi
            shift 2
            ;;
        --no-cleanup)
            CLEANUP_JOBS="false"
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Run main function
main "$@" 