from archway_benchmarks.types import Annotation, Location


def test_location_is_hashable_and_frozen():
    a = Location(file="main.py", line=2, col=5, kind="return", name="func1")
    b = Location(file="main.py", line=2, col=5, kind="return", name="func1")
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_distinct_locations_when_kind_or_name_differs():
    base = dict(file="main.py", line=2, col=5)
    a = Location(**base, kind="return", name="func1")
    b = Location(**base, kind="parameter", name="x", function="func1")
    assert a != b


def test_annotation_types_is_frozenset():
    loc = Location(file="m.py", line=1, col=0, kind="variable", name="x")
    ann = Annotation(location=loc, types=frozenset({"int", "str"}))
    assert isinstance(ann.types, frozenset)
