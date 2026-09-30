"""Build accountable rootless scoring images; never change analysis predictions.

Uses pinned prebuilt CPython images instead of upstream's moving pyenv branches.
Corpus version families and install hooks remain explicit inputs. Failed builds
are retained outcomes, not successful empty scores. Each invocation is a fresh
attempt directory; completed images are shared by both engine revisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


RECIPE = '''ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ENV UV_PYTHON_DOWNLOADS=never
COPY uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git curl pkg-config libssl-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*
COPY scorer /typybench
WORKDIR /typybench
RUN uv pip install --system .
ARG REPO
COPY --from=corpus . /typybenchdata/${REPO}
RUN if [ -f "/typybenchdata/$REPO/build.sh" ]; then cd "/typybenchdata/$REPO/original_repo" && sh "/typybenchdata/$REPO/build.sh"; fi
RUN if [ -f "/typybenchdata/$REPO/envs" ]; then . "/typybenchdata/$REPO/envs"; fi; \
    if [ -f "/typybenchdata/$REPO/requirements.txt" ]; then \
      cd "/typybenchdata/$REPO/original_repo" && uv pip install --system -r "/typybenchdata/$REPO/requirements.txt"; \
    elif [ -f "/typybenchdata/$REPO/custom_install.sh" ]; then \
      cd "/typybenchdata/$REPO/original_repo" && sh "/typybenchdata/$REPO/custom_install.sh"; \
    elif [ -f "/typybenchdata/$REPO/original_repo/setup.py" ] || [ -f "/typybenchdata/$REPO/original_repo/pyproject.toml" ]; then \
      uv pip install --system -e "/typybenchdata/$REPO/original_repo"; \
    fi
RUN python --version > /python-version.txt && uv pip freeze --system > /dependencies.txt
'''


def write_json(path: Path, value: object) -> None:
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def python_family(corpus: Path) -> str:
    version = (corpus / '.python-version')
    if not version.exists():
        return '3.12'
    requested = version.read_text().strip()
    if requested not in {'3.10-dev', '3.11-dev', '3.12-dev'}:
        raise ValueError(f'unsupported corpus Python requirement: {requested}')
    return requested.removesuffix('-dev')


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('analysis_manifest', type=Path)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('scorer', type=Path)
    parser.add_argument('bases', type=Path, help='JSON: Python family -> immutable image reference')
    parser.add_argument('uv', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--repo', action='append', help='explicit subset for a separate retry attempt')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    runtime = json.loads(subprocess.check_output(['podman', 'info', '--format', 'json'], text=True))
    if not runtime['host']['security']['rootless']:
        raise RuntimeError('rootless Podman required')
    bases = json.loads(args.bases.read_text())
    if any('@sha256:' not in ref for ref in bases.values()):
        raise ValueError('base images must be digest pinned')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    context = args.output / 'context'
    context.mkdir()
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=args.scorer).split(b'\0')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=args.scorer):
        raise RuntimeError('scorer checkout must be clean')
    for raw in files:
        if not raw:
            continue
        name = os.fsdecode(raw)
        dest = context / 'scorer' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.scorer / name, dest)
    shutil.copy2(args.uv, context / 'uv')
    (context / 'Dockerfile').write_text(RECIPE)
    repos = sorted(json.loads(args.analysis_manifest.read_text())['repositories'])
    if args.repo:
        unknown = set(args.repo) - set(repos)
        if unknown:
            raise ValueError(f'repositories absent from analysis selection: {sorted(unknown)}')
        repos = sorted(set(args.repo))
    manifest = {
        'schema': 'archway.typybench-image-builds.v1', 'status': 'running',
        'scorer_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.scorer, text=True).strip(),
        'runtime': runtime, 'bases': bases, 'timeout_seconds': args.timeout,
        'recipe_sha256': hashlib.sha256(RECIPE.encode()).hexdigest(),
        'uv_sha256': hashlib.sha256(args.uv.read_bytes()).hexdigest(),
        'analysis_manifest_sha256': hashlib.sha256(args.analysis_manifest.read_bytes()).hexdigest(),
        'selected': repos, 'repositories': {},
        'limitation': 'New prebuilt Python environments, not reproduction of historical development-branch images',
    }
    images = {}
    write_json(args.output / 'manifest.json', manifest)
    for index, repo in enumerate(repos, 1):
        if Path(repo).name != repo or repo in {'.', '..'}:
            raise ValueError('invalid repository name')
        evidence = args.output / repo
        evidence.mkdir()
        record = {'status': 'running', 'started_unix': time.time()}
        manifest['repositories'][repo] = record
        write_json(args.output / 'manifest.json', manifest)
        print(f'BUILD start {index}/{len(repos)} {repo}', flush=True)
        try:
            corpus = (args.corpus / repo).resolve()
            family = python_family(corpus)
            record['python_family'] = family
            command = ['podman', 'build', '--rm', '--force-rm', '--memory=8g',
                       '--iidfile', str(evidence / 'image.id'),
                       '--build-arg', f'BASE_IMAGE={bases[family]}',
                       '--build-arg', f'REPO={repo}',
                       '--build-context', f'corpus={corpus}', str(context)]
            write_json(evidence / 'command.json', command)
            with (evidence / 'build.log').open('w') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=args.timeout)
                except BaseException:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
            record['returncode'] = code
            if code:
                raise RuntimeError(f'build exited {code}')
            image = (evidence / 'image.id').read_text().strip()
            inspection = json.loads(subprocess.check_output(['podman', 'image', 'inspect', image], text=True))
            write_json(evidence / 'image.json', inspection)
            environment = subprocess.check_output([
                'podman', 'run', '--rm', '--network=none', '--cap-drop=all',
                '--security-opt=no-new-privileges', '--entrypoint', 'cat', image,
                '/python-version.txt', '/dependencies.txt'], text=True, timeout=30)
            (evidence / 'environment.txt').write_text(environment)
            images[repo] = image
            record.update(status='complete', image=image)
        except subprocess.TimeoutExpired as error:
            record.update(status='timed_out', error=str(error))
        except Exception as error:
            record.update(status='failed', error=f'{type(error).__name__}: {error}')
        record['finished_unix'] = time.time()
        write_json(args.output / 'manifest.json', manifest)
        write_json(args.output / 'images.json', images)
        print(f'BUILD {record["status"]} {repo}', flush=True)
    manifest['status'] = 'complete' if len(images) == len(repos) else 'finished_with_unavailable_images'
    write_json(args.output / 'manifest.json', manifest)


if __name__ == '__main__':
    main()
