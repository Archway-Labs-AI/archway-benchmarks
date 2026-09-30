import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location('compare_scores', Path(__file__).parents[1] / 'scripts/typybench_compare_scores.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_run(root, *, failed=False, expected='int', image='a', status='complete'):
    root.mkdir()
    records = {}
    for repo in ('paired', 'one-sided'):
        if failed and repo == 'one-sided':
            records[repo] = {'status': 'failed', 'error': 'timeout'}
            continue
        records[repo] = {'status': 'complete', 'score': {
            'total_vars': 3, 'overall_score_exact': 0.3333,
            'overall_score': 0.3333, 'missing_ratio': 0.6667,
        }}
        rows = [{'key': str(i), 'expected': expected, 'predicted': expected if i == 0 else None,
                 'exact': int(i == 0), 'similarity': int(i == 0), 'missing': i != 0} for i in range(3)]
        path = root / 'predictions' / repo / f'{repo}_scored_keys.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'keys': rows, 'count': 3, 'missing_count': 2, 'type_evidence_complete': True}))
    manifest = {'run_status': status, 'selection': {'eligible_repositories': ['paired', 'one-sided']},
                'runtime': {'images': {'paired': image, 'one-sided': image}}, 'repositories': records}
    (root / 'score-manifest.json').write_text(json.dumps(manifest))


def test_common_denominator_excludes_one_sided_failure_and_uses_unrounded_keys(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    write_run(a)
    write_run(b, failed=True)
    result = MODULE.compare(a, b)
    assert result['paired_repositories'] == ['paired']
    assert result['unpaired_repositories'] == ['one-sided']
    assert result['common_denominator_totals']['current'] == {
        'denominator': 3, 'exact_numerator': 1, 'similarity_sum': 1.0, 'missing_count': 2,
    }
    assert result['repositories']['one-sided']['current']['counts']['denominator'] == 3


@pytest.mark.parametrize('override', [{'expected': 'str'}, {'image': 'different'}])
def test_different_reference_or_environment_cannot_form_a_pair(tmp_path, override):
    a, b = tmp_path / 'a', tmp_path / 'b'
    write_run(a)
    write_run(b, **override)
    result = MODULE.compare(a, b)
    assert result['paired_repositories'] == []
    assert result['common_denominator_totals']['current']['denominator'] == 0


def test_live_pass_requires_explicit_interim_mode(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    write_run(a, status='running')
    write_run(b)
    with pytest.raises(ValueError, match='terminal'):
        MODULE.compare(a, b)
    assert MODULE.compare(a, b, allow_running=True)['terminal'] is False


def test_corrupt_key_evidence_cannot_support_a_score(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    write_run(a)
    write_run(b)
    path = a / 'predictions/paired/paired_scored_keys.json'
    data = json.loads(path.read_text())
    data['keys'][0]['exact'] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='differs from rounded'):
        MODULE.compare(a, b)
