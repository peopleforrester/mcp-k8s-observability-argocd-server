#!/bin/bash
# ABOUTME: Script to set up a local Kind cluster with ArgoCD for testing
# ABOUTME: Creates cluster, installs ArgoCD, and outputs connection details

set -e

CLUSTER_NAME="${CLUSTER_NAME:-argocd-test}"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-./kubeconfig}"
K8S_VERSION="${K8S_VERSION:-v1.29.2}"

echo "Setting up Kind cluster for ArgoCD MCP testing..."
echo "Cluster name: $CLUSTER_NAME"
echo "Kubernetes version: $K8S_VERSION"
echo ""

# Check prerequisites
command -v kind >/dev/null 2>&1 || { echo "kind is required but not installed. Aborting."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required but not installed. Aborting."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker is required but not installed. Aborting."; exit 1; }

# Check if cluster already exists
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "Cluster '$CLUSTER_NAME' already exists."
    read -p "Delete and recreate? (y/N): " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "Deleting existing cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
    else
        echo "Using existing cluster."
        kubectl cluster-info --context "kind-${CLUSTER_NAME}" || exit 1
        exit 0
    fi
fi

# Create cluster
echo ""
echo "Creating Kind cluster..."
kind create cluster --name "$CLUSTER_NAME" --image "kindest/node:${K8S_VERSION}"

# Export kubeconfig
echo ""
echo "Exporting kubeconfig to $KUBECONFIG_PATH..."
kind get kubeconfig --name "$CLUSTER_NAME" > "$KUBECONFIG_PATH"
export KUBECONFIG="$KUBECONFIG_PATH"

# Install ArgoCD
echo ""
echo "Installing ArgoCD..."
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
echo ""
echo "Waiting for ArgoCD to be ready (this may take a few minutes)..."
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get admin password
echo ""
ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Output connection details
echo ""
echo "============================================="
echo "ArgoCD is ready!"
echo "============================================="
echo ""
echo "To access ArgoCD UI, run:"
echo "  kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "  Then open https://localhost:8080"
echo ""
echo "Credentials:"
echo "  Username: admin"
echo "  Password: $ARGOCD_PASSWORD"
echo ""
echo "Environment variables for MCP server:"
echo "  export ARGOCD_URL=https://localhost:8080"
echo "  export ARGOCD_TOKEN=\$(argocd account generate-token)"
echo "  export ARGOCD_INSECURE=true"
echo "  export KUBECONFIG=$KUBECONFIG_PATH"
echo ""
echo "Or generate API token with:"
echo "  kubectl -n argocd patch cm argocd-cm --type merge -p '{\"data\":{\"admin.enabled\":\"true\"}}'"
echo "  argocd login localhost:8080 --username admin --password $ARGOCD_PASSWORD --insecure"
echo "  argocd account generate-token"
echo ""
