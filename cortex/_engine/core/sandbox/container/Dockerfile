FROM python:3.12-slim

# Security: run as unprivileged user
RUN useradd -r -m -s /bin/false sandbox

# Copy runner scripts
COPY agent_runner.py proxy_libraries.py /app/

# Remove unnecessary system utilities to reduce attack surface
RUN apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Workspace directory for host file bind mounts
# Output directory for files written by add_to_output_files()
RUN mkdir -p /workspace /output && chown sandbox:sandbox /workspace /output

USER sandbox
WORKDIR /app

ENTRYPOINT ["python", "-u", "agent_runner.py"]
