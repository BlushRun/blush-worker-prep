ARG BASE_IMAGE=__BASE_IMAGE__
FROM ${BASE_IMAGE}

COPY runtime/scripts/ /app/scripts/
COPY runtime/requirements.txt /app/requirements.txt
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/pre-start.sh /app/scripts/apply_config.sh
RUN /opt/venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt

COPY submodules/__SLUG__/config.yml /app/config.yml

CMD ["/app/scripts/pre-start.sh"]
