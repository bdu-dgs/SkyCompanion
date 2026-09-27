#!/usr/bin/env python3
"""Reuse the selected-target-only evaluator on reviewed street obstacles.

This deliberately does not compute full-scene precision or path occupancy.
"""
import evaluate_pole_local_regression as regression

regression.LABELS.clear()
regression.LABELS.update({
    'fence': {'fence'},
    'construction_barrier': {'construction_barrier', 'construction barrier'},
    'rock': {'rock', 'boulder'},
})

if __name__ == '__main__':
    regression.main()
