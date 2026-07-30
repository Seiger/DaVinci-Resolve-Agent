"""Platform path tests."""

from pathlib import Path, PureWindowsPath

from agent.paths import config_directory, plans_directory, runtime_directory


def test_runtime_paths_do_not_contain_a_hardcoded_user_name() -> None:
    first_environment = {
        "APPDATA": r"C:\Users\first-user\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\first-user\AppData\Local",
    }
    second_environment = {
        "APPDATA": r"D:\Profiles\second-user\Roaming",
        "LOCALAPPDATA": r"D:\Profiles\second-user\Local",
    }

    first_runtime = runtime_directory(first_environment)
    second_runtime = runtime_directory(second_environment)

    assert first_runtime != second_runtime
    assert PureWindowsPath(str(first_runtime)).parts[-2:] == (
        "DaVinciResolveAgent",
        "runtime",
    )
    assert PureWindowsPath(str(second_runtime)).parts[-2:] == (
        "DaVinciResolveAgent",
        "runtime",
    )
    assert config_directory(first_environment) == (
        Path(first_environment["APPDATA"]) / "DaVinciResolveAgent"
    )
    assert plans_directory(first_environment) == first_runtime / "plans"
