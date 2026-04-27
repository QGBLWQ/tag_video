from pathlib import Path

from video_tagging_assistant.bat_parser import group_case_tasks, parse_move_bat, parse_pull_bat


def test_parse_pull_bat_extracts_case_mapping(tmp_path: Path):
    bat_path = tmp_path / "pull.bat"
    bat_path.write_text(
        "\n".join(
            [
                "adb wait-for-device",
                r"adb pull /mnt/nvme/CapturedData/117 .\\case_A_0078_RK_raw_117",
                r'move "E:\\DV\\case_A_0078_RK_raw_117" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_RK_raw_117"',
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_pull_bat(bat_path)

    assert len(rows) == 1
    assert rows[0].case_id == "case_A_0078"
    assert rows[0].device_path == "/mnt/nvme/CapturedData/117"


def test_parse_move_bat_extracts_normal_and_night_rows(tmp_path: Path):
    bat_path = tmp_path / "move.bat"
    bat_path.write_text(
        "\n".join(
            [
                r'copy "E:\\DJI\\Nomal\\a.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_DJI_a.mp4"',
                r'copy "E:\\DJI\\Night\\b.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_night_DJI_b.mp4"',
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_move_bat(bat_path)

    assert [row.kind for row in rows] == ["normal", "night"]
    assert rows[1].case_id == "case_A_0078"


def test_group_case_tasks_merges_pull_and_copy_rows(tmp_path: Path):
    pull_path = tmp_path / "pull.bat"
    move_path = tmp_path / "move.bat"
    pull_path.write_text(
        r'adb pull /mnt/nvme/CapturedData/117 .\\case_A_0078_RK_raw_117' + "\n" +
        r'move "E:\\DV\\case_A_0078_RK_raw_117" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_RK_raw_117"',
        encoding="utf-8",
    )
    move_path.write_text(
        r'copy "E:\\DJI\\Night\\b.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_night_DJI_b.mp4"',
        encoding="utf-8",
    )

    tasks = group_case_tasks(pull_path, move_path, Path(r"\\10.10.10.164\rk3668_capture\OV50"), "20260427")

    assert len(tasks) == 1
    assert tasks[0].case_id == "case_A_0078"
    assert tasks[0].copy_tasks[0].kind == "night"
    assert tasks[0].server_case_dir == Path(r"\\10.10.10.164\rk3668_capture\OV50\20260427\case_A_0078")
