FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ARG ARCHWAY_ENGINE_SHA
ARG ARCHWAY_BENCHMARKS_SHA

LABEL org.opencontainers.image.title="Archway BugsInPy detector" \
      org.opencontainers.image.revision.archway="${ARCHWAY_ENGINE_SHA}" \
      org.opencontainers.image.revision.benchmarks="${ARCHWAY_BENCHMARKS_SHA}"

COPY archway /src/archway
COPY archway-benchmarks /src/archway-benchmarks

# The detector uses the reduced-product analysis path, whose only external
# runtime dependency is PyYAML. Install both local projects without resolving
# Archway's service/successor extras into this deliberately small image.
RUN test -n "${ARCHWAY_ENGINE_SHA}" \
    && test -n "${ARCHWAY_BENCHMARKS_SHA}" \
    && python -m pip install --no-cache-dir 'PyYAML==6.0.3' \
    && python -m pip install --no-cache-dir --no-deps /src/archway /src/archway-benchmarks \
    && rm -rf /src

ENTRYPOINT ["archway-bugsinpy-detect"]
