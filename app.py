import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.colors import qualitative
import streamlit as st
from engine import LEVELS, LevelSession, DEFAULT_SEED, T_COUNTS, T_MAX_CHECKS, MAX_STARS, error_metric

st.set_page_config(page_title="Spacetime Sentinel", layout="wide")
PAL = qualitative.Plotly
GREY = "#9aa0a6"


def is_dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return st.get_option("theme.base") == "dark"


# ======================= state =======================
def restart(seed):
    st.session_state.seed = int(seed)
    st.session_state.level = 0
    st.session_state.sessions = {}
    st.session_state.started = set()
    st.session_state.done = False
    st.rerun()


for k_, v_ in (("level", 0), ("sessions", {}), ("started", set()), ("done", False)):
    if k_ not in st.session_state:
        st.session_state[k_] = v_
if "seed" not in st.session_state:
    st.session_state.seed = random.randrange(10 ** 6)

base = st.session_state.seed
idx = st.session_state.level
L = LEVELS[idx]
key = (base, idx)


# ======================= the guide =======================
def guide():
    st.markdown("""
### What is this game about?
A quantum circuit, on real hardware makes mistakes, tends to accumulate errors. **Error detection** does not repair them. It adds a few
extra qubits (**ancillas**) that act like tripwires: if a mistake of the kind a tripwire watches for happens,
the ancilla flips and you **throw that measured shot away**. What remains is cleaner measurement results.
Your job is to place tripwires well, for the given constraints, i.e a limited number of available tripwires or ancillas.

### The setting
Each of the 5 levels uses a **one-dimensional brickwork random Clifford circuit** (the same family as the Qiskit
tutorial) on a chain of 3 to 7 qubits of a simulated IBM Heron chip. The game picks a low-error chain on the chip
and builds the noise model from the chip's calibration data. Only qubits that have a
free neighbouring ancilla on the chip can host a check, and you will see them marked in the hardware panel.

### How a level works
1. **Look at the hardware panel and the circuit** (free).
2. **Pick target qubits** among the available check sites. Each check costs one ancilla. **Order matters**: the
   library commits a check on the first target, then searches for the next given ordered choice.
3. **Preview (free, takes a few seconds).** Shows only cost: ancillas, two-qubit gates, depth, and whether the
   picker found every check you asked for. It does not tell you how good the result is.
4. **Run on hardware (costs 1 of your limited runs).** Gives measured fidelity and kept shots. The plot shows
   fidelity against kept shots, with the number of checks on each marker and one colour per run.
5. **Hint (costs 1 run, once per level) lets you know the baselines initial check placement.**
6. **Finish the level** to review remaining fault exposure, then do the **T-doping experiment**.

### The T-doping experiment
Real hard circuits need non-Clifford **T gates**, which the check cannot handle. The trick is to
put T gates only on wires where **a Z fault is undetected by every check**, so the checks still work and the
syndrome statistics do not change. The fidelity of the hard doped state cannot be measured directly, so we use a
conservative lower bound based on **F₂ ≥ F₁ − upper95(P(harmless | accept))**. Here upper95 is the one-sided 95%
upper confidence limit for the Monte Carlo estimate of the chance that an accepted fault is harmless for the Clifford
circuit (and might become harmful after doping). The circuits are small enough to also compute F₂ exactly, so you
can see whether the conservative bound holds and how loose it is.

### What the numbers mean
- **Fidelity (F):** estimated by averaging expectation values of randomly sampled stabilizers
  of the ideal state, using only the shots that passed every check.
- **Kept shots (K):** the fraction of shots that passed every check.
- **Score** = 100 × baseline error ÷ your error, where error = (1 − F) + 1/√(S·K) with S = 1000 raw shots.
  **Stars (maximum 4):** below 50 earns none; 50–<90 earns 1; 90–<100 earns 2; exactly matching the baseline (100) earns 3; beating it (>100) earns 4.

### Seeds
Every random choice (circuits, chain, stabilizers, picker, simulator, T sites) comes from one seed shown in the
sidebar. Type a number there and press *Apply seed* to replay the same game.

### Limitations
1. The noise is, taken from a fake backend
2. The picker is tuned to its own approximate model.
3. Fidelity is a sample estimate (stabilizer spread is shown).
4. Detection only: nothing is corrected.
5. The T experiment uses exact simulation, checks chosen by the library for the Clifford circuit, and noiseless T gates. Pruning is required to keep the exact simulation small, so only a few checks are used. The bound is conservative and may be loose.

*Open this page again any time from "How to play" in the left menu. Your progress is kept.*
""")


