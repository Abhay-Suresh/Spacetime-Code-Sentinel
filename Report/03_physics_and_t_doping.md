# Spacetime Sentinel: Underlying Physics and T-Doping Strategy

## Payload circuit
Each level creates a one-dimensional **brickwork random Clifford circuit** on 3–7 data qubits. It begins with Hadamard gates and applies alternating nearest-neighbour CZ layers, interleaved with randomly selected Clifford gates (`sx` and `s` in the implementation). Clifford circuits allow efficient stabilizer and Pauli-error analysis and are accepted by `qiskit-paulice`.

## Checks, ancillas, syndromes, and post-selection
The game calls `qiskit-paulice.add_pauli_checks` to add coherent Pauli checks to the Clifford circuit.
- **Data qubits** carry the payload computation.
- **Ancillas** support the check operations.
- **Syndrome/readout information** indicates whether check conditions were satisfied.
- **Post-selection** keeps shots passing every check and discards shots with a non-trivial syndrome.

Checks only detect error components visible to their syndrome. Undetected errors can remain in accepted data. Detection is not correction: flagged shots are discarded, not repaired.

For two requested checks, the picker normally returns three circuit variants: zero checks, one check, and two checks. In general, requesting `k` checks gives variants from 0 through `k` (`k+1` circuits), subject to what the picker can actually place.

## Noise and fidelity
The game selects a connected physical-qubit chain using calibration information from a fake IBM backend. It builds a noise model from that calibration data and simulates locally with Qiskit Aer. Main-game fidelity is estimated from sampled stabilizer expectation values on accepted shots, and the kept-shot fraction is tracked separately.

## Why T gates need a separate strategy
`qiskit-paulice` check insertion accepts Clifford circuits, not circuits containing T gates. T is non-Clifford, so the game does not pass a T-doped payload directly to the picker.

Instead:
1. Construct and validate checks on a Clifford circuit.
2. Insert T gates at selected candidate sites.
3. Compare checked and unchecked versions. The unchecked counterpart is made by stripping gates that touch ancillas while retaining data-only gates.

This is a small-circuit comparison, not native library support for arbitrary T-doped circuits.

## T-site selection
The code examines `qiskit-paulice`'s uncovered Pauli information and selects candidate **Z-type faults** not detected by the chosen checks. Candidate sites are restricted to data-data CZ instructions, excluding check-gadget operations involving ancillas. Selection is shuffled deterministically using the T-stage seed.

The physics motivation is that T is diagonal and commutes with Z:

\\[
TZ = ZT.
\\]

A check/fault relation involving only I or Z on the T-gated qubit can therefore remain compatible across that T gate. This is a local condition; it does not mean arbitrary checks commute with T or every undetected fault is harmless.

The implementation inserts the same number of T gates in checked and unchecked configurations. If fewer legal sites exist than requested, the placed count is limited by the available sites.

## Exact comparison and conservative bound
For T experiments, a statevector defines the ideal target and density-matrix simulation calculates the noisy result under two-qubit depolarizing noise. The code records ideal/noisy acceptance, checked and unchecked fidelities, retained-shot fraction, ancilla/gate/depth overhead, and a Monte Carlo estimate of `P(H|A)` with a one-sided 95% upper confidence limit.

Here `A` denotes acceptance and `H` the defined harmless-fault event. The implementation evaluates:

\\[
F_2 \\geq F_1 - \\operatorname{upper95}\\!\\left(P(H\\mid A)\\right),
\\]

then compares the bound with exact small-circuit T-doped fidelity. The bound is intended to be conservative and may be loose. The app warns if noiseless check preservation fails or if the bound is violated.

The exact T-state calculation uses two-qubit depolarizing noise and a statevector target; readout errors are not included in that exact T-state-fidelity calculation. The number of checks is capped to keep density-matrix simulation tractable.

## What this demonstrates
The T stage explores how checks, T count, fidelity, retained shots, and circuit overhead interact. It does not establish that `qiskit-paulice` supports arbitrary non-Clifford inputs or prove performance on live hardware.
