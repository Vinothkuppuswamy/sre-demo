#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${1:-kind}"

echo "==> Checking kind cluster '${CLUSTER_NAME}' exists..."
if ! kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "Cluster '${CLUSTER_NAME}' not found. Create it first with:"
  echo "  kind create cluster --name ${CLUSTER_NAME}"
  exit 1
fi

kubectl config use-context "kind-${CLUSTER_NAME}"

echo "==> Building app image..."
docker build -t sre-demo-app:latest ./app

echo "==> Loading image into kind cluster..."
kind load docker-image sre-demo-app:latest --name "${CLUSTER_NAME}"

echo "==> Applying namespaces..."
kubectl apply -f k8s/app.yaml --dry-run=client -o yaml | head -1 >/dev/null # no-op sanity
kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace demo-app --dry-run=client -o yaml | kubectl apply -f -

echo "==> Deploying observability stack (Prometheus, Loki, Tempo, OTel Collector, Grafana)..."
kubectl apply -f k8s/prometheus.yaml
kubectl apply -f k8s/loki.yaml
kubectl apply -f k8s/tempo.yaml
kubectl apply -f k8s/otel-collector.yaml
kubectl apply -f k8s/grafana-dashboards-cm.yaml
kubectl apply -f k8s/grafana.yaml

echo "==> Deploying demo app + load generator..."
kubectl apply -f k8s/app.yaml

echo "==> Waiting for rollouts..."
kubectl -n observability rollout status deployment/prometheus --timeout=120s
kubectl -n observability rollout status deployment/loki --timeout=120s
kubectl -n observability rollout status deployment/tempo --timeout=120s
kubectl -n observability rollout status deployment/otel-collector --timeout=120s
kubectl -n observability rollout status deployment/grafana --timeout=120s
kubectl -n demo-app rollout status deployment/sre-demo-app --timeout=120s
kubectl -n demo-app rollout status deployment/load-generator --timeout=120s

echo ""
echo "================================================================"
echo " All set! Access Grafana with:"
echo ""
echo "   kubectl -n observability port-forward svc/grafana 3000:3000"
echo ""
echo " Then open http://localhost:3000 (anonymous admin access enabled)"
echo " A pre-built 'SRE Golden Signals' dashboard is under the SRE folder."
echo ""
echo " Load is already being generated against /work and /chain."
echo " To hit the app manually:"
echo "   kubectl -n demo-app port-forward svc/sre-demo-app 9090:8080"
echo "   curl localhost:9090/work"
echo "   curl localhost:9090/chain"
echo "================================================================"