def get_session(i=None):
    i = idx if i is None else i
    k_ = (base, i)
    if k_ not in st.session_state.sessions:
        try:
            with st.spinner(f"Loading {LEVELS[i].name}: choosing a chain on the chip, building the noise model "
                            "and computing the baseline (can take a minute)..."):
                st.session_state.sessions[k_] = LevelSession(i, base)
        except Exception as e:
            st.error(f"Setup failed: {type(e).__name__}: {e}")
            st.stop()
    return st.session_state.sessions[k_]


def draw_circuit(qc):
    try:
        fig = qc.draw("mpl", fold=40, scale=0.5, style="iqp-dark" if is_dark() else "iqp")
    except Exception:
        try:
            fig = qc.draw("mpl", fold=40, scale=0.5)
        except Exception as e:
            st.error(f"Could not draw circuit ({type(e).__name__}: {e}).")
            return
    st.pyplot(fig)
    plt.close(fig)


# ======================= figures =======================
def frontier_fig(S, height=430):
    """Fidelity vs kept shots; marker labels = number of checks; one coloured line per run."""
    fig = go.Figure()
    for i, r in enumerate(S.history):
        m = r["marginal"]
        fig.add_trace(go.Scatter(
            x=[e["K"] for e in m], y=[e["F"] for e in m], mode="lines+markers+text",
            text=["" if e["k"] == 0 else str(e["k"]) for e in m], textposition="bottom center",
            name=f"Run {i + 1}: {r['used']}", line=dict(color=PAL[i % len(PAL)]),
            customdata=[[e["k"], e["error"]] for e in m],
            hovertemplate="%{customdata[0]} check(s)<br>K=%{x:.3f}<br>F=%{y:.3f}<br>error %{customdata[1]:.3f}"))
    fig.update_layout(xaxis=dict(title="kept-shot fraction (labels = number of checks)", autorange="reversed"),
                      yaxis_title="post-selected fidelity", height=height, margin=dict(t=20))
    return fig


def pareto_front(points):
    pts = sorted({(K, F) for K, F in points if F == F}, key=lambda p: (-p[0], -p[1]))
    front, best = [], -1e9
    for K, F in pts:
        if F > best:
            front.append((K, F))
            best = F
    return front


def pareto_fig(S):
    fig = frontier_fig(S, 420)
    pts = [(e["K"], e["F"]) for r in S.history for e in r["marginal"]]
    fr = pareto_front(pts)
    fig.add_trace(go.Scatter(x=[p[0] for p in fr], y=[p[1] for p in fr], mode="lines", name="Pareto frontier",
                             line=dict(color="#e63946", width=3, shape="linear")))
    return fig


def hardware_panel(S):
    n = S.level.width
    st.markdown(f"**Backend:** {S.backend.name} ({S.backend.num_qubits} qubits) &nbsp;|&nbsp; "
                f"**Chain (physical qubits):** {S.layout} &nbsp;|&nbsp; "
                f"**Gate noise:** {S.gn:.4f} &nbsp;|&nbsp; **Readout noise:** {S.ro:.4f}")
    if S.sites_note:
        st.caption(S.sites_note)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(n)), y=[0] * n, mode="lines+markers+text",
                             text=[f"q{i}<br>({p})" for i, p in enumerate(S.layout)], textposition="top center",
                             marker=dict(size=22, color="#2a9d8f"), line=dict(color=GREY), name="data qubit"))
    ax = [i for i in S.allowed if S.anc_phys[i] is not None]
    for i in ax:
        fig.add_trace(go.Scatter(x=[i, i], y=[0, -1], mode="lines", line=dict(color=GREY, dash="dot"),
                                 showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=ax, y=[-1] * len(ax), mode="markers+text",
                             text=[f"a({S.anc_phys[i]})" for i in ax], textposition="bottom center",
                             marker=dict(size=20, color="#f4a261"), name="free ancilla (check site)"))
    fig.update_layout(height=230, margin=dict(t=10, b=10), yaxis=dict(visible=False),
                      xaxis=dict(visible=False))
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Check sites you can target: {', '.join(f'q{i}' for i in S.allowed)}  "
               f"(ancilla budget {S.budget}). Noise comes from the backend's calibration data.")


def t_rows(S):
    out = []
    for r in S.t_history:
        out.append({"T placed": f"{r['T']} (asked {r['t_req']}, {r['avail']} legal sites)",
                    "checks": str(r["targets"]), "P(accept) Clifford → doped":
                    f"{r['p_clifford']:.3f} → {r['p_acc']:.3f}",
                    "F1 (Clifford)": round(r["F1"], 4),
                    "P(H|A) estimate / 95% upper": f"{r['PH']:.4f} / {r.get('PH_upper', float('nan')):.4f}",
                    "bound F1 − upper95(P(H|A))": round(r["bound"], 4), "exact F2": round(r["F2"], 4),
                    "bound holds": "yes" if r["holds"] else "NO",
                    "checks preserved": "yes" if r["valid"] else "WARNING"})
    return out



