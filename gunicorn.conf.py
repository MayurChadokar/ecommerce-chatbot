# Gunicorn Configuration for Flask Application (WSGI)
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8001"
backlog = 2048

# Worker processes - optimized for Flask
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"  # Use sync workers for Flask (WSGI)
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
preload = True  # Correct parameter name

# Timeouts
timeout = 30
keepalive = 5
graceful_timeout = 30

# Logging
accesslog = "logs/access.log"
errorlog = "logs/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "lotus-flask-api"

# Server mechanics
daemon = False
pidfile = "logs/gunicorn.pid"
user = None
group = None

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Performance tuning for Flask
worker_tmp_dir = "/dev/shm" if os.path.exists("/dev/shm") else None
forwarded_allow_ips = "*"

# Monitoring hooks
def when_ready(server):
    server.log.info("Flask server is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_worker_init(worker):
    worker.log.info("Worker initialized (pid: %s)", worker.pid)

def worker_abort(worker):
    worker.log.info("Worker received SIGABRT signal")
