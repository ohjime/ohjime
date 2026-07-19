# Annotated Bibliography — Conway's Law via Multi-Agent Systems

> Deep per-paper summaries for the sources behind [[conwayLawMultiAgent_verified]].
> Companion to the executive-summary note; this file is the long-form reading guide. Compiled **2026-06-14**.
>
> **Grounding tags** (how confident, and from what):
> - `[full-text]` — I read the downloaded PDF.
> - `[WF-verified]` — specifics confirmed in the deep-research run via 3-vote adversarial check (direct quotes/tables extracted by verifier agents from the PDF).
> - `[abstract+domain]` — paywalled / not downloaded; summary from abstract + established knowledge of the work. Verify before quoting numbers.

## Download manifest (`docs/sources/`)

| File | Paper | Size / pages | Status |
|---|---|---|---|
| `specification-gap-2603.24284.pdf` | The Specification Gap | 0.47 MB / 9 pp | preprint |
| `perspectivegap-2606.08878.pdf` | PerspectiveGap | 5.76 MB / 17 pp | preprint |
| `causal-symmetrization-2512.09352.pdf` | Causal symmetrization (⚠ misattributed in note) | 1.75 MB / 18 pp | preprint |
| `chatdev-2307.07924.pdf` | ChatDev | 3.48 MB | ACL 2024 |
| `macnet-2406.07155.pdf` | MacNet | 3.24 MB | ICLR 2025 |
| `mast-why-mas-fail-2503.13657.pdf` | MAST / "Why Do MAS Fail?" | 1.19 MB / 20 pp | NeurIPS 2025 |
| `topology-priority-2505.22467.pdf` | Topological Structure Learning (position) | 0.51 MB / 13 pp | preprint |
| `agentprune-2410.02506.pdf` | AgentPrune | 21.1 MB | ICLR 2025 |
| `tesna-stsc-amrit-1201.4142.pdf` | TESNA / Socio-Technical Structure Clash | 1.04 MB / 27 pp | preprint of JIT 2010 |
| `agentdropout-acl2025.pdf` | AgentDropout | 1.12 MB | ACL 2025 |
| `carley-orgahead-pnas-2002.pdf` | Carley, Computational Organization Science | 0.17 MB / 6 pp | PNAS 2002 |

**Not downloaded (paywalled).** Jin & Levitt 1996 (Springer/CMOT); MacCormack–Rusnak–Baldwin 2006 (Management Science) & 2012 (Research Policy); Colfer & Baldwin 2016 (ICC/OUP); Herbsleb & Grinter 1999 (ACM/ICSE); Cataldo et al. 2008 (ACM/ESEM). Open working-paper versions exist for the two HBS mirroring papers (see §4).

---

## 1. Credibility-audit targets (real preprints worth reading — but NOT peer-reviewed)

These three arXiv IDs from the original note resolve to **real** papers. The problem in the note was (i) calling preprints "peer-reviewed," and (ii) one fabricated interpretation.

### 1.1 The Specification Gap — Chacón Sartori (arXiv:2603.24284) `[WF-verified]`
*Coordination Failure Under Partial Knowledge in Code Agents.* cs.SE preprint, 25 Mar 2026. Author verifiable (PhD, IIIA-CSIC/UAB; repo `camilochs/the_specification_gap`).

**Thesis.** When independent LLM agents each implement *different methods of the same class* without runtime communication, integration fails not from individual incompetence but from unshared decisions about internal state — a coordination tax that no amount of single-agent capability removes.

