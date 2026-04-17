ARG BASE_IMAGE=__BASE_IMAGE__
FROM ${BASE_IMAGE}

COPY __PREP_SUBMODULE_PATH__/runtime/scripts/ /app/scripts/
COPY __PREP_SUBMODULE_PATH__/runtime/requirements.txt /app/requirements.txt
RUN chmod +x /app/scripts/pre-start.sh /app/scripts/apply_config.sh
RUN /opt/venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt

COPY config.yml /app/config.yml

CMD ["/app/scripts/pre-start.sh"]