def t_comparison_rows(S, level_name=None):
    """Flatten T sweep results into comparable checked/unchecked configurations."""
    rows = []
    for r in S.t_history:
        # A restarted Streamlit process is recommended after updating both files; skip
        # legacy in-memory T rows that predate the full checked/unchecked comparison.
        if "F_no_checks" not in r or "tradeoff_error_checked" not in r:
            continue
        e_unchecked = float(r.get("tradeoff_error_unchecked", float("inf")))
        e_checked = float(r.get("tradeoff_error_checked", float("inf")))
        rows.append({
            "Level": level_name or S.level.name,
            "Width": S.level.width,
            "Payload depth setting (CZ layers)": S.level.depth,
            "T requested": int(r["t_req"]),
            "T placed": int(r["T"]),
            "Available matched T sites": int(r["avail"]),
            "Check placement": str(r["targets"]),
            "Checks inserted": int(r["k"]),
            "Ideal reference": r.get("ideal_reference", "Exact statevector of T-doped circuit"),
            "Ideal fidelity (no checks)": round(float(r.get("F_ideal_unchecked", 1.0)), 5),
            "Ideal fidelity (checks)": round(float(r.get("F_ideal_checked", 1.0)), 5),
            "T locations in payload (instruction, qubit)": str(r.get("payload_T_sites", [])),
            "T locations in checked circuit (instruction, qubit)": str(r.get("checked_T_sites", [])),
            "No-check fidelity": round(float(r["F_no_checks"]), 5),
            "No-check kept shots (%)": round(100 * float(r["K_no_checks"]), 2),
            "No-check ancillas": int(r["unchecked_ancillas"]),
            "No-check 2Q gates": int(r["unchecked_twoq"]),
            "No-check depth": int(r["unchecked_depth"]),
            "Post-selected fidelity": round(float(r["F2"]), 5),
            "Kept shots with checks (%)": round(100 * float(r["p_acc"]), 2),
            "Checked ancillas": int(r["checked_ancillas"]),
            "Checked 2Q gates": int(r["checked_twoq"]),
            "Checked depth": int(r["checked_depth"]),
            "Added ancillas": int(r["checked_ancillas"] - r["unchecked_ancillas"]),
            "Added 2Q gates": int(r["added_twoq"]),
            "Added depth": int(r["added_depth"]),
            "Trade-off error (no checks)": round(e_unchecked, 6),
            "Trade-off error (checks)": round(e_checked, 6),
            "Better choice for this T count": r.get("best_mode", "—"),
            "Best trade-off error": round(float(r.get("best_tradeoff_error", min(e_unchecked, e_checked))), 6),
            "Checks preserved": "yes" if r.get("valid") else "WARNING",
        })
    if rows:
        best_index = min(range(len(rows)), key=lambda i: rows[i]["Best trade-off error"])
        for i, row in enumerate(rows):
            row["Best trade-off in level"] = "BEST" if i == best_index else ""
    return sorted(rows, key=lambda row: (row["T requested"], row["Check placement"]))