**Method.** Two agents implement disjoint methods of one Python class; to integrate they must implicitly agree on the data structures set up in `__init__`. The authors inject *opposing* biases (Agent A prompted to prefer **lists**, Agent B to prefer **dictionaries**) and degrade the shared specification across four levels — **L0** full docstrings+doctests → **L1** drop doctests → **L2** abstracted, data-structure refs removed → **L3** bare signatures — over ~51 class-generation tasks (the paper's task count is stated inconsistently, 51/53/100), on Sonnet and Haiku, 3 runs.

**Key results.** Two-agent integration accuracy falls **58% → 25%** (L0→L3); a single-agent baseline degrades far more gracefully **~89% → 56%**; the gap is a persistent **25–39 pp "coordination tax"** at every level. An AST-based conflict detector hits **~97% precision at L3 with zero extra LLM calls** — yet feeding its conflict reports to a merger agent yields **0 pp** recovery (can even hurt −6.6 pp). The *only* fix that works is restoring the full **L0 specification** to the merger, which recovers the ~89% ceiling.

**Relevance.** The cleanest modern micro-experiment for Conway's Law: the **specification IS the communication structure**, and architectural incompatibility is a direct image of specification impoverishment. The note quotes its numbers *accurately* — the only correction is "preprint, not peer-reviewed."

### 1.2 PerspectiveGap — Sun, Ren, Zhang, Liu, Guo (arXiv:2606.08878) `[WF-verified metadata only]`
*A Benchmark for Multi-Agent Orchestration Prompting.* cs.CL / cs.MA preprint, 7 Jun 2026.

**Thesis / method.** Evaluates whether an *orchestrator* LLM can hand each sub-agent only the fragments it needs. Given a shuffled fragment set across 110 scenarios and 10 role-and-handoff topologies, the orchestrator must route need-to-know context. Failure modes catalogued: **distractor leakage** (orchestrator-only tips bleed into sub-prompts), **out-of-role leakage** (e.g., leaking private test sets to the coder → a reward-hacking channel), and the **bootstrap paradox** (an instruction placed inside the artifact it refers to).

**⚠ Caveats.** Existence/authors/date are confirmed, but the **internal numbers** (27 models; top ~62%, avg ~14.9%; ≥49% leakage) were **not** verified, and the cited models **"GPT-5.5"/"Opus 4.7"** are suspicious/future-dated. Treat headline stats as unverified.

**Relevance.** Conway-at-the-orchestration-layer: if the agent that *defines* the communication boundaries can't enforce need-to-know, the resulting architecture collapses into a contaminated monolith.

### 1.3 Causal symmetrization — Gosme (arXiv:2512.09352) `[WF-verified — and a fabrication flag]`
*Causal symmetrization as an empirical signature of operational autonomy in complex systems.* physics.soc-ph / cs.CY / cs.SE preprint; twin on Research Square (rs-8339220).

**What it actually is.** A paper about **autopoiesis / operational closure** — structure–activity coupling shifting 0.71 → 0.94 as a signature of autonomy. It **never mentions** "Conway's Law," "Inverse Conway," "multi-agent," or even "agent."

**The note's error.** Ref 19 attributes an *"Inverse Conway Effect / symmetric bidirectional coupling in mature open-source projects"* to this paper. That is a **fabrication** — a real DOI with an invented Conway overlay (verifiers refuted it 0–3). Keep the PDF as a cautionary example of the failure pattern, not as Conway evidence.

> The McEntire *"Organizational Physics"* monograph (`cageandmirror.com`, self-published book + pulse2.com PR interview) and Swoft AI's *"Executable Conway's Law"* (vendor marketing) are **not** downloaded and **not** citable as research — see the audit table in [[conwayLawMultiAgent_verified]].

---

## 2. Classical era — organizations as agent-based testbeds (pre-LLM)

### 2.1 Carley (2002), *Computational Organization Science: A New Frontier* — PNAS 99(suppl 3):7257–7262 `[full-text]`
**Thesis.** "Synthetic adaptation": any entity made of intelligent adaptive agents is *itself* an intelligent adaptive agent, so organizations are **inherently computational** and can be studied as multi-agent systems. Agents are not merely "boundedly rational" but **structurally rational** — what they can do is fixed by their position in an interlocked web of social, knowledge, assignment, and task networks (the "metamatrix").

**Method (the testbeds).** Two simulations:
- **ORGAHEAD** — organizations of **5–45 agents** doing a classification-choice task, modeled at two levels. *Operational:* "a multiagent system in which the agents … have a position in the organization's architecture that constrains whom they communicate/report to, what resources they access, and what subtasks they are assigned." *Strategic:* a CEO/executive that forecasts and **restructures** (hire/fire, redesign reporting, retask) — a search over a performance surface (done elsewhere via simulated annealing). Three interlinked models (operational-agent, CEO, task) bound by the **architecture** (personnel, resources/subtasks, and their connections).
- **CONSTRUCT-O** — co-evolution of social structure and culture; information diffusion where technologies (e.g., databases) are themselves agents with network positions.

**Key results.** Virtual experiments (e.g., 1,000 orgs × 10,000 periods; 100 orgs × 40,000 periods; 69 real firms in industrial-accident crises that the model fit well) yield: **congruence** (match between an org's reporting/assignment/knowledge structure and the task's needs/requirements) drives performance; **adaptive** orgs grow **larger and less dense**, maladaptive ones **smaller and denser**; **tuning** (redesign→retask) beats **shaking** (downsizing/CEO swap); and a fundamental **performance-vs-adaptability tradeoff**.

**Relevance.** The canonical proof-of-concept that you can put an *organization's communication/authority structure* under experimental control and read off how it shapes outcomes — exactly the move the user wants to port to LLM swarms. Carley's "congruence/match between structure and task" is the classical seed of socio-technical congruence (§3.x) and of the mirroring intuition; note ref [25] is **Burton & Obel**, tying directly to the org-design-simulation lineage named in the brief.

### 2.2 Jin & Levitt (1996), *The Virtual Design Team (VDT)* — Computational & Mathematical Organization Theory 2(3):171–195 `[abstract+domain]`
**Thesis / method.** An **actor-level (agent) computational model of project organizations**: it disaggregates a project org into individual actor-agents executing **interdependent activities** that demand coordination, operationalizing **Galbraith's (1973) information-processing view** — work generates information-processing load, and an org's structure (positions, reporting links, communication channels) is its capacity to handle that load. Misalignment shows up as coordination backlog, rework, and delay. Highly cited (~466), peer-reviewed in a venue named in the brief.

**Relevance.** The purest "simulate the org, watch structure shape the artifact/schedule" testbed of the classical era; the conceptual ancestor of treating an LLM agent topology as an information-processing organization whose structure predicts output quality. *(Does not itself say "Conway's Law" — that link is the analyst's.)*

---

## 3. Modern era — LLM multi-agent swarms (communication structure as the variable)

### 3.1 ChatDev — Qian et al. (arXiv:2307.07924, ACL 2024, Anthology 2024.acl-long.810) `[WF-verified]`
**What it is.** A multi-agent LLM system run as a **"virtual software company"** with explicit organizational roles — CEO, CTO, CPO, Programmer, Designer, Reviewer/Tester — that collaborate through **designing → coding → testing → documenting**. Inter-agent communication is governed by a **chat-chain** topology (a chain-shaped special case of a DAG) that decomposes the lifecycle into sequential, role-paired phases and dictates *what* gets communicated at each step.

**Relevance.** The agent organization is an *explicit, observable role/communication structure* producing a software artifact — precisely the setup a Conway's-Law study needs. Cite **ChatDev 1.0 (Legacy)** for this; 2.0 pivoted to a generic zero-code platform.

### 3.2 MacNet — Qian et al. (arXiv:2406.07155, ICLR 2025) `[WF-verified]`
**Thesis / method.** Organizes LLM agents into a **directed acyclic graph** ("multi-agent collaboration network") whose **interactive reasoning is topologically orchestrated** — each edge is a supervisor/critic relation, each node a compliant actor. **Communication topology is the manipulated independent variable**: chain, tree, star, mesh, layered, random, and general graphs.

**Key result.** Collaboration **scales to 1000+ agents**, and **irregular (small-world) topologies outperform regular ones**. A follow-up (arXiv:2505.23352, EMNLP 2025) refines this toward "moderately sparse is optimal" rather than overturning it.

**Relevance.** The strongest modern evidence that *the shape of the agent organization materially changes the produced output* — the empirical engine for a topology-centric reading of Conway's Law.

### 3.3 MAST — Cemri et al. (arXiv:2503.13657, NeurIPS 2025 Datasets & Benchmarks, spotlight) `[WF-verified]`
**Thesis / method.** The first **Multi-Agent System Failure Taxonomy**, induced from **150+ execution traces** with strong inter-annotator agreement (**κ = 0.88**). **14 failure modes** in 3 categories: (i) system-design/specification issues, (ii) **inter-agent misalignment**, (iii) task verification.

**Key result.** **Inter-agent misalignment ≈ 37%** of failures — communication breakdowns, context loss at handoffs, conflicting outputs.

**Relevance.** The "broad organizational dynamics" lens made empirical: a MAS's coordination structure produces **observable, categorizable dysfunction signatures**, the silicon analogue of human org pathologies (bikeshedding, dropped handoffs, verification theatre).

### 3.4 Topological Structure Learning … Should Be a Research Priority (arXiv:2505.22467) `[WF-verified]` — *position paper, preprint*
**Claims it consolidates.** Communication topology shifts task performance **by up to ~10%** (MMLU/GSM8K/HumanEval, GPT-3.5 & GPT-4o); the **optimal topology is task-dependent and should mirror the task's coordination structure** — **chains** for sequential workflows (software dev: ChatDev, AutoCodeRover), **tree/star** for simulation/aggregation; and topology drives **coordination cost**, with communication rising **~quadratically** as agents scale (unoptimized fully-connected multi-round MAS burning ~tens× the tokens of a single-agent/chain system).

**Caveat.** A *position paper*: Fig. 1 is motivating, not a controlled study, and the authors themselves caution topology design is not a universal law. Cite as a framing/synthesis, not primary evidence.

### 3.5 AgentPrune — "Cut the Crap" (arXiv:2410.02506, ICLR 2025) `[WF-verified]`
**Thesis / method.** First to **formally define communication redundancy** in LLM-MAS; represents the system as a **spatial-temporal message-passing graph** and does **one-shot pruning** (trainable mask matrices, a low-rank principle, spatial + temporal cuts) to yield a token-economic, often higher-performing topology.

**Key result.** **28.1–72.8% token reduction** at ~5.6% of prior SOTA cost, with maintained/improved accuracy.

**Relevance.** A concrete **graph/network-science method applied directly to the agent communication structure** as an optimizable object — adjacent to (but distinct from) a structural-similarity metric: it optimizes the agent graph, it does not yet compare that graph to the produced artifact (see the gap in [[conwayLawMultiAgent_verified]] §4).

### 3.6 AgentDropout (ACL 2025, Anthology 2025.acl-long.1170) `[WF-verified]`
Dynamic elimination of redundant agents/edges for token efficiency; the source of the **~69×** prompt-token contrast (single-agent ~68K vs fully-connected MAS ~4.7M) cited in the topology position paper. Reinforces that coordination cost is a structural, measurable property of the topology.

---

## 4. Measurement — comparing the complexity & structure of org vs. artifact

### 4.1 Amrit, van Hillegersberg & Kumar — TESNA / **Socio-Technical Structure Clash (STSC)** (arXiv:1201.4142; peer-reviewed in *Journal of Information Technology* 25(2), 2010) `[WF-verified]`
**The procedure that operationalizes the thesis.** Conway's Law is reframed as a **"homomorphism" between the social communication structure and the technical architectural dependencies**; when the team's communication network **fails to match** the software's dependency structure, you have a measurable **STSC**.

**Method (two structures, built independently, then compared):**
- **Technical** — a software-module **Dependency Structure Matrix (DSM)** mined from source/call graphs (CVS), **clustered with the MacCormack–Rusnak–Baldwin (2006) DSM clustering algorithm**.
- **Social** — a developer **communication network** mined from bug-tracker/email/chat repositories (the *eMaxx* case used the **Mantis** tracker), scored with **network-science centrality**: **Information Centrality** (Stephenson & Zelen) and **Betweenness** (Freeman).
- **Compare** the two to detect divergence (clusters with technical dependency but no matching communication link = an STSC).

**Relevance.** This is the most directly reusable template for the user: swap the human dev team for an LLM agent org, build the artifact DSM and the agent-communication graph, and measure the mismatch. The bridge from "Conway as anecdote" to "Conway as a structural-comparison test."

### 4.2 MacCormack, Rusnak & Baldwin (2006), *Exploring the Structure of Complex Software Designs* — Management Science 52(7):1015–1030 `[abstract+domain]`
The **DSM machinery** underneath §4.1: applies dependency-structure-matrix analysis and a **propagation-cost** metric to compare real codebases (famously, a more *modular* open-source design vs a more *tightly-coupled* proprietary one). Supplies the clustering algorithm and the architecture-as-matrix vocabulary the rest of the mirroring literature builds on.

### 4.3 MacCormack, Rusnak & Baldwin (2012), *Exploring the Duality between Product and Organizational Architectures: A Test of the Mirroring Hypothesis* — Research Policy 41(8):1309–1324 `[abstract+domain]`
The **headline empirical mirroring test**: matched product pairs of similar function built by organizations with different coupling (loosely-coupled/distributed open-source vs tightly-coupled/co-located commercial). Finding: **products mirror the organizations** — loosely-coupled orgs produce significantly more **modular** designs, measured via DSM propagation cost. Open version: **HBS Working Paper 08-039**.

### 4.4 Colfer & Baldwin (2016), *The Mirroring Hypothesis: Theory, Evidence, and Exceptions* — Industrial & Corporate Change 25(5):709–738 `[abstract+domain]`
A **review of ~142 studies** of the mirroring hypothesis across industries. Mirroring is **commonly but not universally** supported, and — crucially for calibrating the original note's "always true" rhetoric — the paper catalogues **deliberate exceptions**, where firms break mirroring on purpose (e.g., open platforms, modular ecosystems). **Read this to avoid overclaiming.** Open version: **HBS Working Paper 16-124**.

### 4.5 Herbsleb & Grinter (1999), *Splitting the Organization and Integrating the Code: Conway's Law Revisited* — ICSE '99 `[abstract+domain]`
Field study of **geographically distributed development** (Lucent). When informal communication breaks down across sites, the **formal module interfaces become the only coordination channel**, and integration problems cluster at the **socio-organizational seams** — the empirical re-grounding of Conway's Law in modern distributed SE. (This is the original note's ref 15 — genuinely real and foundational.)

### 4.6 Cataldo, Herbsleb & Carley (2008), *Socio-Technical Congruence: A Framework…* — ESEM '08 (ACM 10.1145/1414004.1414008) `[abstract+domain]`
Defines and measures **socio-technical congruence**: the fraction of **coordination requirements** (derived from technical/task dependencies) that are actually met by **coordination activities** (real communication). Empirically, **higher congruence → faster task resolution** (modification requests close quicker). The metric form of "does communication match the work's dependency structure" — a quantitative cousin of §4.1.

### 4.7 Structural-comparison toolbox (for a methods section) `[abstract+domain]`
For comparing two graphs (agent org vs artifact dependency graph): **graph edit distance**, spectral similarity, and the algorithmic-information measures in §5. Pair with DSM clustering (§4.1–4.3) and congruence (§4.6).

---

## 5. Algorithmic / information-theoretic complexity (supports the Kolmogorov question) `[domain]`

Conceptual backing for measuring MAS complexity and for an information-theoretic statement of mirroring (`K(artifact | org)` small ⇒ strong mirroring). See [[conwayLawMultiAgent_verified]] §3 for the argument.

- **Li & Vitányi**, *An Introduction to Kolmogorov Complexity and Its Applications* — definitions, uncomputability, invariance theorem.
- **Gell-Mann & Lloyd (1996)**, "Information measures, effective complexity, and total information," *Complexity* 2(1) — **effective complexity** (structure, not randomness).
- **Bennett (1988)**, "Logical depth and physical complexity" — computation implied by a design.
- **Crutchfield & Young (1989)**, *Phys. Rev. Lett.* 63:105; **Crutchfield (2012)**, "Between order and chaos," *Nature Physics* 8:17–24 — **statistical complexity / ε-machines**.
- **Cilibrasi & Vitányi (2005)**, "Clustering by Compression," *IEEE TIT* 51(4) — **NCD**, the computable proxy; **Li et al. (2004)**, "The similarity metric" — **NID**, the ideal.
- **Zenil, Kiani & Tegnér (2018)**, "A Review of Graph and Network Complexity from an Algorithmic Information Perspective," *Entropy* — **BDM/CTM** for graphs/networks (robust where compression fails on small structures).
- **Prokopenko, Boschetti & Ryan (2009)**, "An information-theoretic primer on complexity, self-organization, and emergence," *Complexity* 15(1) — applies these measures to self-organizing/agent systems.

---

## 6. How to use this for the thesis

The verified literature gives you (a) classical testbeds proving structure→outcome is experimentally controllable (Carley, VDT), (b) modern swarms where **topology is already the manipulated variable** (MacNet, ChatDev, AgentPrune) and **dysfunction is catalogued** (MAST, Specification Gap), and (c) a concrete **structural-comparison method** (TESNA/STSC DSM-vs-network, congruence, mirroring DSM). The **open gap**: nobody has applied (c) to (b) — measuring the mirroring/distance between an *LLM* agent org and the artifact it builds, via DSM, congruence, or the `NCD`/`K(artifact|org)` formulation. That intersection is the contribution.
