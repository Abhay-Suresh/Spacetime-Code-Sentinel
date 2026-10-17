# Spacetime Sentinel: Game Design and Design Choices

## Purpose
**Spacetime Sentinel** turns low-overhead quantum error detection into a strategy game. The player chooses where to place a limited number of checks in a noisy circuit. The goal is not simply to maximize fidelity: checks also cost extra qubits and gates and discard some measurement shots.

The design follows the Qiskit Fall Fest Advanced Track brief: game mechanics should represent real error-detection decisions, and results should be computed from Qiskit rather than assigned by hand.

## Core game loop
1. **Inspect the circuit and hardware panel.** The player sees the data-qubit chain, physical-qubit layout, estimated gate/readout noise, and available check sites.
2. **Choose target qubits.** The player selects targets in an explicit order. Each placed check consumes ancilla resources. Order matters because the check-placement routine processes the ordered target list.
3. **Preview cost.** A free preview reports ancilla count, two-qubit-gate count, depth, and whether the requested checks could be placed. It does not reveal the final fidelity.
4. **Run an experiment.** A run consumes one limited attempt for that level. The simulator reports estimated fidelity and retained-shot fraction.
5. **Compare strategies.** A fidelity-versus-kept-shots plot helps players compare placements and the marginal value of adding checks.
6. **Review exposure and try T-doping.** The player can inspect remaining undetected fault exposure and explore the extension to non-Clifford T gates.

The game has five levels with widths from 3 to 7 data qubits and increasing payload depths. The levels are intended to make resource pressure and placement choices progressively more important.

## Why these choices?
- **Limited ancilla budget:** checks require extra qubits and circuitry, so the player must choose where the overhead is worthwhile.
- **Ordered target selection:** `qiskit-paulice` builds variants with increasing check counts. For two requested checks, it normally returns zero-, one-, and two-check variants. Order can affect the construction.
- **Hardware-aware layout:** a connected physical-qubit chain is chosen using calibration information from a fake IBM backend. Available check sites depend on neighbouring ancilla availability where the backend exposes it.
- **Fidelity-versus-shots objective:** a check may improve accepted-result quality but reject shots. The score accounts for both fidelity and retained shots.
- **Reproducible randomness:** a user-selected seed controls the payload, layout search, stabilizer sampling, picker, simulator, and T-site selection.

## What the game is—and is not
This is an **error-detection** game. Ancilla checks reveal certain errors through their syndrome; shots with a non-trivial syndrome are discarded. The game does not apply recovery operations, so it is not a complete error-correction system. Results come from small circuits and simulated noise, not live quantum hardware.
