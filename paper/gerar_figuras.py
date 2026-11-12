"""Gera as figuras do projeto de pesquisa a partir de results/ do EvoPolicy-SDD v0.2.0.

Se existirem resultados com LLM (``evopolicy mutate --semantic`` e
``evopolicy llm-benchmark``), as figuras de mutação incluem o nível L4 e é
gerada a figura do benchmark com LLM. Para reproduzir sem chave de API:
``evopolicy mutate --semantic --offline --cache llm_cache/claude.json``.
"""
import csv, sys, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

RES, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
LIGHT = "#f0efec"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "savefig.bbox": "tight", "savefig.dpi": 300,
})
from matplotlib.ticker import FuncFormatter
BR = FuncFormatter(lambda v, _: (f"{v:.1f}" if v % 1 else f"{v:.0f}").replace(".", ","))
br = lambda v: f"{v:.2f}".replace(".", ",")
LV = {"L0_sem_verificacao": "L0\nsem verificação", "L1_versao": "L1\nversão",
      "L2_estrutural": "L2\nestrutural", "L3_completa": "L3\ncompleta",
      "L4_semantica": "L4\nsemântica (LLM)"}
HAS_LLM = os.path.exists(os.path.join(RES, "mutation_llm_summary.csv"))
MUT = "mutation_llm" if HAS_LLM else "mutation"

def rows(name):
    with open(os.path.join(RES, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"))
    plt.close(fig)

def bar_label(ax, bars, fmt):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt(h), (b.get_x() + b.get_width() / 2, h), xytext=(0, 2),
                    textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK)

# ---------- Figura 1: sensibilidade e taxa de alarme falso por nível ----------
ms = rows(f"{MUT}_summary.csv")
labels = [LV[r["level"]] for r in ms]
sens = [float(r["sensitivity"]) for r in ms]
far = [float(r["false_alarm_rate"]) for r in ms]
tp = [int(r["tp"]) for r in ms]; fp = [int(r["fp"]) for r in ms]
fig, ax = plt.subplots(figsize=(6.6, 3.0))
x = range(len(labels)); w = 0.36
b1 = ax.bar([i - w/2 - 0.01 for i in x], sens, w, color=BLUE, label="Sensibilidade (derivas detectadas / 12)")
b2 = ax.bar([i + w/2 + 0.01 for i in x], far, w, color=ORANGE, label="Taxa de alarme falso (benignas bloqueadas / 6)")
for b, k in zip(b1, tp):
    ax.annotate(f"{br(b.get_height())}\n({k}/12)", (b.get_x()+b.get_width()/2, b.get_height()), xytext=(0, 2),
                textcoords="offset points", ha="center", va="bottom", fontsize=7, color=INK)
for b, k in zip(b2, fp):
    ax.annotate(f"{br(b.get_height())}\n({k}/6)", (b.get_x()+b.get_width()/2, b.get_height()), xytext=(0, 2),
                textcoords="offset points", ha="center", va="bottom", fontsize=7, color=INK)
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_ylim(0, 1.15); ax.set_ylabel("Proporção"); ax.yaxis.set_major_formatter(BR)
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, loc="upper left", fontsize=7.5)
save(fig, "fig_sensibilidade_niveis")

# ---------- Figura 2: matriz de detecção mutante x nível ----------
mo = rows(f"{MUT}_observations.csv")
muts = sorted({r["mutation"] for r in mo}, key=lambda m: (m[0] != "M", m))
levels = [r["level"] for r in ms]
det = {(r["mutation"], r["level"]): r for r in mo}
fig, ax = plt.subplots(figsize=(6.4, 0.6 * len(levels) + 0.6))
ax.grid(False)
for j, m in enumerate(muts):
    for i, lv in enumerate(levels):
        r = det[(m, lv)]
        detected = r["detected"] == "True"; drift = r["drift"] == "True"
        if drift:
            color = BLUE if detected else LIGHT     # verdadeiro positivo / falso negativo
        else:
            color = ORANGE if detected else LIGHT   # falso positivo / verdadeiro negativo
        ax.add_patch(plt.Rectangle((j + 0.04, i + 0.06), 0.92, 0.88, color=color, linewidth=0))
        if detected and lv == "L3_completa":
            pass
ax.set_xlim(0, len(muts)); ax.set_ylim(0, len(levels))
ax.set_xticks([j + 0.5 for j in range(len(muts))]); ax.set_xticklabels(muts, rotation=90, fontsize=7.5)
ax.set_yticks([i + 0.5 for i in range(len(levels))]); ax.set_yticklabels([LV[l].replace("\n", " ") for l in levels], fontsize=7.5)
ax.invert_yaxis()
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
ax.axvline(12, color=INK2, linewidth=1.0)
ax.text(6, -0.25, "12 mutações com deriva (M01–M12)", ha="center", fontsize=7.5, color=INK2)
ax.text(15, -0.25, "6 mudanças benignas", ha="center", fontsize=7.5, color=INK2)
ax.legend(handles=[Patch(color=BLUE, label="Deriva detectada (VP)"),
                   Patch(color=ORANGE, label="Benigna bloqueada (FP)"),
                   Patch(color=LIGHT, label="Não sinalizado (FN em derivas, VN em benignas)")],
          frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=7)
