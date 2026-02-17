from __future__ import annotations

import json

from backend.app.evaluation.harness import EvaluationHarness


if __name__ == "__main__":
    report = EvaluationHarness().run()
    print(json.dumps(report, indent=2))
