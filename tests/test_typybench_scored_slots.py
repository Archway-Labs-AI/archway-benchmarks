from archway_benchmarks.typybench_scored_slots import (
    ScoredSlotKind,
    scored_slots,
)


def test_manifest_tracks_multiline_nested_and_async_signature_slots() -> None:
    slots = scored_slots(
        "class Model:\n"
        "    def convert(\n"
        "        self, value, /, *, flag=False, **options\n"
        "    ):\n"
        "        def normalize(item):\n"
        "            return item\n"
        "        return normalize(value)\n"
        "\n"
        "async def fetch(url):\n"
        "    return url\n"
    )

    assert {
        (item.kind, item.qualified_callable, item.name, item.definition_line)
        for item in slots
    } == {
        (ScoredSlotKind.PARAMETER, "Model.convert", "self", 2),
        (ScoredSlotKind.PARAMETER, "Model.convert", "value", 2),
        (ScoredSlotKind.PARAMETER, "Model.convert", "flag", 2),
        (ScoredSlotKind.PARAMETER, "Model.convert", "options", 2),
        (ScoredSlotKind.RETURN, "Model.convert", "Model.convert", 2),
        (ScoredSlotKind.PARAMETER, "Model.convert.normalize", "item", 5),
        (ScoredSlotKind.RETURN, "Model.convert.normalize", "Model.convert.normalize", 5),
        (ScoredSlotKind.PARAMETER, "fetch", "url", 9),
        (ScoredSlotKind.RETURN, "fetch", "fetch", 9),
    }


def test_manifest_excludes_local_module_and_class_assignments() -> None:
    slots = scored_slots(
        "module_value = 1\n"
        "class Model:\n"
        "    class_value = 2\n"
        "    def method(self):\n"
        "        local_value = 3\n"
        "        return local_value\n"
    )

    assert {item.role for item in slots} == {"param:self", "return"}
