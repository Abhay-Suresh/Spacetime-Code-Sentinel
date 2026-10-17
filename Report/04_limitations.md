# Spacetime Sentinel: Limitations and Interpretation

## 1. Simulated hardware, not a live processor
The layout and noise parameters come from a **fake IBM backend**. Circuits run locally in Qiskit Aer. These are hardware-inspired simulations, not live-hardware measurements.

## 2. Approximate noise model
Fake-backend calibration data is not a complete model of every physical effect or its time variation. The main simulation includes configured gate and readout noise, while the exact T-state-fidelity calculation includes two-qubit depolarizing noise and excludes readout errors. Different assumptions can change which strategy appears best.

## 3. Estimated main-game fidelity
Main-game fidelity is estimated from a finite sample of stabilizer measurements. Statistical fluctuation is possible; the reported stabilizer spread is informative but does not eliminate all uncertainty.

## 4. Detection is not correction
Checks flag certain faults through their syndromes. The game discards shots that fail checks; it does not recover those shots. Faults that do not trigger the checks can remain in accepted data.

## 5. Clifford-only check picker
`qiskit-paulice` is used to construct checks on Clifford circuits. T-doped circuits are handled separately: checks are derived from the Clifford circuit, T gates are inserted at selected candidate sites, and checked/unchecked circuits are compared. This does not generalize to arbitrary T-gate placements.

## 6. Small T-doping simulation
Exact density-matrix simulation grows rapidly with circuit width, so the implementation caps the number of checks and tests a finite set of T counts and candidate placements. The Monte Carlo estimate of `P(H|A)` has sampling uncertainty, and the confidence-adjusted bound may be loose. A violated bound should be investigated, not hidden.

## 7. Picker and search limits
The picker uses an approximate cost/noise model and is not guaranteed to find a global optimum. The game explores a finite number of player choices and runs, so the best observed strategy may not be globally optimal.

## 8. Reproducibility
Seeds control the game's random choices, but exact reproduction also depends on compatible versions of Qiskit, Qiskit Aer, `qiskit-paulice`, and related packages. Library or calibration changes may alter outcomes.

## 9. Appropriate claims
The project demonstrates how check placement changes simulated fidelity, retained shots, and circuit overhead, and how a constrained T-doping experiment can be evaluated on small circuits. It should not claim to correct errors, validate all non-Clifford circuits, prove general quantum advantage, or predict real-device performance without further experiments.
