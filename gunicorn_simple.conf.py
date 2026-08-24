# Simple Gunicorn Configuration for Production
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8001"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1  # Dynamic based on CPU cores
worker_class = "sync"  # Use sync if gevent not available, change to "gevent" if installed
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
preload_app = True

# Worker timeout and keep-alive
timeout = 30
keepalive = 5

# Logging
accesslog = "logs/access.log"
errorlog = "logs/error.log"
loglevel = "info"

# Process naming
proc_name = "lotus-chatbot-api"

# Performance tuning
forwarded_allow_ips = "*"

# Monitoring hooks (simplified)
def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def pre_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)
