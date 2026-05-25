from archway_benchmarks.cli import main


def test_list_command_runs(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "no suites" in out
