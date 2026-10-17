import time
import random
from math import sqrt
from dataclasses import dataclass
from collections import Counter
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Pauli, Clifford, Statevector, DensityMatrix
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel as AerNoise, ReadoutError, depolarizing_error
from qiskit_paulice import add_pauli_checks
from qiskit_paulice.layout import get_check_qubits
from qiskit_paulice.noise_models import NoiseModel as PNoise

DEFAULT_SEED = 67
S_SHOTS = 1000            # raw-shot budget in the score
SHOTS_PER_STAB = 2000
N_STABS = 10               # sampled stabilizers per evaluation (notebook: 20)
GATE_NOISE_SCALE = 1.0    # 1.0 = exactly what from_backend reports; raise if levels are too easy
T_COUNTS = [0, 1, 2, 4, 8]
T_MAX_CHECKS = 3          # keeps the exact density-matrix simulation <= 10 qubits at width 7
MAX_STARS = 4
PAYLOAD_LABEL_PREFIX = "SSPAYLOADGATE_"
MC_SAMPLES = 200_000
BACKEND_CANDIDATES = ["FakeFez", "FakeTorino", "FakeMarrakesh", "FakeBoston", "FakeKingston", "FakeSherbrooke"]
NOISY_2Q = ["cz", "cx", "cy"]
BASIS_T = ["h", "s", "sdg", "sx", "sxdg", "x", "y", "z", "t", "tdg", "cx", "cz", "cy"]


@dataclass
class Level:
    name: str
    width: int
    depth: int      # brickwork CZ layers
    budget: int     # max checks (capped by available check sites)
    runs: int
    lesson: str


LEVELS = [
    Level("1. First light", 3, 10, 2, 6, "A small chain: a check helps, but costs shots."),
    Level("2. Warm-up",     4, 13, 3, 6, "Order of targets starts to matter."),
    Level("3. Rising tide", 5, 16, 3, 5, "Gains versus lost shots."),
    Level("4. Storm",       6, 19, 4, 5, "Kept fraction collapses; choose targets wisely."),
    Level("5. Tempest",     7, 22, 4, 5, "The widest chain: every check is expensive."),
]


def seeds(base, idx):
    b = base + 1000 * idx
    return dict(payload=b, layout=b + 1, stab=b + 2, t=b + 3, picker=base + idx, sim=base + 10 * idx)


# ---------------- backend, layout, payload (as in the Qiskit tutorial) ----------------
_BACKEND = None


def get_backend():
    global _BACKEND
    if _BACKEND is None:
        from qiskit_ibm_runtime import fake_provider as fp
        for name in BACKEND_CANDIDATES:
            cls = getattr(fp, name, None)
            if cls is None:
                continue
            try:
                _BACKEND = cls()
                break
            except Exception:
                continue
        if _BACKEND is None:
            raise RuntimeError("No fake backend found in qiskit_ibm_runtime.fake_provider; "
                               "edit BACKEND_CANDIDATES.")
    return _BACKEND


def find_check_layout(backend, num_qubits, rng, num_trials=200, max_gate_error=0.03, max_readout_error=0.2):
    """Tutorial helper: low-error path with many available ancillas (None errors treated as 0)."""
    target = backend.target
    gate_2q = next(nm for nm in ("cz", "ecr", "cx") if nm in target.operation_names)
    edge_error = {}
    for qubits, props in target[gate_2q].items():
        e = props.error if (props is not None and props.error is not None) else 0.0
        edge = tuple(sorted(qubits))
        edge_error[edge] = min(edge_error.get(edge, 1.0), e)
    ro = {}
    for (q,) in target["measure"]:
        props = target["measure"][(q,)]
        ro[q] = props.error if (props is not None and props.error is not None) else 0.0
    adj = {}
    for (a, b), e in edge_error.items():
        if e <= max_gate_error and ro.get(a, 0) <= max_readout_error and ro.get(b, 0) <= max_readout_error:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    starts = sorted(adj)
    best, best_score = None, (-1, float("inf"))
    for _ in range(num_trials):
        path = [starts[rng.integers(len(starts))]]
        while len(path) < num_qubits:
            opts = sorted(adj[path[-1]] - set(path))
            if not opts:
                break
            path.append(opts[rng.integers(len(opts))])
        if len(path) < num_qubits:
            continue
        try:
            npairs = len(get_check_qubits(backend, path)[0])
        except Exception:
            npairs = 0
        mean_e = float(np.mean([edge_error[tuple(sorted(e))] for e in zip(path, path[1:])]))
        if npairs > best_score[0] or (npairs == best_score[0] and mean_e < best_score[1]):
            best, best_score = path, (npairs, mean_e)
    if best is None:
        raise RuntimeError("No connected low-error path found on the backend.")
    return [int(q) for q in best]


