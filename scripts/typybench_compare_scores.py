"""Compare retained TypyBench key evidence on an explicit common denominator."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


TERMINAL = {'complete', 'finished_with_incomplete_repositories', 'no_eligible_repositories'}


def read_json(path: Path) -> tuple[dict, str]:
    data = path.read_bytes()
    return json.loads(data), hashlib.sha256(data).hexdigest()


def key_evidence(root: Path, repo: str, record: dict) -> dict:
    path = root / 'predictions' / repo / f'{repo}_scored_keys.json'
    data, digest = read_json(path)
    rows = data['keys']
    keys = {row['key']: row for row in rows}
    if len(keys) != len(rows) or len(rows) != data['count'] or len(rows) != record['score']['total_vars']:
        raise ValueError(f'{repo}: inconsistent or duplicate scored keys')
    for row in rows:
        if (row['exact'] not in (0, 1) or not isinstance(row['missing'], bool)
                or not isinstance(row['similarity'], (int, float))
                or not math.isfinite(row['similarity']) or not 0 <= row['similarity'] <= 1):
            raise ValueError(f'{repo}: invalid key metrics')
    counts = {
        'denominator': len(rows),
        'exact_numerator': sum(row['exact'] for row in rows),
        'similarity_sum': math.fsum(row['similarity'] for row in rows),
        'missing_count': sum(row['missing'] for row in rows),
    }
    if counts['missing_count'] != data['missing_count']:
        raise ValueError(f'{repo}: missing count differs from key evidence')
    for numerator, metric in (
        ('exact_numerator', 'overall_score_exact'),
        ('similarity_sum', 'overall_score'), ('missing_count', 'missing_ratio'),
    ):
        if rows and not math.isclose(counts[numerator] / len(rows), record['score'][metric], abs_tol=0.000051):
            raise ValueError(f'{repo}: key evidence differs from rounded {metric}')
    return {'counts': counts, 'sha256': digest, 'keys': keys,
            'type_evidence_complete': data.get('type_evidence_complete', False)}


def compare(current: Path, comparison: Path, *, allow_running: bool = False) -> dict:
    manifests = {}
    hashes = {}
    for name, root in (('current', current), ('comparison', comparison)):
        manifests[name], hashes[name] = read_json(root / 'score-manifest.json')
    terminal = all(m.get('run_status') in TERMINAL for m in manifests.values())
    if not terminal and not allow_running:
        raise ValueError('both scoring passes must be terminal, or explicitly request an interim observation')
    selected = {name: set(m['selection']['eligible_repositories']) for name, m in manifests.items()}
    if selected['current'] != selected['comparison']:
        raise ValueError('scoring selections differ')
    rows = {}
    totals = {name: {'denominator': 0, 'exact_numerator': 0, 'similarity_sum': 0.0, 'missing_count': 0}
              for name in manifests}
    paired = []
    for repo in sorted(selected['current']):
        records = {name: m['repositories'].get(repo, {'status': 'not_attempted'}) for name, m in manifests.items()}
        row = {'outcomes': {name: {'status': record['status'], 'error': record.get('error'), 'reason': record.get('reason')}
                            for name, record in records.items()}}
        rows[repo] = row
        evidence = {}
        for name, root in (('current', current), ('comparison', comparison)):
            if records[name]['status'] == 'complete':
                evidence[name] = key_evidence(root, repo, records[name])
                row[name] = {k: v for k, v in evidence[name].items() if k != 'keys'}
        if len(evidence) != 2:
            row['paired'] = False
            continue
        a, b = evidence['current'], evidence['comparison']
        same_keys = a['keys'].keys() == b['keys'].keys()
        same_expected = same_keys and all(a['keys'][key]['expected'] == b['keys'][key]['expected'] for key in a['keys'])
        images = [m.get('runtime', {}).get('images', {}).get(repo) for m in manifests.values()]
        complete_types = a['type_evidence_complete'] and b['type_evidence_complete']
        row['paired'] = same_expected and complete_types and images[0] is not None and images[0] == images[1]
        if not row['paired']:
            row['pairing_failure'] = {'same_keys': same_keys, 'same_expected_types': same_expected,
                                      'complete_type_evidence': complete_types, 'images': images}
            continue
        paired.append(repo)
        row['exact_delta'] = a['counts']['exact_numerator'] - b['counts']['exact_numerator']
        row['changed_keys'] = [key for key in sorted(a['keys']) if any(
            a['keys'][key][field] != b['keys'][key][field]
            for field in ('exact', 'similarity', 'missing', 'predicted'))]
        for name in totals:
            for field in totals[name]:
                totals[name][field] += evidence[name]['counts'][field]
    return {
        'schema': 'archway.typybench-paired-key-comparison.v1',
        'terminal': terminal, 'manifest_sha256': hashes,
        'selected_repositories': len(rows), 'paired_repositories': paired,
        'unpaired_repositories': [repo for repo in rows if repo not in paired],
        'common_denominator_totals': totals, 'repositories': rows,
        'limitation': 'Totals cover only successful pairs with equal reference keys/types and the same image; unavailable cases are not scored zeros',
    }


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('current', type=Path)
    parser.add_argument('comparison', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--allow-running', action='store_true')
    args = parser.parse_args()
    result = compare(args.current, args.comparison, allow_running=args.allow_running)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
