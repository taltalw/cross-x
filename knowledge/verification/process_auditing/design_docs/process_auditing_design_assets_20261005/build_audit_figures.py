"""Compute descriptive process statistics and figures from existing outputs."""

from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ASSETS = Path(__file__).resolve().parent
ROOT = ASSETS.parent
OUTPUTS = ROOT / "cross-x/knowledge/pipielines_v4/outputs"
DOMAINS = ["chemistry", "computer_science", "financial", "geography",
           "legal", "mathematics", "medical"]
LABELS = ["Chem", "CS", "Fin", "Geo", "Law", "Math", "Med"]
COUNTS = [2, 3, 4]
COLORS = ["#2676b8", "#e78b2f", "#34916c"]


def read_rows(stage):
    """Yield records from the given stage in a reproducible file order."""
    for path in sorted((OUTPUTS / stage).glob("*/*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def entropy(counter, size):
    """Return Shannon entropy normalized by a fixed support size."""
    total = sum(counter.values())
    assert total > 0 and size > 1
    return -sum((n / total) * math.log(n / total)
                for n in counter.values()) / math.log(size)


plans = defaultdict(list)
for row in read_rows("1_generate_fusion_plans"):
    plans[row["source_domain"], row["domain_count"]].append(row)
assert len(plans) == 21 and all(len(group) == 100 for group in plans.values())
summary = {}
heatmaps = {}
for k in COUNTS:
    combo_values, marginal_values, coverage_values = [], [], []
    matrix = np.full((7, 7), np.nan)
    for a, source in enumerate(DOMAINS):
        group = plans[source, k]
        combinations = Counter(tuple(sorted(row["fusion_domains"])) for row in group)
        marginal = Counter(d for row in group for d in row["fusion_domains"])
        combo_values.append(entropy(combinations, math.comb(6, k - 1)))
        marginal_values.append(entropy(marginal, 6))
        coverage_values.append(len(combinations) / math.comb(6, k - 1))
        for b, domain in enumerate(DOMAINS):
            if source != domain:
                matrix[a, b] = marginal[domain] / len(group)
    heatmaps[k] = matrix
    summary[k] = {
        "plans": sum(len(plans[d, k]) for d in DOMAINS),
        "conditional_combination_entropy": sum(combo_values) / 7,
        "conditional_marginal_entropy": sum(marginal_values) / 7,
        "conditional_combination_coverage": sum(coverage_values) / 7,
        "combination_entropy_by_source": dict(zip(DOMAINS, combo_values)),
    }

retrieval_scores = defaultdict(list)
query_scores = defaultdict(list)
examples = {}
for row in read_rows("3_retrieve_key_fact_matches"):
    k = row["domain_count"]
    assert row["retrieval"]["method"] == "hybrid"
    assert row["retrieval"]["rrf_k"] == 60
    assert len(row["fusion_domains"]) == k - 1
    domain_scores = []
    for domain in row["fusion_domains"]:
        requirements = row["required_key_facts"][domain]
        candidates = row["retrieved_samples"][domain]
        assert len(requirements) == 3
        for candidate in candidates:
            reconstructed = sum(1 / (60 + h["rank"]) for h in candidate["hits"])
            assert math.isclose(reconstructed, candidate["rrf_score"], rel_tol=1e-12)
        strengths = []
        for query_index in range(1, len(requirements) + 1):
            values = [
                61 / 2 * sum(1 / (60 + h["rank"])
                             for h in candidate["hits"]
                             if h["query_index"] == query_index)
                for candidate in candidates
            ]
            score = max(values, default=0.0)
            assert 0 <= score <= 1 + 1e-12
            strengths.append(score)
            query_scores[k].append(score)
        domain_scores.append(sum(strengths) / len(strengths))
    retrieval_scores[k].append(sum(domain_scores) / len(domain_scores))
    if row["source_domain"] == "computer_science" and row["sample"]["completion"] == "True":
        if "The length of the IPv4 packet header is variable." in row["sample"]["prompt"]:
            examples[k] = {"requirements": row["required_key_facts"],
                           "normalized_rank_strength": sum(domain_scores) / len(domain_scores)}

assert [len(query_scores[k]) for k in COUNTS] == [2100, 4200, 6300]
for k in COUNTS:
    assert len(retrieval_scores[k]) == 700
    v = np.array(retrieval_scores[k])
    summary[k]["rank_strength_mean"] = float(v.mean())
    summary[k]["rank_strength_median"] = float(np.median(v))
    summary[k]["rank_strength_p10"] = float(np.quantile(v, .1))
    summary[k]["rank_strength_p90"] = float(np.quantile(v, .9))
    summary[k]["requirements"] = len(query_scores[k])
    summary[k]["retained_hit_missing_fraction"] = sum(x == 0 for x in query_scores[k]) / len(query_scores[k])

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "svg.fonttype": "none", "pdf.fonttype": 42})
fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
x = np.arange(3)
axes[0].bar(x - .18, [summary[k]["conditional_combination_entropy"] for k in COUNTS],
            width=.36, color="#2676b8", label="Combination entropy (primary)")