save(fig, "fig_matriz_deteccao")

# ---------- Figura 3: impacto operacional por nível (small multiples) ----------
metrics = [("emitted_wrong", "Decisões erradas emitidas"),
           ("emitted_divergent_evidence", "Decisões emitidas com\nevidência divergente"),
           ("blocked_benign_decisions", "Decisões bloqueadas em\nmudanças benignas")]
fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.6))
short = [r["level"][:2] for r in ms]
for ax, (k, title) in zip(axes, metrics):
    vals = [int(r[k] or 0) for r in ms]
    bars = ax.bar(short, vals, 0.6, color=BLUE if k != "blocked_benign_decisions" else ORANGE)
    bar_label(ax, bars, lambda h: f"{int(h)}")
    ax.set_title(title, fontsize=8, color=INK)
    ax.set_ylim(0, max(vals) * 1.2 if max(vals) else 1)
    ax.grid(axis="x", visible=False)
fig.tight_layout()
save(fig, "fig_impacto_operacional")

# ---------- Figura 4: benchmark das cinco condições ----------
sm = rows("summary.csv")
cond = {"B1_hibrido_desatualizado": "B1\nregras v1\ndocs v1",
        "B2_hibrido_atualizado": "B2\nregras v2\ndocs v2",
        "B3_hibrido_documento_antigo": "B3\nregras v2\ndocs v1",
        "P1_sdd_sincronizado": "P1 (SDD)\nregras v2\ndocs v2",
        "P2_sdd_documento_antigo": "P2 (SDD)\nregras v2\ndocs v1"}
acc = [float(r["accuracy"]) for r in sm]
blk = [float(r["block_rate"]) for r in sm]
inv = [int(r["invalid_evidence"]) / int(r["n"]) for r in sm]
fig, ax = plt.subplots(figsize=(6.6, 3.0))
x = list(range(len(sm))); w = 0.26
series = [(acc, BLUE, "Acurácia (bloqueio conta como erro)"),
          (inv, ORANGE, "Decisões com evidência inválida / casos"),
          (blk, AQUA, "Taxa de bloqueio")]
for s, (vals, c, lab) in enumerate(series):
    bars = ax.bar([i + (s - 1) * (w + 0.02) for i in x], vals, w, color=c, label=lab)
    bar_label(ax, bars, lambda h: br(h))
ax.set_xticks(x); ax.set_xticklabels([cond[r["condition"]] for r in sm], fontsize=7.5)
ax.set_ylim(0, 1.22); ax.set_ylabel("Proporção (n = 18 casos)"); ax.yaxis.set_major_formatter(BR)
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=3, fontsize=7)
save(fig, "fig_benchmark_condicoes")

# ---------- Figura 5: benchmark com LLM real (B1 x P) ----------
if os.path.exists(os.path.join(RES, "llm_summary.csv")):
    import json
    model = json.load(open(os.path.join(RES, "llm_summary.json"), encoding="utf-8"))["model"]
    ls = rows("llm_summary.csv")
    names = {("docs_v2", "B1_llm_decide"): "B1: LLM decide\ndocs v2",
             ("docs_v2", "P_sdd_llm_explica"): "P: SDD decide\ndocs v2",
             ("docs_v1_antigos", "B1_llm_decide"): "B1: LLM decide\ndocs v1 (antigos)",
             ("docs_v1_antigos", "P_sdd_llm_explica"): "P: SDD decide\ndocs v1 (antigos)"}
    fig, ax = plt.subplots(figsize=(6.6, 2.9))
    xs = list(range(len(ls)))
    ok = [int(r["emitted_correct"]) for r in ls]
    wr = [int(r["emitted_wrong"]) for r in ls]
    bl = [int(r["blocked"]) for r in ls]
    for vals, base, c, lab in ((ok, [0]*len(ls), BLUE, "Decisão correta emitida"),
                               (wr, ok, ORANGE, "Decisão errada emitida"),
                               (bl, [a+b for a, b in zip(ok, wr)], LIGHT, "Bloqueada (fail-closed)")):
        bars = ax.bar(xs, vals, 0.55, bottom=base, color=c, label=lab,
                      edgecolor=INK2 if c == LIGHT else c,
                      linewidth=[0.6 if v else 0 for v in vals])
        for b, v, b0 in zip(bars, vals, base):
            if v:
                ax.text(b.get_x() + b.get_width()/2, b0 + v/2, str(v), ha="center", va="center",
                        fontsize=7.5, color="white" if c != LIGHT else INK)
    ax.set_xticks(xs); ax.set_xticklabels([names[(r["scenario"], r["condition"])] for r in ls], fontsize=7.5)
    ax.set_ylim(0, 21); ax.set_ylabel("Casos (n = 18)")
    ax.text(1.0, -0.3, f"Modelo: {model}", transform=ax.transAxes, ha="right", fontsize=7, color=INK2)
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3, fontsize=7)
    save(fig, "fig_llm_benchmark")
print("ok")
