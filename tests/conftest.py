import pytest

from gatekeeper.settings import get_settings


@pytest.fixture(scope="session")
def skills_dir():
    return get_settings().skills_path
