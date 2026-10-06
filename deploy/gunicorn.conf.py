"""Single-server Flask deployment behind the local Nginx reverse proxy."""

bind = "127.0.0.1:8001"
# Order tools currently store the session ID in a process global. Keep each
# worker synchronous so concurrent requests cannot overwrite that session ID.
workers = 2
worker_class = "sync"
timeout = 120
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = False
daemon = False
forwarded_allow_ips = "127.0.0.1"
accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True