axes[0].bar(x + .18, [summary[k]["conditional_marginal_entropy"] for k in COUNTS],
            width=.36, color="#b8c7d4", label="Marginal domain entropy")
for j, k in enumerate(COUNTS):
    axes[0].text(j - .18, summary[k]["conditional_combination_entropy"] + .02,
                 f'{summary[k]["conditional_combination_entropy"]:.3f}', ha="center", fontsize=9)
axes[0].set(xticks=x, xticklabels=["2 domains", "3 domains", "4 domains"],
            ylim=(0, 1.12), ylabel="Normalized entropy", title="(a) Source-macro entropy")
axes[0].legend(loc="upper left", fontsize=8)
axes[1].bar(x, [summary[k]["conditional_combination_coverage"] for k in COUNTS], color=COLORS)
for j, k in enumerate(COUNTS):
    axes[1].text(j, summary[k]["conditional_combination_coverage"] + .02,
                 f'{summary[k]["conditional_combination_coverage"]:.1%}', ha="center")
axes[1].set(xticks=x, xticklabels=["2 domains", "3 domains", "4 domains"],
            ylim=(0, 1.05), ylabel="Observed / possible combinations",
            title="(b) Source-macro combination coverage")
fig.tight_layout()
for ext in ["png", "svg", "pdf"]:
    fig.savefig(ASSETS / f"figure1_domain_diversity.{ext}", dpi=180, bbox_inches="tight")
plt.close(fig)

fig, axes = plt.subplots(1, 3, figsize=(12, 4), constrained_layout=True)
cmap = plt.get_cmap("Blues").copy()
cmap.set_bad("#eeeeee")
for ax, k in zip(axes, COUNTS):
    im = ax.imshow(heatmaps[k], vmin=0, vmax=1, cmap=cmap)
    ax.set(xticks=range(7), xticklabels=LABELS, yticks=range(7), yticklabels=LABELS,
           title=f"{k} domains; uniform baseline = {(k-1)/6:.1%}",
           xlabel="Additional domain")
    for i in range(7):
        for j in range(7):
            if i != j:
                value = heatmaps[k][i, j]
                ax.text(j, i, f"{value:.0%}", ha="center", va="center", fontsize=7,
                        color="white" if value > .6 else "black")
axes[0].set_ylabel("Source domain")
fig.colorbar(im, ax=axes, label="Inclusion rate within source group", shrink=.75)
for ext in ["png", "svg", "pdf"]:
    fig.savefig(ASSETS / f"figure1_domain_selection_heatmap.{ext}", dpi=180, bbox_inches="tight")
plt.close(fig)

fig, ax = plt.subplots(figsize=(7, 4))
for k, color in zip(COUNTS, COLORS):
    values = np.sort(retrieval_scores[k])
    ax.step(values, np.arange(1, len(values) + 1) / len(values), where="post",
            label=f"{k} domains (n=700)", color=color, linewidth=2)
ax.set(xlim=(0, 1.01), ylim=(0, 1.01), xlabel="Plan-level normalized rank strength",
       ylabel="Empirical cumulative fraction",
       title="Retrieval rank diagnostic (not knowledge support coverage)")
ax.legend()
ax.grid(alpha=.2)
fig.tight_layout()
for ext in ["png", "svg", "pdf"]:
    fig.savefig(ASSETS / f"figure2_rank_strength_diagnostic.{ext}", dpi=180, bbox_inches="tight")
plt.close(fig)

result = {"status": "Descriptive statistics only; no support judgments or masking runs.",
          "source": str(OUTPUTS), "by_domain_count": summary, "ipv4_examples": examples}
(ASSETS / "descriptive_statistics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with (ASSETS / "descriptive_statistics.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["domain_count", "plans", "requirements", "combination_entropy",
                     "marginal_entropy", "combination_coverage", "rank_strength_mean",
                     "rank_strength_median", "retained_hit_missing_fraction"])
    for k in COUNTS:
        s = summary[k]
        writer.writerow([k, s["plans"], s["requirements"], s["conditional_combination_entropy"],
                         s["conditional_marginal_entropy"], s["conditional_combination_coverage"],
                         s["rank_strength_mean"], s["rank_strength_median"],
                         s["retained_hit_missing_fraction"]])
print(json.dumps({k: {key: value for key, value in s.items() if key != "combination_entropy_by_source"}
                  for k, s in summary.items()}, ensure_ascii=False, indent=2))