def render_t_grouped_views(rows, key_prefix):
    """Show aggregated comparisons by T count, realized circuit depth, and check placement."""
    if not rows:
        st.info("Run a T-gate sweep to populate the comparison tables.")
        return
    df = pd.DataFrame(rows)
    tabs = st.tabs(["Grouped by T count", "Grouped by circuit depth", "Grouped by check placement"])
    with tabs[0]:
        by_t = df.groupby(["Level", "T requested", "T placed"], dropna=False).agg(
            Configurations=("Check placement", "count"),
            Mean_no_check_fidelity=("No-check fidelity", "mean"),
            Mean_checked_fidelity=("Post-selected fidelity", "mean"),
            Mean_checked_kept_percent=("Kept shots with checks (%)", "mean"),
            Best_tradeoff_error=("Best trade-off error", "min"),
        ).reset_index().rename(columns={
            "Mean_no_check_fidelity": "Mean no-check fidelity",
            "Mean_checked_fidelity": "Mean post-selected fidelity",
            "Mean_checked_kept_percent": "Mean kept shots with checks (%)",
            "Best_tradeoff_error": "Best trade-off error (lower is better)",
        })
        st.dataframe(by_t.round(5), width="stretch", hide_index=True, key=f"{key_prefix}_by_t")
    with tabs[1]:
        by_depth = df.groupby(["Level", "Payload depth setting (CZ layers)", "No-check depth", "Checked depth"],
                              dropna=False).agg(
            Configurations=("T placed", "count"),
            T_counts=("T placed", lambda x: ", ".join(map(str, sorted(set(x))))),
            Mean_no_check_fidelity=("No-check fidelity", "mean"),
            Mean_checked_fidelity=("Post-selected fidelity", "mean"),
            Mean_checked_kept_percent=("Kept shots with checks (%)", "mean"),
            Best_tradeoff_error=("Best trade-off error", "min"),
        ).reset_index().rename(columns={
            "Payload depth setting (CZ layers)": "Payload depth setting (CZ layers)",
            "Mean_no_check_fidelity": "Mean no-check fidelity",
            "Mean_checked_fidelity": "Mean post-selected fidelity",
            "Mean_checked_kept_percent": "Mean kept shots with checks (%)",
            "Best_tradeoff_error": "Best trade-off error (lower is better)",
        })
        st.dataframe(by_depth.round(5), width="stretch", hide_index=True, key=f"{key_prefix}_by_depth")
    with tabs[2]:
        by_placement = df.groupby(["Level", "Check placement", "Checks inserted"], dropna=False).agg(
            T_configurations=("T placed", "count"),
            T_counts=("T placed", lambda x: ", ".join(map(str, sorted(set(x))))),
            Mean_no_check_fidelity=("No-check fidelity", "mean"),
            Mean_checked_fidelity=("Post-selected fidelity", "mean"),
            Mean_checked_kept_percent=("Kept shots with checks (%)", "mean"),
            Best_tradeoff_error=("Best trade-off error", "min"),
        ).reset_index().rename(columns={
            "Mean_no_check_fidelity": "Mean no-check fidelity",
            "Mean_checked_fidelity": "Mean post-selected fidelity",
            "Mean_checked_kept_percent": "Mean kept shots with checks (%)",
            "Best_tradeoff_error": "Best trade-off error (lower is better)",
        })
        st.dataframe(by_placement.round(5), width="stretch", hide_index=True, key=f"{key_prefix}_by_placement")

def t_fig(S):
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Exact F2 and the lower bound", "Acceptance probability"))
    groups = {}
    for r in S.t_history:
        groups.setdefault(tuple(r["targets"]), []).append(r)
    for gi, (tg, rs) in enumerate(groups.items()):
        rs = sorted(rs, key=lambda r: r["T"])
        col, name = PAL[gi % len(PAL)], f"checks {list(tg)}"
        fig.add_trace(go.Scatter(x=[r["T"] for r in rs], y=[r["F2"] for r in rs], mode="lines+markers",
                                 name=f"{name}: exact F2", line=dict(color=col), legendgroup=name), row=1, col=1)
        fig.add_trace(go.Scatter(x=[r["T"] for r in rs], y=[r["bound"] for r in rs], mode="lines",
                                 name=f"{name}: bound", line=dict(color=col, dash="dash"), legendgroup=name),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=[r["T"] for r in rs], y=[r["p_acc"] for r in rs], mode="lines+markers",
                                 name=name, line=dict(color=col), legendgroup=name, showlegend=False),
                      row=1, col=2)
    fig.update_xaxes(title_text="T gates placed", dtick=1)
    fig.update_layout(height=340, margin=dict(t=40))
    return fig


