# BugsInPy detector image

This public Dockerfile packages the ground-truth-blind detector. Its build
context must contain clean Git archives at `archway/` and
`archway-benchmarks/`; the private runner assembles that context and records
both exact revisions plus the resulting immutable image ID.

The image entrypoint is `archway-bugsinpy-detect`, so the isolated invocation
arguments are simply:

```text
/input/detector-input.json /output/predictions.json
```

The pinned base image, exact runtime dependency, and revision-archived source
trees make the build inputs reviewable without transient wheel-build tooling.
Benchmark claims must additionally retain the build attestation,
image ID, detector manifest, execution attestation, and prediction artifact.