def brickwork(n, depth, rng):
    """One-dimensional brickwork random Clifford (the tutorial's payload)."""
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for d in range(depth):
        for i in range(d % 2, n - 1, 2):
            qc.cz(i, i + 1)
        for q in range(n):
            if rng.integers(0, 2): qc.sx(q)
            if rng.integers(0, 2): qc.s(q)
            if rng.integers(0, 2): qc.sx(q)
    return qc


def sample_stabilizers(circ, n, M, rng):
    gens = [Pauli(lbl) for lbl in Clifford(circ).to_labels(mode="S")]
    seen, out = set(), []
    while len(out) < M:
        mask = tuple(int(x) for x in rng.integers(0, 2, n))
        if not any(mask) or mask in seen:
            continue
        seen.add(mask)
        p = Pauli("I" * n)
        for g, m in zip(gens, mask):
            if m:
                p = p.compose(g)
        out.append(p)
    return out


def rotated(circ, pauli):
    out = circ.copy()
    for q in range(pauli.num_qubits):
        if pauli.x[q]:
            if pauli.z[q]:
                out.sdg(q)
            out.h(q)
    out.measure_all()                    # creg "meas"
    return out


# ---------------- library helpers ----------------
def get_circuit(cc):
    for name in ("circuit", "checked_circuit", "qc", "dressed_circuit"):
        if hasattr(cc, name):
            return getattr(cc, name)
    return cc


def pick(circ, targets, pn, seed):
    return add_pauli_checks(circ, target_qubits=list(targets), noise_model=pn,
                            cost="gamma", method="windowed", seed=seed)


def error_metric(F, K):
    Fc = min(max(F, 0.0), 1.0)
    return (1 - Fc) + 1 / sqrt(S_SHOTS * K) if K > 0 else float("inf")


def coverage_info(cc, n):
    unc = list(getattr(cc, "uncovered_paulis", ()))
    by_q = Counter(u.qubit for u in unc if u.qubit < n)
    cells = [(u.qubit, 0 if u.after_instruction is None else u.after_instruction + 1)
             for u in unc if u.qubit < n]
    return {q: by_q.get(q, 0) for q in range(n)}, cells


def run_variants(sim, objs, pauli, n, seed):
    """Simulate every check-count variant of one stabilizer circuit; return (<G> after post-selection, kept)."""
    circs = [get_circuit(o) for o in objs]
    res = sim.run(circs, shots=SHOTS_PER_STAB, seed_simulator=seed).result()
    sign = -1 if int(pauli.phase) % 4 == 2 else 1
    supp = [q for q in range(n) if pauli.x[q] or pauli.z[q]]
    out = []
    for v, (o, qc) in enumerate(zip(objs, circs)):
        counts = res.get_counts(v)
        syn = o.get_postselection_method()
        meas_idx = [qc.find_bit(c).index for c in next(r for r in qc.cregs if r.name == "meas")]
        tot = kept = s = 0
        for key, c in counts.items():
            tot += c
            key = key.replace(" ", "")
            if np.asarray(syn(key)).any():
                continue
            bits = key[::-1]
            par = sum(bits[meas_idx[q]] == "1" for q in supp) & 1
            kept += c
            s += c * (1 - 2 * par)
        out.append((sign * s / kept if kept else float("nan"), kept / tot))
    return out