# ======================= T stage UI =======================
def t_stage(S):
    st.subheader("T-gate experiment: lower-bounding the fidelity of a hard state")
    st.write("T gates are placed only on wires where a Z fault is undetected by every check, so the checks are intended to remain valid. "
             "The conservative bound uses **F₂ ≥ F₁ − upper95(P(harmless | accept))**. The exact T-state comparison uses density-matrix simulation with the configured two-qubit depolarizing noise and a statevector target; readout errors are not included in this exact T-state-fidelity calculation. "
             f"(At most {T_MAX_CHECKS} checks, to keep the exact simulation small.)")
    best_run = S.best()
    best_targets = [t for t in (best_run["used"] if best_run else S.t_default_targets()) if t in S.allowed]
    default = best_targets[:T_MAX_CHECKS]
    if best_run:
        st.caption(f"Best-scoring case: score {best_run['score']:.1f}, checks {best_run['used']}. "
                   "The dedicated sweep below uses this case's checks for every T-gate count.")
    else:
        st.caption("No scored run is available yet; the sweep will use the default check placement.")
    anc = st.multiselect("Checks to use (target qubits)", S.allowed, default=default,
                         max_selections=T_MAX_CHECKS, key=f"tanc_{key}")
    tsel = st.select_slider("Number of T gates", options=T_COUNTS, key=f"tsel_{key}")
    b1, b2, b3 = st.columns(3)
    go1 = b1.button("Run T experiment", key=f"trun_{key}", type="primary", width="stretch", disabled=not anc)
    go2 = b2.button("Sweep selected checks", key=f"tsweep_{key}", width="stretch", disabled=not anc)
    go_best = b3.button("Sweep best-scoring case", key=f"tsweepbest_{key}", width="stretch",
                        disabled=not best_targets)
    try:
        if go1 or go2 or go_best:
            sweep_targets = best_targets if go_best else anc
            sweep_counts = T_COUNTS if (go2 or go_best) else [tsel]
            with st.spinner("Choosing T sites, simulating exactly and estimating P(harmless | accept). "
                            "A full sweep can take longer..."):
                for t in sweep_counts:
                    S.run_t(t, sweep_targets)
            st.rerun()
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")
    if S.t_history:
        if any(not r["valid"] for r in S.t_history):
            st.warning("For at least one run the noiseless doped circuit did not keep every shot, so the T sites "
                       "or syndrome observables do not preserve the checks as assumed. Treat those rows with "
                       "caution.")
        if any(not r["holds"] for r in S.t_history):
            st.warning("The bound was violated in at least one row. That should not happen; it points to a bug "
                       "or to a violated assumption (see the limits).")
        st.dataframe(t_rows(S), width="stretch", hide_index=True)
        comp_rows = t_comparison_rows(S, S.level.name)
        st.subheader("Complete T-doping comparison")
        st.caption("Each row is a matched unchecked/checked pair. The ideal target is the statevector of that same T-doped payload. "
                   "The lower trade-off error wins: (1 − F) + 1/√(1000·K), so fidelity is always considered alongside retained shots.")
        st.dataframe(comp_rows, width="stretch", hide_index=True)
        if comp_rows:
            best_row = next((row for row in comp_rows if row["Best trade-off in level"] == "BEST"), None)
            if best_row:
                st.success(f"Best trade-off for {S.level.name}: T={best_row['T placed']} (requested {best_row['T requested']}), "
                           f"checks {best_row['Check placement']}, choose {best_row['Better choice for this T count']} "
                           f"(objective {best_row['Best trade-off error']:.5f}).")
        st.plotly_chart(t_fig(S), width="stretch")
        st.caption("Dashed line: conservative lower bound using the one-sided 95% upper confidence limit for P(H|A). "
                   "Solid line: exact post-selected fidelity. The comparison table also reports unchecked noisy fidelity and costs.")
    elif not S.t_skipped:
        if st.button("Skip the T experiment", key=f"tskip_{key}"):
            S.t_skipped = True
            st.rerun()


# ======================= dashboard =======================
def dashboard():
    st.title("Final dashboard")
    st.caption(f"Seed {base}. Enter this seed to replay the same game.")
    rows, runs_rows, t_all, t_compare_all = [], [], [], []
    for i, Lv in enumerate(LEVELS):
        S = st.session_state.sessions.get((base, i))
        if S is None:
            continue
        b = S.best()
        rows.append({"level": Lv.name, "width": Lv.width, "backend": S.backend.name, "chain": str(S.layout),
                     "gate noise": round(S.gn, 4),
                     "best score": round(b["score"]) if b else "-", "stars": b["stars"] if b else 0,
                     "runs": len(S.history), "hint": "yes" if S.hint_used else "no", "T runs": len(S.t_history)})
        for j, r in enumerate(S.history):
            runs_rows.append({"level": Lv.name, "run": j + 1, "targets": str(r["used"]), "checks": r["k"],
                              "F": round(r["F"], 4), "K": round(r["K"], 4), "2q gates": round(r["twoq"]),
                              "depth": r["depth"], "score": round(r["score"], 1), "stars": r["stars"]})
        for r in t_rows(S):
            t_all.append({"level": Lv.name, **r})
        t_compare_all.extend(t_comparison_rows(S, Lv.name))
    st.subheader("Summary")
    st.dataframe(rows, width="stretch", hide_index=True)
    st.metric("Total stars", f"{sum(r['stars'] for r in rows)} / {MAX_STARS * len(LEVELS)}")

    tabs = st.tabs([Lv.name for Lv in LEVELS])
    for i, tab in enumerate(tabs):
        S = st.session_state.sessions.get((base, i))
        with tab:
            if S is None:
                st.write("Not played.")
                continue
            hardware_panel(S)
            st.markdown("**Pareto plot: fidelity vs kept shots**")
            st.plotly_chart(pareto_fig(S), width="stretch")
            if S.history:
                st.markdown("**Runs**")
                st.dataframe([r for r in runs_rows if r["level"] == LEVELS[i].name],
                             width="stretch", hide_index=True)
            if S.t_history:
                st.markdown("**T-gate experiment**")
                st.dataframe(t_rows(S), width="stretch", hide_index=True)
                st.plotly_chart(t_fig(S), width="stretch")
            else:
                st.caption("No T-gate runs for this level.")
    if t_compare_all:
        st.subheader("Unified T-doping comparison across configurations")
        st.caption("Rows retain each T count, circuit depth, and check placement. The best row per level is marked BEST; compare the grouped views below. "
                   "Trade-off error = (1 − F) + 1/√(1000·K), lower is better. Unchecked rows retain 100% of shots by design.")
        st.dataframe(t_compare_all, width="stretch", hide_index=True)
        render_t_grouped_views(t_compare_all, f"unified_{base}")

    d1, d2, d3 = st.columns(3)
    d1.download_button("Download all runs (CSV)", pd.DataFrame(runs_rows).to_csv(index=False),
                       file_name=f"runs_seed{base}.csv", mime="text/csv")
    d2.download_button("Download T bound results (CSV)", pd.DataFrame(t_all).to_csv(index=False),
                       file_name=f"t_bound_runs_seed{base}.csv", mime="text/csv")
    d3.download_button("Download full T comparison (CSV)", pd.DataFrame(t_compare_all).to_csv(index=False),
                       file_name=f"t_doping_comparison_seed{base}.csv", mime="text/csv")
    st.subheader("Play again")
    r1, r2, r3 = st.columns(3)
    if r1.button("Restart with the same seed", width="stretch"):
        restart(base)
    if r2.button("Restart with a new random seed", width="stretch"):
        restart(random.randrange(10 ** 6))
    txt = r3.text_input("Or choose a seed", key="dash_seed", placeholder="integer")
    if r3.button("Restart with this seed", width="stretch"):
        try:
            restart(int(txt))
        except ValueError:
            st.error("Seed must be an integer.")


