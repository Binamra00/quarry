# pipeline/analyzer/specs.py
import json
from pathlib import Path
from typing import Dict, List
from .contracts import IRelevanceSpec


class JsonRelevanceSpec(IRelevanceSpec):
    """
    Concrete implementation of the Specification Pattern.
    Loads the Relevance Matrix from a JSON file and strictly enforces it.
    """

    def __init__(self, config_path: Path):
        self.rules = self._load_json(config_path)

    def _load_json(self, path: Path) -> Dict[str, List[str]]:
        """
        Loads and validates the JSON configuration.
        """
        if not path.exists():
            raise FileNotFoundError(f"Relevance matrix not found at: {path}")

        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return data
        except Exception as e:
            raise RuntimeError(f"Failed to load relevance matrix: {e}")

    def is_relevant(self, ref_type: str, rule: str) -> bool:
        """
        The Filter Logic:
        Returns True ONLY if the Refactoring Type is explicitly allowed
        to fix the given Smell Rule in the JSON configuration.
        """
        # Default to empty list if ref_type is not in the matrix (Implicit Reject)
        allowed_rules = self.rules.get(ref_type, [])
        return rule in allowed_rules