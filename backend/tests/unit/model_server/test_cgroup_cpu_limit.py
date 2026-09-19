from pathlib import Path

from model_server.utils import get_cgroup_cpu_limit


def _missing(tmp_path: Path) -> Path:
    return tmp_path / "does_not_exist"


def test_cgroup_v2_quota(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"
    v2.write_text("800000 100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=v2,
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        == 8
    )


def test_cgroup_v2_unlimited(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"
    v2.write_text("max 100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=v2,
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        is None
    )


def test_cgroup_v2_floors_fractional_quota(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"
    # 7.5 cores -> floors to 7 so the cap never exceeds the quota (round would give 8).
    v2.write_text("750000 100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=v2,
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        == 7
    )


def test_cgroup_v2_sub_core_floors_to_one(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"
    # 0.1 cores would round to 0; we floor to 1 so torch always gets a usable count.
    v2.write_text("10000 100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=v2,
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        == 1
    )


def test_cgroup_v2_max_does_not_fall_through_to_v1(tmp_path: Path) -> None:
    # When v2 reports unlimited, a populated v1 quota (hybrid host) must be ignored:
    # the v2 hierarchy is authoritative.
    v2 = tmp_path / "cpu.max"
    v2.write_text("max 100000")
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("400000")
    period.write_text("100000")
    assert (
        get_cgroup_cpu_limit(v2_cpu_max=v2, v1_cpu_quota=quota, v1_cpu_period=period)
        is None
    )


def test_cgroup_v2_malformed_does_not_fall_through_to_v1(tmp_path: Path) -> None:
    # A present-but-unparseable v2 file is still authoritative: we must not consult v1.
    v2 = tmp_path / "cpu.max"
    v2.write_text("garbage")
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("400000")
    period.write_text("100000")
    assert (
        get_cgroup_cpu_limit(v2_cpu_max=v2, v1_cpu_quota=quota, v1_cpu_period=period)
        is None
    )


def test_cgroup_v1_fallback(tmp_path: Path) -> None:
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("400000")
    period.write_text("100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=_missing(tmp_path),
            v1_cpu_quota=quota,
            v1_cpu_period=period,
        )
        == 4
    )


def test_cgroup_v1_unlimited(tmp_path: Path) -> None:
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("-1")
    period.write_text("100000")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=_missing(tmp_path),
            v1_cpu_quota=quota,
            v1_cpu_period=period,
        )
        is None
    )


def test_no_cgroup_files(tmp_path: Path) -> None:
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=_missing(tmp_path),
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        is None
    )


def test_malformed_contents(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"
    v2.write_text("garbage")
    assert (
        get_cgroup_cpu_limit(
            v2_cpu_max=v2,
            v1_cpu_quota=_missing(tmp_path),
            v1_cpu_period=_missing(tmp_path),
        )
        is None
    )