# ======================= pages =======================
def intro_page():
    st.title("Spacetime Code Sentinel - by RandomQubits")
    st.caption(f"Current level: {L.name}  |  seed: {base}")
    guide()
    st.divider()
    if st.session_state.done:
        st.info("The game is finished. Open the Game page for your dashboard.")
        return
    get_session()
    started = key in st.session_state.started
    st.success(f"{L.name} is loaded and ready.")
    if st.button("Back to the game" if started else "Click to play", type="primary"):
        st.session_state.started.add(key)
        st.switch_page(game_pg)


def show_preview(S, targets):
    kt = tuple(targets)
    if kt not in S._cache:
        st.caption("Press **Preview (free)** to see what this placement costs before spending a run.")
        return
    objs, rows = S.prep(targets)
    k = len(rows) - 1
    st.markdown(f"**Preview for {' → '.join(f'q{t}' for t in targets)}**: cost only, nothing simulated")
    if k < len(targets):
        st.warning(f"The picker found only {k} valid check(s) of the {len(targets)} requested.")
    else:
        st.success(f"The picker found all {k} requested check(s).")
    c = st.columns(3)
    c[0].metric("Ancillas added", rows[-1]["ancillas"])
    c[1].metric("Two-qubit gates", rows[-1]["twoq"], f"{rows[-1]['twoq'] - rows[0]['twoq']:+d}", delta_color="inverse")
    c[2].metric("Circuit depth", rows[-1]["depth"], f"{rows[-1]['depth'] - rows[0]['depth']:+d}", delta_color="inverse")
    st.caption("Cost (for the first sampled stabilizer circuit) is not quality. Only a run tells you how well the "
               "checks work.")


