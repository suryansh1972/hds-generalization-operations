Semantic Generalization of Motifs — Methodology & Implementation Plan
1 Nov 2026 · @Suryansh
Where this sits in the design doc
The generalization step is Section 6.5 (Abstraction operators and validity checks) of the Central–Leaf design v0.3: Eq. (15) defines the partial order S ⪯ S′ and Table 3 lists the permitted moves and their required checks. Everything else in Section 6 (metrics V, K, D, C, U, Laya, the objective in Eqs. 16–21) is the optimization step and is out of scope here.
Doc location
What it contributes to generalization
Sect. 2, sub-process 4 “Ablate and generalize”
One-line definition of the step
Sect. 3 Glossary: Semantic ablation, Generalization order, Candidate signature
Vocabulary: S ⪯ S′, candidate signature S
Sect. 6.1, action set A
The move set: remove-node, remove-edge, ontology-generalize, coarsen-numeric, coarsen-temporal, suppress-attribute (derived-state substitute is also listed)
Sect. 6.1, “How entities are actually removed”
Counterfactual ablation: build S \ {x} or g(x), then re-measure
Sect. 6.5, Eq. (15) + Table 3
Core: partial order, operators, per-operator checks, forbidden moves
Algorithm 2, line 1 GenerateSoundGeneralizations and lines 10–11 AblateOrGeneralize
Where the generator is called and where illegal moves are discarded
Fig. 3, “Ontology generalization: replace / suppress / coarsen” box
Same step, drawn
Derived-state substitution (last but one row of Table 3) is left out here: it depends on the closure rule engine, not on the hierarchy, and you did not list it.
Scope, inputs and outputs
The step takes one supported motif and returns every legal, more general version of it, each with an explicit change set and a proof that it is a generalization. It does not score, rank, count patients or choose anything; that is the next step.
In scope
• Six operators: concept lift, attribute removal, numeric range coarsening, temporal coarsening, relation relaxation, edge removal (with orphan-node removal).
• Legality rules per operator (the “Required check” column of Table 3) and the forbidden moves.
• The partial order S ⪯ S′, built by construction and independently verified.
• A generalization lattice per motif, deduplicated, with every edge labelled by its move.
Out of scope (next step)
• Support counts, disclosure, complexity, utility, Laya, NBFNet ranking, grouping, Disclosure Guard.
• Re-running BioPathNet. Motifs arrive already enriched; this step only reads them.
• Any noise injection, fuzzy matching or learned similarity. Every decision is a symbolic check against SNOMED or a fixed rule table.

