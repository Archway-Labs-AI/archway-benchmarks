FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ARG ARCHWAY_ENGINE_SHA
ARG ARCHWAY_BENCHMARKS_SHA

LABEL org.opencontainers.image.title="Archway BugsInPy detector" \
      org.opencontainers.image.revision.archway="${ARCHWAY_ENGINE_SHA}" \
      org.opencontainers.image.revision.benchmarks="${ARCHWAY_BENCHMARKS_SHA}"

COPY archway /opt/archway
COPY archway-benchmarks /opt/archway-benchmarks

# The detector uses the reduced-product analysis path, whose only external
# runtime dependency is PyYAML. Run the exact archived sources directly: a
# wheel build would introduce transient, separately resolved build tooling.
RUN test -n "${ARCHWAY_ENGINE_SHA}" \
    && test -n "${ARCHWAY_BENCHMARKS_SHA}" \
    && python -m pip install --no-cache-dir 'PyYAML==6.0.3'

ENV PYTHONPATH="/opt/archway:/opt/archway-benchmarks/src"
ENTRYPOINT ["python", "-m", "archway_benchmarks.bugsinpy_detector"]