def game_page():
    if st.session_state.done:
        dashboard()
        return
    if key not in st.session_state.started:
        st.title("Spacetime Code Sentinel - by RandomQubits")
        st.caption(f"Loading {L.name}. Read the guide below while it loads.")
        guide()
        st.divider()
        get_session()
        st.success(f"{L.name} is loaded and ready.")
        if st.button("Click to play", type="primary"):
            st.session_state.started.add(key)
            st.rerun()
        st.stop()

    S = get_session()
    b, n = S.baseline, L.width
    st.header(f"{L.name}  ({idx + 1} of {len(LEVELS)})")
    st.caption(L.lesson)
    c = st.columns(5)
    c[0].metric("Width", n)
    c[1].metric("Brickwork depth", L.depth)
    c[2].metric("Ancilla budget", S.budget)
    c[3].metric("Hardware runs left", S.runs_left)
    c[4].metric("Payload CZ gates", S.payload_twoq)
    st.info(f"No checks: fidelity {b['F']:.3f}, 100% of shots kept.")
    if S.hint_text:
        st.warning(f"Hint: {S.hint_text}")

    with st.expander("Hardware: backend, chain and check sites", expanded=True):
        hardware_panel(S)
    with st.expander("View the payload circuit"):
        st.write("CZ gates touching each qubit: " + ", ".join(f"q{q}: {v}" for q, v in S.payload_load().items()))
        st.caption("A one-dimensional brickwork random Clifford circuit, as in the Qiskit tutorial.")
        draw_circuit(S.circ)

    # ---------- place checks ----------
    st.subheader("Place checks")
    st.write("Pick target qubits among the available check sites. **Order matters**: the library commits a check "
             "on the first target, then searches for the next given that choice.")
    targets = st.multiselect("Target qubits", S.allowed, max_selections=S.budget,
                             format_func=lambda q: f"q{q} (chip qubit {S.layout[q]})")
    if targets:
        st.caption(f"Order used: {' → '.join(f'q{t}' for t in targets)}")
    b1, b2, b3 = st.columns(3)
    do_prev = b1.button("Preview (free)", disabled=not targets, width="stretch")
    do_run = b2.button("Run on hardware (uses 1 run)", type="primary", width="stretch",
                       disabled=S.runs_left <= 0 or not targets or S.finished)
    do_hint = b3.button("Hint (uses 1 run)", width="stretch",
                        disabled=S.runs_left < 2 or bool(S.hint_text) or S.finished)
    try:
        if do_prev:
            with st.spinner("Asking the check picker..."):
                S.prep(targets)
        if do_run:
            with st.spinner("Running on hardware..."):
                S.run(targets)
            st.rerun()
        if do_hint:
            S.use_hint()
            st.rerun()
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")
    if targets:
        show_preview(S, targets)

    # ---------- latest run ----------
    last = S.history[-1] if S.history else None
    if last:
        st.subheader("Latest run")
        st.success(f"Score {last['score']:.0f}  |  {'★' * last['stars']}{'☆' * (MAX_STARS - last['stars'])}  "
                   f"({last['seconds']:.0f} s)")
        result_cols = st.columns(3)
        result_cols[0].metric("Result fidelity", f"{last['F']:.3f}")
        result_cols[1].metric("Kept shots", f"{last['K'] * 100:.1f}%")
        result_cols[2].metric("Remaining undetected fault types", f"{last['unc_total']:.0f}")
        st.markdown("**Remaining exposure by qubit**")
        remaining = last["unc_by_qubit"]
        st.dataframe([{"Qubit": f"q{q}", "Undetected fault types remaining": round(remaining[q], 2)}
                      for q in range(n)], width="stretch", hide_index=True)
        with st.expander("Effect of each added check", expanded=True):
            check_rows = []
            previous = None
            for m in last["marginal"]:
                if m["k"] == 0:
                    previous = m
                    continue
                fidelity_increase = (m["F"] - previous["F"]) * 100 if previous else 0.0
                shots_lost = ((previous["K"] - m["K"]) / previous["K"] * 100
                              if previous and previous["K"] > 0 else 0.0)
                check_rows.append({
                    "Check added": m["k"],
                    "Fidelity increase (percentage points)": round(fidelity_increase, 2),
                    "Shots lost (%)": round(shots_lost, 2),
                })
                previous = m
            st.dataframe(check_rows, width="stretch", hide_index=True)

    # ---------- frontier ----------
    st.subheader("Fidelity vs kept shots")
    st.caption("One coloured line per run; the labels on the markers are the number of checks.")
    st.plotly_chart(frontier_fig(S), width="stretch")

    # ---------- coverage + inspect ----------
    def run_label(i, r):
        return f"Run {i + 1}: targets {r['used']} (k={r['k']}, score {r['score']:.0f})"

    options = {"No checks": b}
    for i, r in enumerate(S.history):
        options[run_label(i, r)] = r
    names = list(options)
    if S.history:
        st.subheader("Coverage after your runs")
        st.caption("Bars: fault types no check can detect, averaged over the sampled stabilizer circuits. Checks add "
                   "gates, so read this as where the exposure is, not an exact percentage.")
        chosen = st.multiselect("Runs to compare", names, default=["No checks", names[-1]])
        fc = go.Figure()
        for name in chosen:
            d = options[name]["unc_by_qubit"]
            fc.add_trace(go.Bar(x=[f"q{q}" for q in range(n)], y=[d[q] for q in range(n)], name=name))
        fc.update_layout(barmode="group", yaxis_title="undetected fault types", height=320, margin=dict(t=20))
        st.plotly_chart(fc, width="stretch")

        st.subheader("Inspect a run")
        sel = st.selectbox("Run", names, index=len(names) - 1)
        r = options[sel]
        m = st.columns(4)
        m[0].metric("Fidelity", f"{r['F']:.3f}")
        m[1].metric("Kept shots", f"{r['K']:.3f}")
        m[2].metric("Two-qubit gates", f"{r['twoq']:.0f}")
        m[3].metric("Undetected fault types", f"{r['unc_total']:.0f}")
        st.markdown("**Remaining exposure by qubit**")
        exposure = r["unc_by_qubit"]
        st.dataframe([{"Qubit": f"q{q}", "Undetected fault types remaining": round(exposure[q], 2)}
                      for q in range(n)], width="stretch", hide_index=True)
        bins = 30
        grid = np.zeros((n, bins))
        for q, pos in r["unc_cells"]:
            grid[q, min(bins - 1, pos * bins // (r["n_inst"] + 1))] += 1
        fh2 = go.Figure(go.Heatmap(z=grid, y=[f"q{q}" for q in range(n)], colorscale="Reds",
                                   colorbar=dict(title="undetected")))
        fh2.update_layout(xaxis_title="position in the first sampled stabilizer circuit (early → late)",
                          height=300, margin=dict(t=20))
        st.plotly_chart(fh2, width="stretch")
        if "circuit" in r:
            with st.expander("Checked circuit for this run (first sampled stabilizer)"):
                st.caption(f"{r['ancillas']} ancilla(s) added; depth {r['depth']}.")
                draw_circuit(r["circuit"])
        st.subheader("Your runs")
        cols_show = ("used", "k", "F", "K", "twoq", "depth", "ancillas", "score", "stars")
        st.dataframe([{k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in rr.items() if k_ in cols_show}
                      for rr in S.history], width="stretch")

    # ---------- finish ----------
    st.subheader("Finish")
    if S.runs_left == 0 or S.finished:
        S.finished = True
        best = S.best()
        st.markdown("#### Level summary")
        if best is None:
            st.write("You did not run anything this level.")
        else:
            st.dataframe([
                {"": "You (best run)", "targets": str(best["used"]), "checks": best["k"],
                 "F": round(best["F"], 3), "K": round(best["K"], 3), "score": round(best["score"])},
                {"": "No checks", "targets": "[]", "checks": 0, "F": round(b["F"], 3), "K": round(b["K"], 3),
                 "score": round(100 * S.par["error"] / b["error"])}], width="stretch", hide_index=True)
            st.write(f"Stars: {'★' * best['stars']}{'☆' * (MAX_STARS - best['stars'])}")

        t_stage(S)

        if not (bool(S.t_history) or S.t_skipped):
            st.caption("Run at least one T experiment (or skip it) to continue.")
        elif idx < len(LEVELS) - 1:
            if st.button("Next level →", type="primary"):
                st.session_state.level += 1
                st.rerun()
        else:
            if st.button("See the final dashboard →", type="primary"):
                st.session_state.done = True
                st.balloons()
                st.rerun()
    else:
        st.caption("Use your runs, or finish early to unlock the T experiment.")
        if st.button("Finish level"):
            S.finished = True
            st.rerun()

    with st.expander("How the score works"):
        st.write(f"error = (1 − F) + 1/√(S·K) with S = 1000 raw shots. F is the average post-selected expectation "
                 f"value of {len(S.stabs)} randomly sampled stabilizers. Score = 100 × reference error / run error. "
                 "Stars: below 50 = 0; 50–<90 = 1; 90–<100 = 2; exactly matching the reference (100) = 3; beating it (>100) = 4. "
                 "The objective balances infidelity and shot retention.")
    st.caption("Limits: coverage counts are estimates; fidelity differences within the stabilizer-sampling spread "
               "are noise; this is a simulated, depolarizing-noise sandbox.")


# ======================= sidebar and navigation =======================
st.sidebar.markdown(f"**Seed: {base}**")
st.sidebar.text_input("Set a seed (integer)", key="seed_text", placeholder="blank = keep current")
c1, c2 = st.sidebar.columns(2)
if c1.button("Apply seed"):
    try:
        restart(int(st.session_state.get("seed_text", "").strip()))
    except ValueError:
        st.sidebar.error("Seed must be an integer.")
if c2.button("Random seed"):
    restart(random.randrange(10 ** 6))
st.sidebar.caption("Applying a seed restarts the game. The same seed gives the same game.")
st.sidebar.markdown(f"**Level {idx + 1} of {len(LEVELS)}**: {L.name}")
if not st.session_state.done and st.sidebar.button("Reset this level"):
    st.session_state.sessions.pop(key, None)
    st.rerun()
if st.sidebar.button("Restart from level 1 (same seed)"):
    restart(base)

intro_pg = st.Page(intro_page, title="How to play", icon="📖", default=True)
game_pg = st.Page(game_page, title="Game", icon="🎮")
pg = st.navigation([intro_pg, game_pg])
pg.run()