import logging
import random
import time
import sys

from flask import Flask, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import requests

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# ---------- Logging (structured JSON-ish, easy for Loki/Promtail) ----------
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"sre-demo-app","msg":"%(message)s"}',
)
log = logging.getLogger("sre-demo-app")

# ---------- Tracing ----------
resource = Resource.create({"service.name": "sre-demo-app"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="otel-collector.observability.svc.cluster.local:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("sre-demo-app")

# ---------- App ----------
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["endpoint"]
)
DOWNSTREAM_ERRORS = Counter(
    "downstream_call_errors_total", "Errors calling downstream service"
)


@app.route("/")
def root():
    return jsonify(service="sre-demo-app", status="ok")


@app.route("/healthz")
def healthz():
    return jsonify(status="healthy")


@app.route("/work")
def work():
    """Simulates variable-latency work with occasional slow tail and errors."""
    start = time.time()
    endpoint = "/work"

    with tracer.start_as_current_span("do_work") as span:
        # simulate variable processing time - mostly fast, occasional slow tail
        if random.random() < 0.05:
            delay = random.uniform(1.5, 3.0)  # slow tail (p99 territory)
            span.set_attribute("work.slow_path", True)
        else:
            delay = random.uniform(0.02, 0.2)
        time.sleep(delay)
        span.set_attribute("work.delay_ms", int(delay * 1000))

        # simulate occasional downstream failure (calls itself / internal endpoint)
        status_code = 200
        if random.random() < 0.08:
            status_code = 500
            DOWNSTREAM_ERRORS.inc()
            log.error("downstream dependency failed during /work request")
        else:
            log.info(f"processed /work request in {delay*1000:.1f}ms")

    duration = time.time() - start
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)
    REQUEST_COUNT.labels(method="GET", endpoint=endpoint, status=status_code).inc()

    if status_code == 500:
        return jsonify(error="downstream failure"), 500
    return jsonify(result="done", duration_ms=int(duration * 1000))


@app.route("/chain")
def chain():
    """Calls /work internally to demonstrate multi-span traces."""
    with tracer.start_as_current_span("chain_call"):
        try:
            r = requests.get("http://localhost:8080/work", timeout=5)
            log.info(f"chain call completed with status {r.status_code}")
            return jsonify(chain_result=r.status_code), r.status_code
        except Exception as e:
            log.error(f"chain call failed: {e}")
            return jsonify(error=str(e)), 500


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
