# Spacetime-Code-Sentinel
Advanced Track Submission for Qiskit Fall Fest 2026 @IIT Jodhpur

**Demo link:**

**Spacetime Code Sentinel** is an interactive Streamlit game and experiment sandbox for exploring spacetime Pauli checks, error detection, and post-selection in noisy quantum circuits. The project was developed for the Qiskit Fall Fest 2026 Hackathon — Advanced Track by **RandomQubits**.

It uses [`qiskit-paulice`](https://qiskit.github.io/qiskit-paulice/) to insert ancilla-assisted Pauli checks into Clifford circuits, then compares the fidelity of accepted samples with the fraction of shots retained. It also contains an experimental T-gate-doping workflow for studying selected non-Clifford circuit variants.

> **Simulation only:** despite the in-game wording “Run on hardware,” the current code simulates circuits locally with Qiskit Aer using a fake IBM backend to obtain a hardware layout and approximate noise parameters. It does not submit jobs to a real quantum processor and does not require IBM Quantum credentials.

## Features

- Five levels with 3–7 data qubits and brickwork Clifford payloads of 10, 13, 16, 19, or 22 CZ layers.
- Fake-backend-aware physical-qubit layout selection and identification of data qubits with neighbouring ancillas available for checks.
- Check placement through `qiskit-paulice`, using `cost="gamma"` and `method="windowed"`.
- Free check-cost previews, limited scored runs, a hint, fidelity-versus-kept-shot plots, Pareto visualization, fault-exposure comparisons, and remaining-exposure inspection.
- T-doping experiments for requested T counts **0, 1, 2, 4, and 8**, subject to available legal insertion sites and the exact simulation's check-count limit.
- Checked-versus-unchecked T-circuit comparisons, including fidelity, kept-shot fraction, ancillas, two-qubit gate count, circuit depth, and a combined trade-off objective.
- CSV exports for game runs and T-doping results.
- Seeded generation so a seed can reproduce the main randomized game setup.

## How the game works

1. The engine generates a one-dimensional brickwork random Clifford circuit.
2. It selects a path through a compatible fake backend's connectivity and extracts approximate gate/readout noise parameters.
3. You choose target logical qubits for check insertion. **The order matters** because the check picker processes targets in order. Each successfully inserted check uses an ancilla and adds circuit overhead.
4. Qiskit Aer simulates the checked circuits with a noise model. Shots that fail any check are discarded (post-selected out).
5. The app estimates fidelity from sampled stabilizer expectation values and reports the kept-shot fraction, circuit costs, score, and star rating.
6. The T-doping stage explores T-gate counts on eligible sites and compares unchecked and checked noisy simulations. The T-stage exact state-fidelity simulation includes the configured two-qubit depolarizing noise; its current calculation does **not** include readout errors.

Error detection filters accepted results; it does **not** actively correct the quantum state.

## Score and stars

The game uses the combined error objective

\[
E(F,K)=(1-F)+\frac{1}{\sqrt{1000K}},
\]

where `F` is fidelity and `K` is the fraction of shots kept. The score is `100 × reference_error / run_error`; a lower objective means a better result. The internally selected reference configuration is generated from a seeded ordering of available check sites and the best-performing prefix of that ordering. The no-check result is tracked separately.

| Score | Stars |
|---|---:|
| Below 50 | 0 |
| 50 to below 90 | 1 |
| 90 to below 100 | 2 |
| Exactly 100 (matches the reference) | 3 |
| Above 100 (beats the reference, if the reference is not the optimal selection) | 4 |

## Requirements

- Python **3.12 recommended**. Use a Python version supported by both Qiskit and `qiskit-paulice` (the latter currently documents Python 3.10–3.13).
- The packages in [`requirements.txt`](requirements.txt).
- Enough RAM for the exact density-matrix calculation in the T-doping experiment. Runtime and memory requirements increase quickly with the number of qubits and checks. We have restricted a general T-doping experiment only upto 3 target qubits, but the all T-doping sweep of you best result is not. 

`qiskit-paulice` 0.2.1 requires Qiskit 2.1 or newer; the requirements file reflects that compatibility floor. See the [official installation guide](https://qiskit.github.io/qiskit-paulice/install.html) if installation of its compiled package fails on your platform.

## Install and run

### Windows PowerShell

From the directory containing `app.py`, `engine.py`, and `requirements.txt`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

If `py -3.12` is not available, install Python 3.12 first or substitute another supported Python version. If PowerShell blocks virtual-environment activation, you can invoke the environment's executable directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Streamlit prints a local URL (usually `http://localhost:8501`) when the app starts.

## Project layout

```text
.
├── app.py            # Streamlit interface, game flow, plots, and exports
├── engine.py         # Quantum circuits, backend layout, noise, simulation, scoring, and T stage
├── requirements.txt  # Python runtime dependencies
├── README.md         # Project documentation
└── .gitignore        # Ignore local environments, secrets, caches, and generated exports
```

## Reproducibility and performance

- A seed appears in the sidebar. Applying a seed restarts the game with that seed.
- Level setup may take a minute because it selects a layout, prepares the noise model, and evaluates a reference curve.
- A full T-doping sweep can take longer than an ordinary run because it performs exact state simulation and estimates a fault-probability bound using Monte Carlo samples.
- To preserve reproducibility, use the same dependency versions, Python version, and seed. Some underlying operations may still have implementation-dependent behavior.

## Important limitations

- Fake backend calibrations are used for local simulation; results are not measurements from live hardware.
- The check picker uses an approximate noise model and a heuristic cost/method, so a selected result is not guaranteed to be globally optimal.
- Clifford fidelity is estimated using a finite sample of stabilizers (`N_STABS = 10` in the current engine); small differences can be sampling noise.
- The noise model is simplified, and the T-stage exact fidelity path models configured two-qubit depolarizing noise but omits readout errors.
- T-doping is restricted to candidate sites where the implementation's Pauli-fault condition is met. Requested T counts may exceed the number of valid sites, so inspect the “requested” and “placed” counts in the output.
- Exact density-matrix simulation is intended for the small circuits used here and becomes expensive as circuit width and ancilla count grow.

## Analysis
Should you wish to have an exhaustive small-level analysis of what has been done essential in terms of Quantum Error Dection using [`engine.py`](engine.py) and [`app.py`](app.py), you can run the [`analysis.ipynb`](analysis.ipynb), confiuguring every underlying element contributing to the game.

Run this notebook from the project folder, with [`app.py`](app.py) and [`engine.py`](engine.py) in the same folder. First install the project's [`requirements.txt`](requirements.txt); then start Jupyter with `python -m pip install jupyterlab` if needed.

This can become expensive at higher levels. Results are saved as CSV files in `analysis_results/` if you wish to save them.

## References


