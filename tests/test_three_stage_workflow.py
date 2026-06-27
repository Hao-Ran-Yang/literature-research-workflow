"""Compatibility stub for the split three-stage workflow tests.

The original monolithic test module has been split for CI-friendly execution:

- Fast/default: ``python -B -m unittest tests.test_three_stage_workflow_fast``
- Integration/manual: ``python -B -m unittest tests.integration_three_stage_workflow``
- Slow e2e/manual: ``python -B -m unittest tests.slow_three_stage_workflow``

This module intentionally defines no ``unittest.TestCase`` classes so
``unittest discover`` does not run the old long e2e suite by accident.
"""
