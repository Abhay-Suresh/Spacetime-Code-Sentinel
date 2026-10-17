# Spacetime Sentinel: Scoring Criteria

## Measurements
The game records:
- **Fidelity (`F`):** estimated by averaging expectation values of sampled stabilizers of the ideal Clifford payload, using shots that pass all checks.
- **Kept-shot fraction (`K`):** fraction of raw measurement shots passing every check.
- **Check cost:** ancilla count, two-qubit-gate count, and circuit depth.
- **Fault exposure:** summary of uncovered Pauli fault types and their distribution across data qubits.

The implementation uses `S_SHOTS = 1000` in its scoring objective. Main-game fidelity is an estimate, not an exact state fidelity.

## Error objective
The code uses:

\\[
E(F,K) = (1-F) + \\frac{1}{\\sqrt{S K}},
\\]

where `S = 1000` and `K` is the kept-shot fraction. The first term penalizes infidelity; the second penalizes statistical uncertainty from having fewer accepted shots. If `K = 0`, error is infinite.

This captures the central trade-off: more checks may raise fidelity but reject enough shots that the statistical penalty outweighs the gain.

## Score relative to baseline
\\[
\\text{Score} = 100 \\times \\frac{E_{\\text{baseline}}}{E_{\\text{player}}}.
\\]

- **100:** matches the baseline objective.
- **Above 100:** better than baseline.
- **Below 100:** worse than baseline.

Scores are computed from simulation results, not assigned manually.

## Star thresholds

| Score | Stars |
|---|---:|
| Below 50 | 0 |
| 50 to below 90 | 1 |
| 90 to below 100 | 2 |
| Exactly 100 (within numerical tolerance) | 3 |
| Above 100 | 4 |

## Fair comparisons
Fidelity should not be read alone: a configuration retaining very few shots is not equivalent to one retaining most of them. The interface plots fidelity against kept-shot fraction, labels the number of checks, and can display a Pareto frontier. A point is dominated if another configuration has at least as high fidelity and at least as many kept shots, with one strictly better.

## T-doping objective
The T experiment compares checked and unchecked circuits using the same objective, `E(F,K) = (1-F) + 1/sqrt(1000K)`, while also reporting ancillas, two-qubit gates, depth, ideal acceptance, and fidelity.
