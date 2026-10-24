from commitrocket.batching import (
    MIB,
    estimate_batch_count,
    plan_batches,
    select_batch,
)


def make_files(root, sizes):
    for name, size in sizes.items():
        (root / name).write_bytes(b"x" * size)
    return list(sizes)


def test_packs_small_files_up_to_limit(tmp_path):
    files = make_files(tmp_path, {"a": MIB, "b": MIB, "c": MIB})
    selected, deferred, total = select_batch(tmp_path, files, 2 * MIB, 6 * MIB)
    assert selected == ["a", "b"]
    assert deferred == []
    assert total == 2 * MIB


def test_large_file_goes_alone(tmp_path):
    files = make_files(tmp_path, {"small": MIB, "big": 3 * MIB})
    selected, _, total = select_batch(tmp_path, files, 2 * MIB, 6 * MIB)
    assert selected == ["big"]
    assert total == 3 * MIB


def test_oversized_file_is_deferred(tmp_path):
    files = make_files(tmp_path, {"huge": 7 * MIB, "small": MIB})
    selected, deferred, _ = select_batch(tmp_path, files, 2 * MIB, 6 * MIB)
    assert selected == ["small"]
    assert deferred == [("huge", 7 * MIB)]


def test_lfs_files_are_grouped_up_to_lfs_limit(tmp_path):
    files = make_files(tmp_path, {"a": 3 * MIB, "b": 3 * MIB, "c": 3 * MIB})
    selected, _, total = select_batch(
        tmp_path, files, 2 * MIB, 9 * MIB, frozenset(files), 7 * MIB
    )
    assert selected == ["a", "b"]
    assert total == 6 * MIB


def test_lfs_group_always_takes_one_file(tmp_path):
    files = make_files(tmp_path, {"a": 3 * MIB})
    selected, _, _ = select_batch(
        tmp_path, files, 2 * MIB, 9 * MIB, frozenset(files), MIB
    )
    assert selected == ["a"]


# The batch-type tests count in KiB so they don't write hundreds of MiB to disk.
K = 1024


def batches(tmp_path, sizes, batch_type, limit=100, max_=300):
    files = make_files(tmp_path, sizes)
    remaining = list(files)
    result = []
    while remaining:
        selected, _, _ = select_batch(
            tmp_path, remaining, limit * K, max_ * K, batch_type=batch_type
        )
        if not selected:
            break
        result.append(selected)
        remaining = [path for path in remaining if path not in selected]
    return result


SIZES = {"A": 60 * K, "B": 50 * K, "C": 30 * K, "D": 20 * K}


def test_deterministic_skips_files_that_do_not_fit(tmp_path):
    assert batches(tmp_path, SIZES, "deterministic") == [["A", "C"], ["B", "D"]]


def test_sequential_stops_at_first_file_that_does_not_fit(tmp_path):
    assert batches(tmp_path, SIZES, "sequential") == [["A"], ["B", "C", "D"]]


def test_soft_may_cross_the_limit(tmp_path):
    assert batches(tmp_path, SIZES, "soft") == [["A", "B"], ["C", "D"]]


def test_soft_respects_max_total(tmp_path):
    sizes = {"A": 60 * K, "B": 50 * K, "C": 30 * K}
    result = batches(tmp_path, sizes, "soft", limit=100, max_=100)
    assert result == [["A"], ["B", "C"]]


def test_in_order_types_keep_large_file_alone(tmp_path):
    sizes = {"big": 150 * K, "A": 10 * K}
    assert batches(tmp_path, sizes, "sequential") == [["big"], ["A"]]
    assert batches(tmp_path, sizes, "soft") == [["big"], ["A"]]


def test_plan_batches_matches_execution_and_reports_deferred(tmp_path):
    sizes = {**SIZES, "huge": 400 * K}
    files = make_files(tmp_path, sizes)
    plan, deferred = plan_batches(tmp_path, files, 100 * K, 300 * K)

    assert [paths for paths, _ in plan] == [["A", "C"], ["B", "D"]]
    assert [total for _, total in plan] == [90 * K, 70 * K]
    assert deferred == [("huge", 400 * K)]


def test_estimate_matches_selection(tmp_path):
    files = make_files(tmp_path, {"a": MIB, "b": MIB, "c": MIB, "big": 3 * MIB})
    assert estimate_batch_count(tmp_path, files, 2 * MIB, 6 * MIB) == 3
