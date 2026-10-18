import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from mas.config import Config  # noqa: E402

RACINE = Path(__file__).parents[1]


@pytest.fixture(scope="session")
def config() -> Config:
    return Config.model_validate(yaml.safe_load((RACINE / "config.example.yaml").read_text()))


@pytest.fixture(scope="session")
def releves(tmp_path_factory):
    from mas.synthetique import generer_jeu

    return generer_jeu(tmp_path_factory.mktemp("synth"), 4, graine_depart=100)


@pytest.fixture(scope="session")
def jeu_anonymise(config, releves):
    from mas.optimisation.donnees import _anonymiser_releve

    return [_anonymiser_releve(config, p) for p in releves]
