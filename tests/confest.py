import sys
from pathlib import Path
import pytest

# Ensure the 'pipeline' module can be imported
sys.path.append(str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def mock_config_paths(monkeypatch, tmp_path):
    """
    Automatically redirects config.OUTPUTS_PATH to a temp directory
    for EVERY test. This guarantees isolation.
    """
    # Create a fake output directory in the temp folder
    fake_outputs = tmp_path / "outputs"
    fake_outputs.mkdir()

    # Monkeypatch the variable in the actual loaded module
    import pipeline.config
    monkeypatch.setattr(pipeline.config, "OUTPUTS_PATH", fake_outputs)

    return fake_outputs