Input
Output
Object
Supported motif S₀ (JSON), from the BioPathNet-enriched patient graph after validation
Lattice of candidate signatures {S′} with S₀ ⪯ S′
Knowledge
SNOMED CT RF2 Snapshot (local), relation hierarchy file, coarsening ladders (YAML)
—
Per candidate
—
canonical JSON, hash, depth from S₀
Per lattice edge
—
parent hash, child hash, operator, change set, legality evidence (e.g. the IS-A path used)
The change set is what makes “each change is re-measured” possible later: the next step re-evaluates S′ against S and attributes any metric change to exactly that move.
Methodology
A move is legal only if it can never shrink the set of matching patients; that is checked symbolically against SNOMED and a fixed rule table, never estimated.
1. Motif model
A motif is a small typed, directed graph (typically 3–8 nodes):
• Node: id, type (Disorder, Substance, Observable, Procedure, Gene, Pathway …), code (SCTID for clinical nodes; OptimusKG id for context nodes), polarity (present / absent), role (anchor, exposure, outcome, modifier, context), optional value interval with unit.
• Edge: source, target, relation, provenance (asserted / derived / context), optional time window relative to another node, e.g. [0, 30] days after n2.
• Context edges carry the BioPathNet score only as metadata. They are never promoted to asserted.
2. The partial order S ⪯ S′
S′ is more general than S when every part of S′ can be mapped onto a part of S that is equal or more specific. Formally, S ⪯ S′ holds if there is a mapping h from the nodes of S′ to the nodes of S such that:
\forall v' \in V_{S'}:\; \mathrm{code}(h(v')) \sqsubseteq \mathrm{code}(v') \text{ (present)},\quad \mathrm{code}(v') \sqsubseteq \mathrm{code}(h(v')) \text{ (absent)}
\forall (u',r',w') \in E_{S'}:\; \exists (h(u'),r,h(w')) \in E_S \text{ with } r \sqsubseteq r'
\mathrm{value}(h(v')) \subseteq \mathrm{value}(v'),\quad \mathrm{window}(e) \subseteq \mathrm{window}(e')
Here ⊑ is SNOMED subsumption (IS-A, ancestor-or-self), the same relation as ECL <<. This is the standard homomorphism test for graph-pattern containment. It gives Eq. (15) of the design doc under one condition: the patient matcher in the next step uses the same subsumption semantics, which holds because the closure G⁺ already contains SNOMED ancestors (Sect. 4.2, step 1).
Each operator builds S′ so that the order holds by construction. An independent checker re-proves it for every generated pair, so a bug in an operator is caught rather than shipped.
3. Operators and legality rules
Operator
Transformation
Legal only if
Example (motif M1)
Concept lift
Replace node code by one IS-A parent
Parent is active in RF2; stays at or below the type’s floor concept; node polarity is present
Doxorubicin → its SNOMED parent substance class
Attribute removal
Delete a non-mandatory attribute or leaf node
Node role is not anchor; node is not the only link between anchor and an outcome
Drop BRCA1 variant node
Range coarsening
Replace value interval with the next wider bin on a fixed ladder
Original interval lies inside the new bin; same unit
LVEF 38% → “≤ 40%” → “< 50%” → removed
Temporal coarsening
Widen a time window on a fixed ladder
Original window inside new window; before/after order kept
23 days after → 0–90 days after → after → co-occurs
Relation relaxation
Replace relation by its parent in the relation hierarchy
Parent exists in the hierarchy file; direction and roles unchanged
administered_drug → exposed_to_drug
Edge removal
Delete one edge, then drop nodes no longer connected to the anchor
Anchor stays; at least one asserted edge remains; edge is not a negation constraint unless policy allows
Drop gene → pathway context edge
Concept lift on SNOMED’s polyhierarchy yields one candidate per parent, so a concept with two parents produces two siblings in the lattice.
4. Forbidden moves
These are rejected outright because they can shrink or change the patient set:
• Lifting an absent (negated) concept. “No type 2 diabetes” lifted to “no diabetes” excludes more patients, so it is a specialization.
• Narrowing a range or window, or moving it so it no longer contains the original.
• Reversing an edge, flipping polarity, or replacing an association with a causal relation.
• Promoting a context edge (BioPathNet-predicted) to asserted or derived.
• Lifting above the floor concept configured per node type (e.g. not above “Malignant neoplastic disease” for the anchor), since the top of a hierarchy carries no clinical meaning.
5. Building the lattice
The primary interface is one step at a time: neighbors(S) applies every operator, filters illegal results, canonicalizes and returns (S′, change set) pairs. The optimizer in the next step calls it repeatedly, matching AblateOrGeneralize in Algorithm 2.
For testing and small motifs, enumerate_lattice(S₀, max_depth) runs breadth-first search over neighbors, deduplicating by canonical hash. Moves on different nodes are independent, so the full lattice is roughly a product of per-node ladders; a depth cap (start with 4) keeps it finite.
Using your local SNOMED RF2 files
Yes, the RF2 files are the backbone of this step: concept lift, the floor rules, relation relaxation for SNOMED attributes and the order checker all read the IS-A graph from them. Only three Snapshot files are needed, loaded once into Python on your Mac.
File (Snapshot/Terminology)
Columns used
Used for
sct2_Concept_Snapshot_INT_<date>.txt
id, active
Only active concepts may be lift targets
sct2_Description_Snapshot-en_INT_<date>.txt
conceptId, typeId, term, active
FSN labels (typeId 900000000000003001); semantic tag such as “(disorder)” gives the node type; resolving synthetic labels to SCTIDs
sct2_Relationship_Snapshot_INT_<date>.txt
sourceId, destinationId, typeId, characteristicTypeId, active
IS-A edges: typeId 116680003, inferred rows only (characteristicTypeId 900000000000011006)
What gets built from them:
1. parents: dict[SCTID, set[SCTID]] from active inferred IS-A rows. This is the whole hierarchy, including the attribute hierarchy under “Concept model attribute”, which gives relation relaxation for SNOMED attributes for free.
2. ancestors(c), cached, for the subsumption test c ⊑ d. Equivalent to ECL >> c.
3. depth(c) = shortest IS-A distance to the root 138875005, for floor rules and for logging how far a lift went.
4. A pickle (or SQLite table) of the above, stamped with the RF2 release date, so the lattice output records which SNOMED version produced it.
Two practical notes:
• Read the files with sep="\t", dtype=str and quoting=csv.QUOTE_NONE; SNOMED terms contain quote characters that otherwise break parsing.
• Drug class lifts depend on how deep the SNOMED substance hierarchy is for each drug. The first check in the build plan prints the parents of each synthetic drug; if a drug has no clinically useful class parent, that is an open question for the team (ATC is the usual fallback, but it is not in SNOMED International).
A Snowstorm terminology server would also answer ECL queries, but it needs Elasticsearch. Polars over the RF2 files is enough for this step; FalkorDB can hold the IS-A graph once later stages need it.
Synthetic motifs
Four motifs mimic what the validated BioPathNet-enriched patient graph should hand over: a patient node, an asserted clinical core (anchor, exposure, outcome with value and time) and one or two BioPathNet context edges with scores. Together they exercise all six operators and the negation rule.
Motif
Clinical core
Context (BioPathNet)
Operators it exercises
M1
Breast cancer, doxorubicin, LVEF 38% at 23 days, age 67, cumulative dose
Doxorubicin → TOP2B → pathway
All six
M2
Type 2 diabetes, metformin, CKD, eGFR 42 at 180 days, no type 1 diabetes
Metformin → lactic acidosis
Negation rule, range, temporal
M3
NSCLC, EGFR mutation finding, osimertinib, interstitial lung disease at 41 days
Osimertinib → EGFR → ErbB pathway
Lift, edge removal, relation relaxation
M4
Rheumatoid arthritis, methotrexate, ALT 145 U/L at 90 days
Methotrexate → liver injury
Range, temporal, lift
code is left null for clinical nodes on purpose: the loader resolves each label to its SCTID by exact FSN match in your RF2 Description file and stops with an error if a label is not found. That avoids typing concept ids by hand. Context codes are placeholders in an OptimusKG-like format; replace them with real ids from your colleague’s output when it arrives. All values are invented.
[
 {"motif_id": "M1", "anchor": "n1",
  "nodes": [
   {"id": "P",  "type": "Patient", "role": "patient"},
   {"id": "n1", "type": "Disorder",   "label": "Malignant neoplasm of breast (disorder)", "code": null, "polarity": "present", "role": "anchor",
    "attrs": {"age_at_dx": {"interval": [67, 67], "unit": "a"}}},
   {"id": "n2", "type": "Substance",  "label": "Doxorubicin (substance)", "code": null, "polarity": "present", "role": "exposure",
    "attrs": {"cumulative_dose": {"interval": [360, 360], "unit": "mg/m2"}}},
   {"id": "n3", "type": "Observable", "label": "Left ventricular ejection fraction (observable entity)", "code": null, "polarity": "present", "role": "outcome",
    "value": {"interval": [38, 38], "unit": "%"}},
   {"id": "n4", "type": "Gene",    "label": "TOP2B", "code": "optimus:gene/TOP2B", "role": "context"},
   {"id": "n5", "type": "Pathway", "label": "DNA topoisomerase II pathway", "code": "optimus:pathway/PLACEHOLDER", "role": "context"}],
  "edges": [
   {"s": "P",  "t": "n1", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n2", "rel": "administered_drug", "prov": "asserted"},
   {"s": "P",  "t": "n3", "rel": "has_measurement",  "prov": "asserted"},
   {"s": "n2", "t": "n3", "rel": "followed_by",      "prov": "asserted", "time": {"window": [23, 23], "unit": "d"}},
   {"s": "n2", "t": "n4", "rel": "targets",          "prov": "context", "bpn_score": 0.81},
   {"s": "n4", "t": "n5", "rel": "participates_in",  "prov": "context", "bpn_score": 0.64}]},

 {"motif_id": "M2", "anchor": "n1",
  "nodes": [
   {"id": "P",  "type": "Patient", "role": "patient"},
   {"id": "n1", "type": "Disorder",   "label": "Type 2 diabetes mellitus (disorder)", "code": null, "polarity": "present", "role": "anchor"},
   {"id": "n2", "type": "Disorder",   "label": "Type 1 diabetes mellitus (disorder)", "code": null, "polarity": "absent",  "role": "modifier"},
   {"id": "n3", "type": "Substance",  "label": "Metformin (substance)", "code": null, "polarity": "present", "role": "exposure"},
   {"id": "n4", "type": "Disorder",   "label": "Chronic kidney disease (disorder)", "code": null, "polarity": "present", "role": "modifier"},
   {"id": "n5", "type": "Observable", "label": "Glomerular filtration rate (observable entity)", "code": null, "polarity": "present", "role": "outcome",
    "value": {"interval": [42, 42], "unit": "mL/min/1.73m2"}},
   {"id": "n6", "type": "Disorder",   "label": "Lactic acidosis", "code": "optimus:disease/PLACEHOLDER", "role": "context"}],
  "edges": [
   {"s": "P",  "t": "n1", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n2", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n3", "rel": "administered_drug", "prov": "asserted"},
   {"s": "P",  "t": "n4", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n5", "rel": "has_measurement",  "prov": "asserted"},
   {"s": "n3", "t": "n5", "rel": "followed_by",      "prov": "asserted", "time": {"window": [180, 180], "unit": "d"}},
   {"s": "n3", "t": "n6", "rel": "associated_with",  "prov": "context", "bpn_score": 0.72}]},

 {"motif_id": "M3", "anchor": "n1",
  "nodes": [
   {"id": "P",  "type": "Patient", "role": "patient"},
   {"id": "n1", "type": "Disorder",  "label": "Non-small cell lung cancer (disorder)", "code": null, "polarity": "present", "role": "anchor"},
   {"id": "n2", "type": "Finding",   "label": "EGFR gene mutation finding (resolve exact FSN locally)", "code": null, "polarity": "present", "role": "modifier"},
   {"id": "n3", "type": "Substance", "label": "Osimertinib (substance)", "code": null, "polarity": "present", "role": "exposure"},
   {"id": "n4", "type": "Disorder",  "label": "Interstitial lung disease (disorder)", "code": null, "polarity": "present", "role": "outcome"},
   {"id": "n5", "type": "Gene",      "label": "EGFR", "code": "optimus:gene/EGFR", "role": "context"},
   {"id": "n6", "type": "Pathway",   "label": "ErbB signaling pathway", "code": "optimus:pathway/PLACEHOLDER", "role": "context"}],
  "edges": [
   {"s": "P",  "t": "n1", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n2", "rel": "has_finding",      "prov": "asserted"},
   {"s": "P",  "t": "n3", "rel": "administered_drug", "prov": "asserted"},
   {"s": "P",  "t": "n4", "rel": "has_condition",    "prov": "asserted"},
   {"s": "n3", "t": "n4", "rel": "followed_by",      "prov": "asserted", "time": {"window": [41, 41], "unit": "d"}},
   {"s": "n3", "t": "n5", "rel": "targets",          "prov": "context", "bpn_score": 0.88},
   {"s": "n5", "t": "n6", "rel": "participates_in",  "prov": "context", "bpn_score": 0.70}]},

 {"motif_id": "M4", "anchor": "n1",
  "nodes": [
   {"id": "P",  "type": "Patient", "role": "patient"},
   {"id": "n1", "type": "Disorder",   "label": "Rheumatoid arthritis (disorder)", "code": null, "polarity": "present", "role": "anchor"},
   {"id": "n2", "type": "Substance",  "label": "Methotrexate (substance)", "code": null, "polarity": "present", "role": "exposure"},
   {"id": "n3", "type": "Observable", "label": "Alanine aminotransferase activity (resolve exact FSN locally)", "code": null, "polarity": "present", "role": "outcome",
    "value": {"interval": [145, 145], "unit": "U/L"}},
   {"id": "n4", "type": "Disorder",   "label": "Drug-induced liver injury", "code": "optimus:disease/PLACEHOLDER", "role": "context"}],
  "edges": [
   {"s": "P",  "t": "n1", "rel": "has_condition",    "prov": "asserted"},
   {"s": "P",  "t": "n2", "rel": "administered_drug", "prov": "asserted"},
   {"s": "P",  "t": "n3", "rel": "has_measurement",  "prov": "asserted"},
   {"s": "n2", "t": "n3", "rel": "followed_by",      "prov": "asserted", "time": {"window": [90, 90], "unit": "d"}},
   {"s": "n2", "t": "n4", "rel": "associated_with",  "prov": "context", "bpn_score": 0.77}]}
]
Two labels (M3 EGFR finding, M4 ALT) are marked “resolve exact FSN locally” because their exact SNOMED wording should be confirmed in your RF2 before use.
Implementation plan (no code)
Build it as six small pieces in this order, and check each one before starting the next; everything runs in Python on your Mac, next to the RF2 files.
Tools per step
The recommended stack is Polars for RF2, FalkorDB (embedded as FalkorDBLite during development) as the graph store, and rustworkx for the order proof. The logic in Steps 1–6 does not change; only the tool doing each job does.
Step
Job
Recommended tool
Why this one
Watch out
1 Config
Ladders, floors, relation parents
YAML file, validated with Pydantic v2 models
Typos in a ladder or floor fail at load time, not mid-run
Keep it under version control; clinicians review this file
2 SNOMED loader
Read RF2, build IS-A lookups
Polars (or DuckDB reading the TSV in place)
Much faster than pandas on the 3M+ relationship rows; same RF2 files, no Snowstorm
Same rules: all columns as text, tab separator, no quoting
2b SNOMED as a graph (optional now, needed later)
Load concepts + inferred IS-A edges into a graph
FalkorDB via FalkorDBLite (pip install falkordblite)
Embedded, no server to run; the same code later points at a FalkorDB server by changing one connection line (FalkorDBLite docs). Subsumption becomes a Cypher variable-length IS-A path query
Needs Python 3.12+; on a Mac it needs libomp from Homebrew (PyPI)
3 Motif loader
Validate motif JSON, resolve FSNs
Pydantic v2 schema + the Step 2 lookups
Field errors reported with the exact path in the JSON
—
4 Operators
Generate S′ + change record
Plain Python over the motif objects; rustworkx for the connectivity check after edge removal
rustworkx is a Rust-backed graph library with the same jobs as networkx
—
5 Order proof
Is S′ ⪰ S?
rustworkx digraph_vf2_mapping / digraph_is_subgraph_isomorphic with custom node and edge matchers, induced=False
Implements VF2++ in Rust; induced=False gives the non-induced match the order definition needs (rustworkx docs)
Default is induced=True; leaving it on would wrongly reject valid generalizations
6 Lattice store
Candidates + parent→child edges with change records
FalkorDB graph: (:Candidate)-[:GENERALIZES_TO {op, change}]->(:Candidate); also written to JSONL/Parquet for versioning
The lattice is a graph; storing it as one lets the next stages query it directly
—
Checks
Look at results
FalkorDB Browser (comes with the server image, port 3000) for motifs and the lattice; Plotly for the containment heatmap
Click through the lattice instead of drawing it yourself (FalkorDB docs)
FalkorDBLite has no browser; for visual checks run the FalkorDB Docker image locally
Tests
Automatic checks
pytest + Hypothesis (property-based tests)
Hypothesis generates many random motifs and checks “every generated pair passes the proof”
—
Why not do the proof in FalkorDB Cypher? Two reasons: Cypher matches with a no-repeated-edge rule rather than plain homomorphism, and FalkorDB documents a quirk where an unreferenced relationship in a pattern is only checked for existence (known limitations). The proof must be exact, so it stays in rustworkx. FalkorDB is the right home for storage, browsing, and the later stages (support counting over patient graphs, grouping).
Where FalkorDB pays off later: patient closures G⁺, the SNOMED IS-A graph and the lattice can live in one graph, so the next stage’s support count Kh(S) becomes a Cypher MATCH with COUNT(DISTINCT patient) (design doc Table 2). For the Leaf TEE deployment, the same code moves to a FalkorDB server by changing the connection line.
Tools not opened as sources here (stated from general knowledge, check current versions before installing): Polars, DuckDB, Pydantic v2, Plotly, Hypothesis.
Research backing each step (2022–2026)
Recent work supports the PDF’s approach as written: ontology-based relaxation for the moves, homomorphism for the order check, and a pinned SNOMED release because hierarchy errors change cohorts. None of it changes the logic; it tells us which established method each step is an instance of.
Step
Paper
What it says
How we use it
4 Concept lift, relation relaxation
Fakih & Serrano-Alvarado, A Survey on SPARQL Query Relaxation under the Lens of RDF Reification, Semantic Web journal, 2024 (page)
Query relaxation broadens query constraints using logical entailment over ontologies (class and property hierarchies) so the query returns more results
Our concept lift and relation relaxation are this kind of logical relaxation, with SNOMED as the ontology. Use the survey for terminology and to cite in the write-up
4 (why symbolic)
Brunink & Daza et al., Counting Still Counts: Understanding Neural Complex Query Answering Through Query Relaxation, 2025 (arXiv 2511.22565)
A training-free relaxation strategy is competitive with neural query answering and finds answers neural models miss
Supports keeping generalization symbolic, with graph models only ranking evidence (NBFNet), as the PDF requires
5 Order proof
Beaudou, Foucaud et al., Complexity of conjunctive regular path query homomorphisms, 2023 (arXiv 2305.07271)
A homomorphism between two graph queries is a strong form of containment; for path queries, deciding it is EXPTIME, cheaper than general containment
Confirms the Step 5 check (map S′ into S) is the right test for Eq. (15). Our motifs have no path expressions, so the simple case applies
5 Order proof
A Neuro-Symbolic Framework for Answering Graph Pattern Queries in Knowledge Graphs, 2023 (arXiv 2310.04598)
Uses the classical theorem that pattern q is contained in q′ exactly when there is a homomorphism from q′ to q, to prove an over-approximation is safe
Same proof pattern as ours: each generalized motif must over-approximate the original. Good template for writing the correctness argument
2 SNOMED loader, Check 1
Quantitatively assessing the impact of the quality of SNOMED CT subtype hierarchy on cohort queries, 2024 (PMC)
Errors in SNOMED’s IS-A hierarchy change which patients a cohort query returns
Pin one RF2 release, record it in every output, and run Check 1 against the browser. Floors protect against lifting into badly placed ancestors
1 Config, floors
Evaluation of SNOMED CT Grouper Accuracy and Coverage in Organizing the EHR Problem List by Clinical System, JMIR Med Inform 2024 (article)
SNOMED concept groupers accurately organize problem-list diagnoses by clinical system
A candidate source for floor concepts: clinically validated grouper concepts as the highest allowed lift, instead of picking floors by hand
Gap: no 2022–2026 paper turned up for the numeric and time ladders themselves. They stay clinician-defined in the config, as Table 3 of the PDF already requires (“exact original value falls inside the generalized range”, “preserve clinically required order/window”).
Step 1: Config file (all clinical choices in one place)
One YAML file holds every judgement call, so the code stays generic and a clinician can review it without reading code.
Setting
What it holds
Starting values for the synthetic motifs
Floors
Highest concept a lift may reach, per node type, plus per-anchor overrides
Disorder: Malignant neoplastic disease; M2 anchor: Diabetes mellitus; Substance and Observable: confirm in RF2
Value ladders
Ordered bins, narrow to wide, per observable or attribute
LVEF %: 30–39, ≤ 40, ≤ 49 · eGFR: 30–44, 15–59 · age: 65–69, 60–79, ≥ 18 · dose: 300–399, ≥ 250
Time ladder
Ordered windows after the exposure
0–30 d, 0–90 d, 0–365 d, any time after
Relation parents
Each patient relation and its more general parent
administered_drug → exposed_to_drug; has_finding → has_observation; others none
Protected roles
Roles that may never be removed
patient, anchor
Negation policy
Whether “absent” constraints may be dropped
false
Max depth, verify flag
Lattice depth cap; run the proof on every pair
4; on
Step 2: SNOMED loader (rf2)
• Does: reads the three Snapshot files and builds four lookups: active concepts, parents of each concept (active, inferred, IS-A only), FSN text per concept, and FSN → concept id.
• Logic: ancestors of a concept = its parents plus their ancestors, computed once and cached. “A subsumes B” = A is B or A is in B’s ancestors.
• Gotchas: read every column as text (ids are too long for numbers), tab separator, quoting turned off. Save the loaded object to disk with the RF2 release date in the file name.
• Done when: you can look up any concept’s FSN and parents in Jupyter.
Step 3: Motif loader (motif)
• Does: reads the synthetic motif JSON, fills each null code by exact FSN match, and rejects the motif if a label is missing, a field is missing, an edge points at an unknown node, or the anchor is not connected to the patient node.
• Canonical form: sort nodes by id and edges by (source, target, relation), serialise to text, hash it. Operators keep node ids, so two routes to the same candidate give the same hash.
• Done when: all four motifs load and each prints a short hash.
Step 4: The six operators (operators)
Every operator takes a motif, never changes it, and returns a list of (new motif, change record). Build and test them one at a time.
Operator
Loop over
Produces
Skip when
Concept lift
Each present, non-context clinical node
One candidate per active IS-A parent
Parent is above the floor; node is absent; node is context
Attribute removal
Each attribute (age, dose) and each node value
Candidate without that attribute or value
Node is absent
Range coarsening
Each node value or attribute with a ladder
Candidate with the next wider bin that still contains the current one
No wider bin left
Temporal coarsening
Each edge with a time window
Candidate with the next wider window; lower bound stays at 0 or more
No wider window left
Relation relaxation
Each asserted edge
Candidate with the parent relation, same direction
Relation has no parent
Edge removal
Each edge
Candidate without it; nodes no longer connected to the patient are dropped too
Edge is patient → anchor; it would drop the anchor or an absent node
The change record names the operator, the node or edge touched, and the before and after values. It is what lets the next step attribute any metric change to exactly one move.
Step 5: The independent proof (order)
• Does: answers “is S′ really more general than S?” without looking at the change record.
• Logic: turn both motifs into directed graphs and ask rustworkx’s VF2 matcher (digraph_vf2_mapping, with induced=False) for a mapping of S′ into S where every S′ node is equal-or-broader than its partner (SNOMED ancestor-or-self; reversed for absent nodes; equal for context ids; value and attribute ranges contain the partner’s) and every S′ edge has a partner edge whose relation is equal-or-narrower, same provenance, and a window inside the S′ window.
• Bonus: a patient graph is just a very specific motif, so “does patient p match S” is the same function with the patient graph in place of S. You get the matcher for free.
• Done when: the hand-made illegal cases in the next section all return false.
Step 6: Lattice builder (lattice) and outputs
• One step (neighbors): run all six operators, drop duplicates by hash, run the proof on each, stop loudly if any fails.
• Full lattice: breadth-first from the original motif, depth by depth up to the cap, keeping a hash → (motif, depth) table and a list of parent → child edges with their change records.
• Files out, per motif: a candidates file (hash, depth, motif) and an edges file (parent hash, child hash, operator, change record). Put the RF2 release date and a hash of the config in each file, so every result is traceable.
• Done when: M1–M4 run at depth 2, then depth 4, with zero proof failures.
How to check the results are right
Check in three layers: look at what each piece produces in Jupyter, compare it with a known answer you write down first, then let automatic tests guard it. The target is zero proof failures and zero containment violations on M1–M4.
Check 1: SNOMED loader matches the official browser
• Look at: for each synthetic label, a small table in Jupyter: label, SCTID found, FSN, list of parents with their FSNs, depth from root.
• Compare with: the same concept in the SNOMED CT browser (browser.ihtsdotools.org), set to the same release as your RF2. Parents and FSN must match exactly.
• Red flags: a label not found (fix the FSN text), a concept with no parents (wrong filter on relationship rows), parents that look odd (you read stated instead of inferred rows).
Check 2: Each operator, by eye, on M1
Write the expected answer before running, then print each candidate as a one-line diff from M1 (for example “n3 value: [38,38] → [30,39]”).
Operator on M1
What you should see
What would be wrong
Concept lift
One candidate per parent of breast cancer, doxorubicin and LVEF; each new FSN is a parent you saw in Check 1
A lift on the patient, TOP2B or pathway node; a jump of two levels
Attribute removal
Candidates without age, without dose, without the LVEF value
The anchor or patient node disappearing
Range coarsening
LVEF [38,38] → [30,39]; age [67,67] → [65,69]; dose [360,360] → [300,399]
A bin that does not contain the old value
Temporal coarsening
23 days → 0–30 days
A negative lower bound (that would allow “before”)
Relation relaxation
administered_drug → exposed_to_drug
Any edge changing direction
Edge removal
Drop the gene→pathway edge (pathway node goes too); drop the drug→gene edge (gene and pathway go)
Patient → breast cancer edge removed
Then walk one ladder to its end: apply range coarsening to LVEF repeatedly; you should see [38,38] → [30,39] → [0,40] → [0,49] → nothing more. Same for time: 23 → 0–30 → 0–90 → 0–365 → any time after → nothing more.
Check 3: The negation rule on M2
• Expect: “no type 1 diabetes” is never lifted and never dropped. Type 2 diabetes may lift, but never above Diabetes mellitus (its floor).
• Look at: filter M2’s candidates for any change touching node n2. The count must be 0.
Check 4: The proof catches bad candidates
Hand-build five wrong candidates from M1 and M2 and run the proof on each. All five must come back false:
1. Doxorubicin replaced by a sibling drug, not a parent.
2. LVEF range narrowed to [38,39] around a [30,39] parent, or moved to [40,49].
3. The drug → LVEF edge reversed.
4. The drug → TOP2B context edge relabelled as asserted.
5. M2’s “no type 1 diabetes” lifted to “no diabetes mellitus”.
Also run it on the identity pair (M1 vs M1): true both ways.
Check 5: Containment on synthetic patients (the real test of Eq. 15)
This is the result that proves the method works: a more general candidate must never match fewer patients.
1. Hand-make about 20 small patient graphs in the same JSON format with real SNOMED codes: some exactly like M1, some with a different anthracycline, some with LVEF 45%, some with the outcome at 60 days, some with no context edges, a few with type 1 diabetes for M2.
2. Before running anything, fill a table by hand: which patients should match the original M1. That is your gold answer for the root.
3. Run the matcher (the proof function with the patient graph in place of S) for every candidate in the M1 lattice against every patient.
4. For every lattice edge, check that the parent’s matched set is inside the child’s matched set. Count violations; it must be 0.
Seeing it: a heatmap with candidates as rows (sorted by depth) and patients as columns, filled when matched. Rows should fill in as depth goes up, never empty out along an edge. A violation shows up as a cell that is filled in a parent row but empty in its child row.
Check 6: Lattice size and shape
• Summary table per motif: candidates per depth (1, 2, 3, 4) and per operator. Expect sizes to grow fast with depth; if depth 4 is too large to inspect, keep depth 2 for review.
• Picture: load M1’s lattice to depth 2 into FalkorDB and open it in FalkorDB Browser (localhost:3000, from the FalkorDB Docker image). Root at the top, each edge labelled with its operator, each node labelled with its one-line diff from M1. You should be able to click from the root down any path and read a sensible chain of moves.
• Side-by-side view: draw M1 next to one deep candidate, with changed nodes coloured. This is the picture to show your boss.
Check 7: Clinical spot check
Sample 20 random lattice edges into a spreadsheet: parent, child, operator, change, plus two columns for a reviewer to fill: “still clinically meaningful?” and “correctly more general?”. Any “no” in the second column is a bug; “no” in the first is a floor or ladder to tighten in the config.
Check 8: Automatic tests (pytest)
Once Checks 1–7 pass by eye, freeze them as tests so later changes cannot break them silently: the ladder walks, the M2 negation count, the five illegal cases, zero containment violations, and determinism (two runs give identical hashes and files).
Open questions for the team
• Which drug class level is acceptable as a floor, and is the SNOMED substance hierarchy deep enough, or is ATC needed?
• Who signs off the value and time ladders (clinician review)?
• May negated constraints ever be dropped, and under what policy?
Amendment, 4 Nov 2026: recursive ancestor generalization
This section amends the text above; earlier sections are kept as written. The full design is in docs/plans/recursive-ancestor-generalization.md (decisions R1–R10).
Generalization versus phenotype matching
• Generalization moves up: a concept lift replaces a code by a direct IS-A parent, and repeated lifts climb the ancestors. It reads parents only.
• Phenotype matching moves down: deciding which patients or concepts a generalized motif covers means reading descendants. That is not part of generalization and is not built. The only descendant reads in the code belong to the floor policies (the PhecodeX containment rule and the descendant count in snomed_boundary).
Decisions
• R1 Default floor: floor_policy.mode is required, snomed_boundary by default, phecodex selectable. No unrestricted mode and no fallback.
• R2 Descendant ceiling: a parent passes when its strict descendant count is at most max_descendants (2500, DRAFT). The count is of distinct active transitive descendants, self excluded. It is a computational broadness heuristic, not a clinical rule.
• R3 Excluded roots: listed by FSN, each resolving to exactly one active concept or the run fails. Mechanism and disposition groupers such as Antifolate are not excluded; this is a documented limitation. The excluded subtree also contains recognised drug classes, not only chemical structures: in SNOMED release 20260201 Biguanide hypoglycemic agent (metformin's only parent) and Anthracycline (doxorubicin's only parent) sit inside it, so metformin reaches nothing under snomed_boundary (reached_floor with 0 reached), while osimertinib and methotrexate still lift through their mechanism parents. This is a known DRAFT consequence for future review; the exclusion is unchanged.
• R4 Semantic tag: a parent must have the child's FSN semantic tag; no parseable tag fails closed.
• R5 State-based lift eligibility: a value or concept-dependent attribute on the current motif blocks lifting. No historical blocking.
• R6 Removal protection (rule change): attribute_removal no longer removes a concept-dependent attribute, including unflagged ones. Guard rejects the same removal independently. Values can still be removed, so doxorubicin with a dose cannot be lifted while LVEF can lose its value and then lift. This amends D3, which had protected such attributes only from lifting.
• R7 Search limits: max_depth bounds combined operations; max_candidates (default 50000) bounds the combined lattice.
• R8 Per-node climb: from the root motif only, each liftable node follows accepted lifts until none remain. It is not bounded by max_depth or max_candidates, passes the same guard and order proof, and yields candidates with origin axis.
• R9 Termination: motif status is exhausted, depth_limited or candidate_limited, and only exhausted is complete. Per-node status is reached_floor, reached_hierarchy_top (any branch) or policy_restricted.
• R10 PhecodeX keeps its behaviour under mode phecodex. No similarity engine is built.
Termination semantics
A run reports how it stopped (termination.json) instead of implying completeness. A cap that lands on a dead end is exhausted. For an exhausted run, blocked records can differ by cap because blocks on a final dead-end frontier are not recorded. The M1–M4 results in the README are synthetic, DRAFT and not clinically validated; BioPathNet is not integrated and no patient data is used.
