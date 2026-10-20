from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

@pytest.fixture
def tmp_path():
    root=Path(__file__).resolve().parents[1]/'runtime/tests'
    root.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='eap2-',dir=root) as directory: yield Path(directory)
