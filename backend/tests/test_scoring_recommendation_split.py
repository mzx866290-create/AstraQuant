from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCORING_PATH = ROOT / "backend/services/analysis_service/api/v1/scoring.py"
RECOMMENDATION_ENGINE_PATH = ROOT / "backend/services/analysis_service/engine/recommendation_engine.py"

RECOMMENDATION_HELPERS = {
    "_empty_recommendations_result",
    "_mark_fallback_recommendation",
    "_evaluate_candidates_parallel",
    "_load_recommendation_candidates",
    "_fallback_recommendation_candidates",
    "_evaluate_daily_candidate",
    "_score_daily_candidate",
    "_build_score_breakdown",
    "is_valid_score_number",
    "_valid_mv",
    "_daily_rating",
}


def _defined_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


class ScoringRecommendationSplitTests(unittest.TestCase):
    def test_scoring_api_layer_stays_thin_after_recommendation_split(self) -> None:
        scoring_lines = SCORING_PATH.read_text(encoding="utf-8").splitlines()

        self.assertLess(len(scoring_lines), 1050)
        self.assertFalse(RECOMMENDATION_HELPERS & _defined_functions(SCORING_PATH))

    def test_recommendation_logic_lives_in_engine_module(self) -> None:
        self.assertLessEqual(RECOMMENDATION_HELPERS, _defined_functions(RECOMMENDATION_ENGINE_PATH))


if __name__ == "__main__":
    unittest.main()
