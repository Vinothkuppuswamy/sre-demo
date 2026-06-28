# SRE Observability Demo (Traces + Logs + Metrics) on kind

A minimal but complete "three pillars of observability" stack you can run
locally to practice SRE techniques: golden signals, SLOs, alerting,
trace-log-metric correlation, and debugging under synthetic load/failure.

## What's in here

| Component        | Role                                           |
|-------------------|------------------------------------------------|
| `sre-demo-app`    | Flask app exposing `/work` and `/chain`, emits metrics (Prometheus client), logs (stdout, JSON-ish), and traces (OTel SDK) |
| `load-generator`  | Busybox loop hitting the app continuously so dashboards have live data |
| Prometheus        | Scrapes app + OTel Collector span-metrics      |
| Loki + Promtail   | Collects and stores pod logs                   |
| Tempo             | Stores traces (receives via OTel Collector)    |
| OTel Collector    | Receives OTLP traces from app, forwards to Tempo, derives RED metrics via `spanmetrics` connector |
| Grafana           | Single pane of glass — Prometheus/Loki/Tempo datasources pre-wired with trace↔log↔metric correlation |

```
sre-demo-app --(OTLP gRPC traces)--> otel-collector --> tempo
     |                                     |
     | (scraped /metrics)                  +--(spanmetrics)--> prometheus
     v                                                              ^
 prometheus  <----------------------------------------------------- |
     |
     v
  grafana <---- loki <---- promtail (tails pod logs)
```

## Prerequisites

- Docker Desktop running, with a kind cluster already created
  (if not: `kind create cluster --name kind`)
- `kubectl` and `kind` CLIs on your PATH
- ~1.5 vCPU / 2GB RAM free for the stack (it's deliberately lightweight)

## Quick start

```bash
cd sre-demo
chmod +x setup.sh
./setup.sh kind          # pass your cluster name if not "kind"
```

This builds the app image, loads it into kind (no registry needed),
applies all manifests, and waits for rollouts.

Then:

```bash
kubectl -n observability port-forward svc/grafana 3000:3000
```

Open **http://localhost:3000** — anonymous admin access is enabled, no login
needed. Go to **Dashboards → SRE → SRE Golden Signals**.

## Generating traffic manually

The load generator already runs constantly, but if you want hands-on control:

```bash
kubectl -n demo-app port-forward svc/sre-demo-app 8080:8080
curl localhost:8080/work     # ~8% chance of 500, ~5% chance of slow tail
curl localhost:8080/chain    # multi-span trace (chain -> work)
```

## SRE exercises to practice

1. **Golden signals**: Watch the dashboard. Identify the baseline error rate
   (~8%) and p99 latency tail (~5%) just from the panels.
2. **Trace → log → metric correlation**: In Grafana, go to **Explore**,
   query Tempo, pick a trace with an error, click into its logs via the
   trace-to-logs link, then check the metric spike at that timestamp.
3. **Define an SLO**: e.g. "99% of `/work` requests complete in < 1s over a
   rolling 30m window." Write the PromQL for the SLI, and calculate error
   budget burn.
4. **Write an alert rule**: Add a Prometheus alerting rule for error rate
   > 10% over 5m, or p99 latency > 2s. (Not pre-built — good exercise to add
   `k8s/alerting-rules.yaml` and mount it into the Prometheus config.)
5. **Break it on purpose**: Scale `load-generator` up
   (`kubectl -n demo-app scale deploy/load-generator --replicas=5`) and watch
   saturation/latency change. Practice a "what changed" RCA workflow using
   only the dashboards.
6. **Log-based debugging**: Use LogQL in Grafana (`{namespace="demo-app"} |= "error"`)
   to find failures, then pivot to the trace ID embedded in the log line.

## Tearing down

```bash
kubectl delete namespace demo-app observability
```

## Notes / things you may want to extend

- Retention is intentionally short (Prometheus 6h, Tempo/Loki similar) to
  keep disk usage low on a laptop-grade kind cluster.
- No persistent volumes are used — everything is ephemeral `emptyDir`/container
  filesystem. Fine for a learning sandbox; add PVCs if you want data to
  survive pod restarts.
- `imagePullPolicy: Never` is used for the app because we load the image
  directly into kind's node — no registry needed for local iteration.
- If you want real CPU/memory saturation panels, install metrics-server in
  kind (not included here, since kind doesn't ship it by default).