# ---------------- T stage: exact simulation and the paper's bound ----------------
def accept_vector(N, supports, signs):
    b = np.arange(2 ** N)
    acc = np.ones(2 ** N)
    for sup, sg in zip(supports, signs):
        par = np.zeros(2 ** N, dtype=np.int64)
        for q in sup:
            par ^= (b >> q) & 1
        acc *= (par == (0 if sg == 1 else 1))
    return acc


def exact_post(qc_nm, supports, signs, gn, noisy):
    """Exact post-selected fidelity of the encoded state (data + ancillas) and acceptance probability."""
    N = qc_nm.num_qubits
    psi = Statevector(qc_nm).data
    nm = None
    if noisy:
        nm = AerNoise()
        nm.add_all_qubit_quantum_error(depolarizing_error(gn, 2), NOISY_2Q)
    sim = AerSimulator(method="density_matrix", noise_model=nm)
    tq = transpile(qc_nm, basis_gates=BASIS_T, optimization_level=0)
    tq.save_density_matrix()
    rho = DensityMatrix(sim.run(tq).result().data()["density_matrix"]).data
    acc = accept_vector(N, supports, signs)
    rp = rho * acc[:, None] * acc[None, :]
    p = float(np.real(np.trace(rp)))
    F = float(np.real(psi.conj() @ rp @ psi)) / p if p > 1e-12 else float("nan")
    return p, F


def mc_harmless(qc_nm, supports, gn, samples, seed):
    """Pr(E in H | E in A): accepted, non-trivial, harmless fault configurations (Theorem S1).
    A fault is harmless if its pull-back to the input has no X part, i.e. it stabilizes the encoded state."""
    N = qc_nm.num_qubits
    k = len(supports)
    data = [(i.operation, [qc_nm.find_bit(q).index for q in i.qubits])
            for i in qc_nm.data if i.operation.name != "barrier"]
    G = len(data)
    ident = Clifford(QuantumCircuit(N))
    pre = [ident]
    for op, qs in data:
        pre.append(pre[-1].compose(Clifford(op), qargs=qs))
    suf = [None] * (G + 1)
    suf[G] = ident
    for i in range(G - 1, -1, -1):
        op, qs = data[i]
        suf[i] = ident.compose(Clifford(op), qargs=qs).compose(suf[i + 1])
    locs = [(i, qs) for i, (op, qs) in enumerate(data) if op.name in NOISY_2Q and len(qs) == 2]
    codes = np.zeros((len(locs), 15), dtype=np.int64)
    for li, (i, qs) in enumerate(locs):
        for c in range(1, 16):
            lab = ["I"] * N
            lab[N - 1 - qs[0]] = "IXYZ"[c % 4]
            lab[N - 1 - qs[1]] = "IXYZ"[c // 4]
            E = Pauli("".join(lab))
            fx = E.evolve(suf[i + 1], frame="s").x
            bx = E.evolve(pre[i + 1], frame="h").x
            syn = 0
            for j, sup in enumerate(supports):
                syn |= (int(np.sum(fx[sup])) & 1) << j
            xv = 0
            for q in range(N):
                xv |= int(bx[q]) << q
            codes[li, c - 1] = syn | (xv << k)
    q_fault = gn * 15 / 16
    rng = np.random.default_rng(seed)
    n_acc = n_h = 0
    chunk = 20000
    for start in range(0, samples, chunk):
        m = min(chunk, samples - start)
        rows, cols = np.nonzero(rng.random((m, len(locs))) < q_fault)
        pidx = rng.integers(0, 15, len(rows))
        acc = np.zeros(m, dtype=np.int64)
        np.bitwise_xor.at(acc, rows, codes[cols, pidx])
        nf = np.bincount(rows, minlength=m)
        accepted = (acc & ((1 << k) - 1)) == 0
        harmless = (acc >> k) == 0
        n_acc += int(accepted.sum())
        n_h += int((accepted & harmless & (nf > 0)).sum())
    p = n_h / max(n_acc, 1)
    se = sqrt(p * (1 - p) / max(n_acc, 1))
    # One-sided 95% Clopper-Pearson upper confidence limit for P(H | accept).
    try:
        from scipy.stats import beta
        upper = 1.0 if n_h >= n_acc else float(beta.ppf(0.95, n_h + 1, n_acc - n_h))
    except Exception:
        upper = min(1.0, p + 1.645 * se)
    return p, se, n_acc / samples, upper


def labeled_payload_copy(circ):
    """Copy the data-only payload and label its gates so check-insertion positions can be mapped back."""
    out = QuantumCircuit(circ.num_qubits)
    out.global_phase = circ.global_phase
    for i, inst in enumerate(circ.data):
        # Standard Qiskit gates (for example HGate) may be immutable singletons.
        # Convert them to a mutable instruction before assigning our payload label.
        if hasattr(inst.operation, "to_mutable"):
            op = inst.operation.to_mutable()
        else:
            op = inst.operation.copy()
        op.label = f"{PAYLOAD_LABEL_PREFIX}{i}"
        qargs = [out.qubits[circ.find_bit(q).index] for q in inst.qubits]
        out.append(op, qargs)
    return out


def _payload_instruction_positions(checked, payload, n):
    """Return (checked instruction index, original payload instruction index) pairs.

    Labels are preferred. If the check library strips labels, recover the original
    instruction subsequence by matching operation names, parameters, and data-qubit args.
    """
    found = []
    for checked_idx, inst in enumerate(checked.data):
        label = getattr(inst.operation, "label", None) or ""
        if label.startswith(PAYLOAD_LABEL_PREFIX):
            try:
                payload_idx = int(label[len(PAYLOAD_LABEL_PREFIX):])
            except ValueError:
                continue
            found.append((checked_idx, payload_idx))
    if len(found) == len(payload.data):
        return found
    found = []

    def signature(circuit, inst):
        qids = tuple(circuit.find_bit(q).index for q in inst.qubits)
        params = tuple(repr(v) for v in getattr(inst.operation, "params", ()))
        return inst.operation.name, qids, params

    cursor = -1
    for payload_idx, pinst in enumerate(payload.data):
        sig = signature(payload, pinst)
        for checked_idx in range(cursor + 1, len(checked.data)):
            if signature(checked, checked.data[checked_idx]) == sig:
                found.append((checked_idx, payload_idx))
                cursor = checked_idx
                break
    return found


def map_checked_site_to_payload(checked_idx, q, payload_positions):
    """Map a checked-circuit location to the matching data-only instruction boundary."""
    previous = [(ci, pi) for ci, pi in payload_positions if ci <= checked_idx]
    payload_idx = max(previous, key=lambda pair: pair[0])[1] if previous else -1
    return payload_idx, q

def strip_ancillas(qc, n):
    """Delete every gate that touches an ancilla (qubit index >= n). Keeps data-only gates, including T."""
    out = QuantumCircuit(n)
    for inst in qc.data:
        if inst.operation.name in ("measure", "barrier"):
            continue
        idx = [qc.find_bit(q).index for q in inst.qubits]
        if all(i < n for i in idx):
            out.append(inst.operation, idx)
    return out

def insert_T(qc, sites):
    """Insert T gates after instruction indices; index -1 means before the first instruction."""
    by = {}
    for (i, q) in sites:
        by.setdefault(i, []).append(q)
    out = qc.copy_empty_like()
    for q in by.get(-1, []):
        out.t(q)
    for i, inst in enumerate(qc.data):
        out.append(inst.operation, inst.qubits, inst.clbits)
        for q in by.get(i, []):
            out.t(q)
    return out


# ---------------- feedback ----------------
def feedback(r, prev, base, par, n):
    sec = {}
    dF, dK = r["F"] - base["F"], base["K"] - r["K"]
    res = [f"Fidelity {base['F']:.3f} → {r['F']:.3f} ({dF:+.3f}); you kept {r['K']:.0%} of shots (lost {dK:.0%})."]
    if r["k"] == 0:
        res.append("The picker found no valid checks for these targets, so this run equals placing nothing.")
    elif r["error"] < base["error"]:
        res.append(f"Net win: combined error fell from {base['error']:.3f} to {r['error']:.3f}.")
    else:
        res.append(f"Net loss: combined error rose from {base['error']:.3f} to {r['error']:.3f}. "
                   "The checks cost more than they gained.")
    noise = 2 * sqrt(np.nan_to_num(r.get("F_err", 0)) ** 2 + np.nan_to_num(base.get("F_err", 0)) ** 2)
    if abs(dF) < noise:
        res.append(f"The change is within the stabilizer-sampling spread (about ±{noise:.3f}); do not over-read it.")
    sec["Result"] = res

    m, used = r["marginal"], r["used"]
    pc = []
    for j in range(1, len(m)):
        dFj, dKj = m[j]["F"] - m[j - 1]["F"], m[j - 1]["K"] - m[j]["K"]
        dE = m[j]["error"] - m[j - 1]["error"]
        tgt = used[j - 1] if j - 1 < len(used) else "?"
        pc.append(f"Check {j} (target q{tgt}): fidelity {dFj:+.3f}, shots lost {dKj:.1%} → "
                  f"{'worth its ancilla' if dE < 0 else 'cost more than it gained'}.")
    if len(m) >= 3:
        gains = [m[j]["F"] - m[j - 1]["F"] for j in range(1, len(m))]
        if gains[0] > 0 and gains[-1] < 0.3 * gains[0]:
            pc.append("Later checks add much less than the first: diminishing returns.")
    if pc:
        sec["Each check"] = pc

    if prev:
        a, p = r["used"], prev["used"]
        vs = ["Same placement as your last run (differences are sampling noise)." if a == p
              else (f"Same qubits as last run in a different order ({p} → {a})." if set(a) == set(p)
                    else f"Targets changed from {p} to {a}.")]
        vs.append(f"Score {prev['score']:.0f} → {r['score']:.0f} ({r['score'] - prev['score']:+.0f}); "
                  f"two-qubit gates {prev['twoq']:.0f} → {r['twoq']:.0f}.")
        sec["Versus your last run"] = vs

    unc = r["unc_by_qubit"]
    worst = max(unc, key=unc.get)
    ex = [f"Most exposed qubit now: q{worst} ({unc[worst]:.0f} undetected fault types on average)."]
    if worst not in used:
        ex.append(f"q{worst} is not one of your targets; consider it next if it is an available check site.")
    sec["Remaining exposure"] = ex
    pv = [f"Score {r['score']:.0f} against baseline 100."]
    if r["k"] < r["requested"]:
        pv.append(f"The picker found only {r['k']} valid check(s) of the {r['requested']} you requested.")
    sec["Versus baseline"] = pv
    return sec


# ---------------- session ----------------
class LevelSession:
    def __init__(self, idx, base_seed):
        self.level, self.idx = LEVELS[idx], idx
        self.s = seeds(base_seed, idx)
        n = self.level.width
        L = self.level
        self.backend = get_backend()
        self.circ = brickwork(n, L.depth, np.random.default_rng(self.s["payload"]))
        self.layout = find_check_layout(self.backend, n, np.random.default_rng(self.s["layout"]))
        base_nm = PNoise.from_backend(self.backend, self.layout, uniform_gate_noise=True)
        self.gn = float(base_nm.gate_noise) * GATE_NOISE_SCALE
        self.ro = float(base_nm.readout_noise or 0.0)
        self.pn = PNoise(gate_noise=self.gn, readout_noise=self.ro)
        pos = {p: i for i, p in enumerate(self.layout)}
        try:
            tp, ap = get_check_qubits(self.backend, self.layout)
            self.anc_phys = {pos[t]: a for t, a in zip(tp, ap) if t in pos}
        except Exception:
            self.anc_phys = {}
        self.sites_note = ""
        if not self.anc_phys:
            self.anc_phys = {i: None for i in range(n)}
            self.sites_note = "Could not read check sites from the chip; all qubits allowed."
        self.allowed = sorted(self.anc_phys)
        self.budget = max(1, min(L.budget, len(self.allowed)))
        nm = AerNoise()
        nm.add_all_qubit_quantum_error(depolarizing_error(self.gn, 2), NOISY_2Q)
        if self.ro > 0:
            nm.add_all_qubit_readout_error(ReadoutError([[1 - self.ro, self.ro], [self.ro, 1 - self.ro]]))
        self.sim = AerSimulator(method="stabilizer", noise_model=nm)
        self.stabs = sample_stabilizers(self.circ, n, min(N_STABS, 2 ** n - 1),
                                        np.random.default_rng(self.s["stab"]))
        self.rot = [rotated(self.circ, p) for p in self.stabs]
        self.payload_twoq = self.circ.count_ops().get("cz", 0)
        self.runs_left, self.history, self._cache = L.runs, [], {}
        self.hint_text, self.finished, self.hint_used = None, False, False
        self.t_history, self.t_skipped, self._tprep, self._tcache = [], False, {}, {}
        self._compute_par()

    # ----- main game -----
    def _objs(self, targets):
        key = tuple(targets)
        if key not in self._cache:
            self._cache[key] = [pick(r, key, self.pn, self.s["picker"] + j) for j, r in enumerate(self.rot)]
        return self._cache[key]

    def _evaluate(self, objs_by_stab, kmax):
        n, M = self.level.width, len(self.stabs)
        per = [run_variants(self.sim, objs[:kmax + 1], self.stabs[j], n, self.s["sim"] + 17 * j)
               for j, objs in enumerate(objs_by_stab)]
        out = []
        for v in range(kmax + 1):
            Es = np.array([per[j][v][0] for j in range(M)])
            Ks = np.array([per[j][v][1] for j in range(M)])
            F, K = float(np.nanmean(Es)), float(np.mean(Ks))
            covs = [coverage_info(objs_by_stab[j][v], n) for j in range(M)]
            unc_q = {q: float(np.mean([c[0][q] for c in covs])) for q in range(n)}
            qc0 = get_circuit(objs_by_stab[0][v])
            ops = qc0.count_ops()
            out.append(dict(
                k=v, F=F, K=K, error=error_metric(F, K), F_err=float(np.nanstd(Es) / sqrt(M)),
                twoq=float(np.mean([sum(get_circuit(o[v]).count_ops().get(g, 0) for g in NOISY_2Q)
                                    for o in objs_by_stab])),
                depth=qc0.depth(), ancillas=qc0.num_qubits - n,
                gamma=float(np.mean([getattr(o[v], "cost", np.nan) for o in objs_by_stab])),
                unc_by_qubit=unc_q, unc_total=sum(unc_q.values()),
                unc_cells=covs[0][1], n_inst=len(qc0.data)))
        return out

    def _compute_par(self):
        t0 = time.time()
        rng = random.Random(self.s["picker"] * 7 + 1)
        order = rng.sample(self.allowed, len(self.allowed))[:self.budget]
        self.par_order = order
        objs = self._objs(order)
        kmax = min(len(o) - 1 for o in objs)
        res = self._evaluate(objs, kmax)
        used = list(getattr(objs[0][-1], "target_qubits", ()))
        for r in res:
            r["targets"] = used[:r["k"]]
        self.baseline, self.par_curve = res[0], res
        self.par = min(res, key=lambda r: r["error"])
        self.setup_seconds = time.time() - t0

    def prep(self, targets):
        objs = self._objs(targets)
        rows = []
        for k in range(min(len(o) for o in objs)):
            qc = get_circuit(objs[0][k])
            ops = qc.count_ops()
            rows.append(dict(k=k, twoq=sum(ops.get(g, 0) for g in NOISY_2Q), depth=qc.depth(),
                             ancillas=qc.num_qubits - self.level.width))
        return objs, rows

    def run(self, targets):
        if self.runs_left <= 0 or not targets or len(targets) > self.budget:
            raise ValueError("no runs left, no targets, or over ancilla budget")
        if any(t not in self.allowed for t in targets):
            raise ValueError("a selected qubit has no free neighbouring ancilla on this chip")
        t0 = time.time()
        objs = self._objs(targets)
        kmax = min(len(o) - 1 for o in objs)
        res = self._evaluate(objs, kmax)
        used = list(getattr(objs[0][-1], "target_qubits", ()))[:kmax]
        r = dict(res[-1])
        r.update(targets=list(targets), used=used, requested=len(targets),
                 marginal=[{k_: e[k_] for k_ in ("k", "F", "K", "error", "unc_total", "twoq")} for e in res],
                 seconds=time.time() - t0, circuit=get_circuit(objs[0][-1]))
        r["score"] = 100 * self.par["error"] / r["error"] if r["error"] > 0 else float("inf")
        r["stars"] = self.stars(r)
        prev = self.history[-1] if self.history else None
        r["feedback"] = feedback(r, prev, self.baseline, self.par, self.level.width)
        self.runs_left -= 1
        self.history.append(r)
        return r

    def use_hint(self):
        if self.runs_left < 2 or self.hint_text:
            raise ValueError("hint unavailable")
        self.runs_left -= 1
        self.hint_used = True
        pt = self.par.get("targets") or []
        self.hint_text = ("The baseline's best result on this level uses no checks." if not pt else
                          f"The baseline's best result starts with a check on q{pt[0]} and uses "
                          f"{self.par['k']} check(s).")
        return self.hint_text

    def stars(self, r):
        """Four-star rubric: <50=0, 50-<90=1, 90-<100=2, match=3, beat=4."""
        score = float(r.get("score", 0.0))
        if score < 50:
            return 0
        if score < 90:
            return 1
        if score < 100:
            return 2
        if abs(score - 100.0) <= 1e-9:
            return 3
        return 4

    def best(self):
        return max(self.history, key=lambda r: r["score"]) if self.history else None

    def payload_load(self):
        load = Counter()
        for inst in self.circ.data:
            if inst.operation.name == "cz":
                for q in inst.qubits:
                    load[self.circ.find_bit(q).index] += 1
        return {q: load.get(q, 0) for q in range(self.level.width)}

    # ----- T stage (the paper's fidelity bound) -----
    def t_default_targets(self):
        b = self.best()
        base = (b["used"] if b and b["used"] else self.par.get("targets") or self.allowed)
        return list(base)[:T_MAX_CHECKS]

    def _t_prep(self, targets):
        key = tuple(targets)
        if key in self._tprep:
            return self._tprep[key]
        n = self.level.width
        payload = self.circ.copy()                       # no labels
        circ = payload.copy()
        circ.measure_all()
        objs = pick(circ, key, self.pn, self.s["picker"] + 99)
        cc, k = objs[-1], len(objs) - 1
        qc = get_circuit(cc)
        first_meas = next((i for i, inst in enumerate(qc.data) if inst.operation.name == "measure"), len(qc.data))
        nm = qc.remove_final_measurements(inplace=False)
        N = nm.num_qubits
        cl = Clifford(nm)
        anc = list(getattr(cc, "check_qubits", ()))[:k] or list(range(n, n + k))
        supports, signs, ok = [], [], True
        for a in anc:
            lab = ["I"] * N
            lab[N - 1 - a] = "Z"
            S = Pauli("".join(lab)).evolve(cl, frame="s")     # ideal syndrome observable
            ok &= not bool(S.x.any())
            supports.append([q for q in range(N) if S.z[q]])
            signs.append(-1 if int(S.phase) % 4 == 2 else 1)

        # T sites: Z faults that no check can detect, restricted (as in the paper, S1.3) to positions
        # directly after a payload CZ. A gadget CZ always involves an ancilla (index >= n), so requiring
        # both qubits < n excludes check circuitry.
        def after_payload_cz(i, q):
            inst = qc.data[i]
            if inst.operation.name != "cz":
                return False
            idx = [qc.find_bit(x).index for x in inst.qubits]
            return all(j < n for j in idx) and q in idx

        raw_sites = sorted({(u.after_instruction, u.qubit) for u in getattr(cc, "uncovered_paulis", ())
                            if u.pauli == "Z" and u.qubit < n and u.after_instruction is not None
                            and u.after_instruction < first_meas
                            and after_payload_cz(u.after_instruction, u.qubit)})
        random.Random(self.s["t"]).shuffle(raw_sites)
        # Mapping-free: the unchecked counterpart is derived in run_t by stripping the check gates.
        site_pairs = [(s, s) for s in raw_sites]

        p1, F1 = exact_post(nm, supports, signs, self.gn, noisy=True)
        PH, PHse, _, PHupper = mc_harmless(nm, supports, self.gn, MC_SAMPLES, self.s["t"])
        out = dict(qc=qc, payload=payload, k=k, supports=supports, signs=signs, supports_ok=ok,
                   site_pairs=site_pairs, sites=raw_sites, payload_sites=raw_sites,
                   p1=p1, F1=F1, PH=PH, PHse=PHse, PHupper=PHupper)
        self._tprep[key] = out
        return out

    def run_t(self, t, targets):
        key = (t, tuple(targets))
        if key in self._tcache:
            return self._tcache[key]
        pr = self._t_prep(targets)
        chosen_pairs = pr["site_pairs"][:t]
        checked_sites = [pair[0] for pair in chosen_pairs]
        payload_sites = [pair[1] for pair in chosen_pairs]

        # Checked T-doped configuration: same T-count at the corresponding check-safe sites.
        doped_checked = insert_T(pr["qc"], checked_sites)
        checked_nm = doped_checked.remove_final_measurements(inplace=False)
        ideal_keep_checked, ideal_f_checked = exact_post(
            checked_nm, pr["supports"], pr["signs"], self.gn, noisy=False
        )
        checked_keep, F_checked = exact_post(
            checked_nm, pr["supports"], pr["signs"], self.gn, noisy=True
        )

        # Unchecked counterpart: delete the check gadgets from the checked doped circuit.
        doped_payload = strip_ancillas(doped_checked, self.level.width)
        ideal_keep_unchecked, ideal_f_unchecked = exact_post(doped_payload, [], [], self.gn, noisy=False)
        unchecked_keep, F_unchecked = exact_post(doped_payload, [], [], self.gn, noisy=True)

        bound = pr["F1"] - pr["PHupper"]
        checked_ops = checked_nm.count_ops()
        payload_ops = doped_payload.count_ops()
        checked_twoq = int(sum(checked_ops.get(g, 0) for g in NOISY_2Q))
        unchecked_twoq = int(sum(payload_ops.get(g, 0) for g in NOISY_2Q))
        unchecked_depth = int(doped_payload.depth())
        checked_depth = int(checked_nm.depth())
        tradeoff_unchecked = error_metric(F_unchecked, unchecked_keep)
        tradeoff_checked = error_metric(F_checked, checked_keep)
        better_mode = "With checks" if tradeoff_checked < tradeoff_unchecked else "Without checks"
        best_tradeoff = min(tradeoff_checked, tradeoff_unchecked)
        r = dict(
            T=len(checked_sites), t_req=t, avail=len(pr["site_pairs"]), targets=list(targets), k=pr["k"],
            ideal_reference="Exact statevector of the corresponding T-doped circuit",
            F_ideal_unchecked=ideal_f_unchecked, F_ideal_checked=ideal_f_checked,
            p_ideal_unchecked=ideal_keep_unchecked, p_ideal_checked=ideal_keep_checked,
            p_clifford=pr["p1"], p_acc=checked_keep, F1=pr["F1"], F2=F_checked,
            F_no_checks=F_unchecked, K_no_checks=unchecked_keep,
            PH=pr["PH"], PH_se=pr["PHse"], PH_upper=pr["PHupper"], bound=bound,
            holds=bool(F_checked >= bound - 1e-9),
            valid=bool(abs(ideal_keep_checked - 1) < 1e-6 and abs(ideal_f_checked - 1) < 1e-6
                       and pr["supports_ok"]),
            unchecked_ancillas=0, checked_ancillas=int(checked_nm.num_qubits - self.level.width),
            unchecked_twoq=unchecked_twoq, checked_twoq=checked_twoq,
            added_twoq=checked_twoq - unchecked_twoq,
            unchecked_depth=unchecked_depth, checked_depth=checked_depth,
            added_depth=checked_depth - unchecked_depth,
            tradeoff_error_unchecked=tradeoff_unchecked, tradeoff_error_checked=tradeoff_checked,
            best_tradeoff_error=best_tradeoff, best_mode=better_mode,
            checked_T_sites=checked_sites, payload_T_sites=payload_sites,
        )
        self._tcache[key] = r
        self.t_history = [x for x in self.t_history if (x["t_req"], tuple(x["targets"])) != key] + [r]
        return r

