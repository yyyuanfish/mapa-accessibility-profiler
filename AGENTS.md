# AGENTS.md

## Thesis Writing Rules (read before every writing task)

- **Plain words over invented compounds.** Do not coin hyphenated or unusual compound terms (e.g. "speech-ready instructions", "route-relevant functional requirements", "falsely reassuring outputs", "learned communication-topology approaches", "evidence-grounded route adaptation"). Use the simplest everyday academic wording a reader understands at first glance ("spoken instructions", "the needs that matter for a route", "wrong safety claims", "agents that learn how to coordinate", "route changes backed by real data"). A non-standard compound is allowed **only if both** hold: (1) it recurs many times later (like `MAPA`), and (2) it is briefly explained at first use. Otherwise rewrite it.
- **Lead with the point.** Open every paragraph with one to three sentences stating its main point, then expand. Open every (sub)section by saying in one sentence what it covers and in what form, so the reader is never unsure why to keep reading.
- **Few or no em-dashes.** Avoid the `---` / "—" dash construction; it reads as AI-generated. Use a comma, colon, or a new sentence instead.
- **Keep it short and compact.** Target ~40 pages total. Cut background and literature that is not needed for the methodology or the contributions; move useful-but-secondary citations to Related Work. Do not add length that does not add meaning.
- **No negative definitions.** Never define a concept as "not X" or "rather than Y". State what something IS, not what it is not. Example: instead of "an agent is a workflow role, not an open-ended conversational agent", write "an agent is an executable workflow role with typed inputs, typed outputs, and traceable state updates."
- **No redundant closing sentences.** Do not end a paragraph by restating what the previous sentence already said (e.g. "This makes the boundary explicit" after already explaining the boundary).
- **Keep the spine consistent.** The Abstract claims, Problem Statement gaps, Research Questions, Contributions, and Conclusion must echo each other (same three contributions, same order). The Abstract states contributions and outcomes **without numbers** ("reaches higher accuracy through follow-up questions", not "F1 0.847 to 0.879"); numbers live in Results and Conclusion. When the English abstract or contributions change, update the German `Zusammenfassung` to match.
- **Define every acronym/short name at first use**, in the body and in the abstract: full term first, short form in parentheses, e.g. "Multimodal multi-Agent Profiling for Accessibility (MAPA)". After that, use the short form only.
- **Do not explain well-known software.** Tools every reader already knows (Python, JSON, FastAPI, Pydantic, LangGraph, React, Vite, Whisper, etc.) are not contributions. Do not describe or repeatedly name them. Mention a tool only when a *specific method* of it, or a *choice between two options*, carries the contribution (e.g. "the schema is validated and serialized as JSON"; "we chose X over Y because ..."). Otherwise drop the name or mention it once in passing.
- Use `pipeline` when referring to the planning graph; reserve `workflow` for the profiling dialogue or when referring to both together.

## Mission
Build and maintain an offline-first **Multimodal Accessibility Profiling Agent for Personalized Journey Planning**.

Core outcomes:
- Run a short consent-first profiling dialogue (functional needs only).
- Produce validated JSON user profiles (JSON Schema v1 + Pydantic).
- Personalize route guidance using fixed route examples and explicit route facts.
- Orchestrate multi-agent pipelines via **LangGraph** with parallel execution.
- Expose REST + SSE streaming APIs via **FastAPI**.
- Serve a **React / TypeScript** frontend (Vite + Shadcn/Radix UI).
- Keep multimodal image analysis optional and explicitly consent-gated.
- Support three runtime modes:
  - **Mock** — deterministic offline, no model server
  - **Ollama** — local LLM (`qwen3.5:4b`) + vision (`llava:7b`), no cloud API key
  - **Backend** — React frontend calls FastAPI endpoints

## Pipeline Architecture

### Profile Pipeline (multi-turn dialogue)
```
consent_guard_node
      |
profiler_node           <- ProfilerAgent.process_turn()
      |
profile_manager_node    <- ProfilerAgent.build_profile()
      |
conversation_orchestrator_node
      |
     END
```

### Planning Pipeline (single-shot, Zurich-enriched parallel fan-out)
```
input_validator_node
      |
zurich_data_fetcher_node
      |
 +---------+---------+---------------+
 |                   |               |
route_reasoner    image_hazard   amenity_locator   <- parallel
 |                   |               |
 +---------+---------+---------------+
           |
  hazard_fusion_node
           |
     planner_node       <- PlannerAgent.create_plan()
           |
    synthesis_node
           |
          END
```

See `pipeline_workflow.html` for the interactive diagram.

## Product Rules
- Never infer medical diagnoses.
- Ask minimal, non-intrusive questions and always allow skip.
- Always include a recap confirmation: "Here is what I understood... Is this correct?"
- Never claim real-world accessibility unless route data explicitly contains it.
- Keep all model calls behind provider interfaces (`LLMProvider`, `RouteProvider`, `ImageProvider`).
- Default runtime is offline with mock providers.
- If local model calls fail, degrade gracefully to mock behavior where implemented.
- Agent outputs must be strict JSON validated by Pydantic.
- If JSON parsing fails, retry once with a strict instruction to return JSON only.
- If cognitive/readability needs are detected (or requested), switch output to Simple English.

## Thesis Writing Rules
When revising the thesis, act as a senior computational linguistics writing advisor. Follow UZH CL thesis style: controlled claims, clear scope boundaries, evidence-led argumentation, and explicit separation between data, system design, implementation, evaluation, results, limitations, and future work.

For each chapter or subsection request:
- First decide whether the user's proposed paragraph can be kept. Preserve correct content and avoid unnecessary rewriting.
- Before rewriting, separate correct prose from prose that only needs structural movement, citation tightening, or style cleanup. Do not rewrite already correct sentences only for variation.
- Identify the job of the section before editing: motivation, dataset description, system design, implementation detail, evaluation setup, result interpretation, or discussion.
- Keep the chapter logic in a clear whole-part-whole structure: opening context, ordered subsections, and a short closing link to the next chapter or results.
- For `Related Work`, keep a whole-part-whole structure: begin with an overview subsection that explains the historical and thematic path of the literature, organize the main sections by problem area, and end with a positioning section that briefly reviews how the chapter supports the thesis scope.
- Before each major Related Work subsection, connect it to the previous subsection or to the chapter argument in one or two sentences. Do not let subsections read as independent paper summaries.
- End each major Related Work subsection with a short bridge that explains why the next theme is needed or how the theme positions MAPA.
- Ensure every paragraph has a concrete function and connects to MAPA as a personalized multimodal accessibility planning system.
- Use short, natural academic sentences. Avoid inflated novelty claims, long stacked clauses, uncommon invented phrases, and generic AI-sounding transitions.
- Minimize em-dash usage. Prefer commas, semicolons, parentheses, or separate sentences over em-dashes. Use an em-dash only when no other punctuation works naturally. Never use more than one em-dash pair per paragraph.
- Keep citations tied to specific claims. Do not add or invent citations unless they are verified or already present in the thesis bibliography.
- Avoid citation pile-ups. Do not place several citations after one broad sentence unless all sources support the exact same narrow claim. Prefer splitting the sentence so each concrete claim has the citation that directly supports it.
- In contribution and positioning paragraphs, lead with what the thesis does. Avoid opening with repeated negative framing such as "not X, not Y, not Z." Mention limits only when they protect the claim, and place them after the positive contribution using concise scope wording.
- Outside dedicated `Limitations`, `Future Work`, or explicit error-analysis sections, define MAPA by implemented and evaluated behaviour. Avoid describing scope mainly through absent features, repeated "not/no" phrasing, or lists of unimplemented product capabilities; when a boundary is needed, first state the realised prototype, evidence source, or evaluation contract, then add one concise boundary sentence.
- In thesis prose about accessibility profiles, do not define the profile by saying what it is not. Avoid phrases such as "not diagnosis", "not diagnostic labels", "rather than diagnostic categories", or any repeated "not X but Y" contrast. State the positive design object directly: route-relevant functional needs, profile fields, support preferences, planning constraints, or validated profile representation.
- Add a table, figure, schema, or chart only when the subsection needs it for comparison, categories, workflow, architecture, or real metrics. If prose is clearer, do not add a visual element.

Chapter boundary rules:
- `Datasets` should contain only data, materials, fixed evaluation inputs, and their role in reproducibility or grounding.
- `Datasets` may discuss profile evaluation targets, route fixtures, persona scripts, automated tests, Zurich open-data feeds, map/interface inputs, and generated evaluation files.
- `Datasets` should not explain the architecture of the profile schema, the planner, LangGraph workflows, backend logic, or frontend design as design objects. Move that material to `Method and System Design`.
- `Method and System Design` should contain the profile schema, planning interface, system architecture, agent workflows, implementation choices, provider abstractions, and multimodal interaction design.
- `Results` should report observed outcomes and metric-based findings. Interpretations and limitations should be calibrated and should not overclaim user benefit beyond the evidence.

When improving a Datasets overview, make the data role explicit: data fixes what counts as a relevant need, which route facts may justify adaptation, and which cases are used for comparison. The section should then introduce the following subsections in order: profile evaluation targets, fixed route examples and location data, persona scripts and test material, Zurich open data, map/interface data, generated evaluation files, and a short chapter summary.

For mixed Chinese-English thesis revision prompts:
- Treat the user's mixed-language paragraph as intent notes, not final prose.
- First map each requested claim to existing thesis evidence: bibliography entries, result tables, generated CSV/JSON files, code fixtures, or explicit scope limits.
- Before adding citations, check whether the cited work already exists in `YuanYu_Bachelor_cl-thesis/biblio/thesis.bib`. Prefer existing verified entries. Do not invent BibTeX or cite unverified papers.
- For evidence-heavy revisions, create or update `plan/evidence-map.md`, `plan/chapter-blueprints/<section>-blueprint.md`, and `plan/review/evidence-coverage.md` before editing the chapter.
- Rewrite the target section in three passes: evidence alignment, chapter-boundary cleanup, and humanized academic prose.
- When extending a chapter after rewriting an overview, add only content that the overview has prepared the reader for and that later results or methods actually support.
- Keep Datasets prose tied to materials and experiment setup. Mention result scale or generated files when needed, but leave metric interpretation to `Results`.
- When the user asks to add a figure, table, schema, or chart to a thesis subsection, first decide what the subsection needs. Use a LaTeX table for categorical examples, labels, datasets, or evaluation targets; use a diagram only for workflows or architecture; use a numerical plot only when there are real metrics. Do not add decorative figures to the Datasets chapter.
- For profile evaluation target sections, prefer a compact example table that maps dialogue cues to expected active labels and evaluation meaning. Keep the full schema explanation in `Method and System Design`.
- Remove translationese, formulaic transitions, inflated importance claims, and AI-sounding lists. Prefer direct sentences with a clear subject and one main relation.
- Vary transitions across adjacent sentences and paragraphs. Do not repeat the same connector or sentence opening unless the repetition carries a deliberate logical function.
- Before finalizing thesis prose, run a reviewer-readability pass. Replace unexplained acronyms, coordinate-system names, implementation jargon, and invented phrases with plain terms. Examples: write "latitude and longitude coordinates" instead of "WGS84 coordinates", "City of Zurich data feeds" instead of "WFS feeds", and "OpenStreetMap map tiles" instead of "OSM tiles". Keep a technical term only if it is necessary, defined on first use, and used consistently afterward.
- **No software names in figure captions or system description prose.** Do not name specific frameworks or libraries (FastAPI, Pydantic, React, Vite, LangGraph, Ollama, etc.) in figure captions or running system descriptions unless the sentence is explicitly about that tool's design role. Use generic architectural terms instead: "backend pipeline", "frontend", "schema validation", "graph-based orchestration", "local language model".
- After editing, compile or at least run a LaTeX syntax check when feasible, and report any unresolved warnings separately from content changes.

## Target User Types
The system must explicitly support:
- Blind / low-vision users
- Deaf / hard-of-hearing users
- Sign-language users
- Wheelchair / mobility disability users
- Users with reading or memory difficulty, cognitive load concerns, or children

## Definition of Done (DoD)
A change is complete only if:
- All profile and plan schemas validate.
- `pytest -q` passes.
- FastAPI server starts and all endpoints respond (`/api/health`, `/api/routes`, `/api/zurich/data`, `/api/audio/transcribe`, `/api/profile/turn`, `/api/profile/stream`, `/api/plan`, `/api/plan/stream`).
- React frontend builds and connects to the backend in "Backend" mode.
- SSE streaming shows per-node progress for both pipelines.
- Route fixtures include: `route_with_stairs`, `step_free_route`, `long_walk_route`.
- Evaluation harness runs all personas and returns precision/recall metrics.

## Academic Writing Skills (auto-load on thesis revision)

When revising thesis prose, always load and follow these skills. Do not wait for the user to invoke them explicitly.

### Core skills (always active during thesis editing)
| Skill | Path | Purpose |
|-------|------|---------|
| UZH CL Thesis Writing | `/Users/yuanyu/.agents/skills/uzh-cl-thesis-writing/SKILL.md` | UZH voice, calibrated claims, scope boundaries, section patterns |
| Writing Core (去AI化) | `research-writing-skill/skills/writing-core/SKILL.md` | De-AI rules, forbidden words, sentence-level norms |
| Prompts Collection | `research-writing-skill/skills/prompts-collection/SKILL.md` | Translation, polishing, de-AI templates, AI word blacklist |
| ML Paper Writing | `/Users/yuanyu/.codex/skills/ml-paper-writing/SKILL.md` | Citation hygiene, argument structure, conference-level prose |
| Systems Paper Writing | `/Users/yuanyu/.codex/skills/systems-paper-writing/SKILL.md` | Paragraph blueprints, design section structure, evaluation framing |

### Supplementary skills (load when relevant)
| Skill | Path | When to use |
|-------|------|-------------|
| Evidence-Driven Writing | `research-writing-skill/skills/evidence-driven-writing/SKILL.md` | Introduction, Related Work, literature-backed claims |
| Peer Review | `research-writing-skill/skills/peer-review/SKILL.md` | Self-review, rigor check before output |
| Rigor Reviewer | `/Users/yuanyu/.codex/skills/rigor-reviewer/SKILL.md` | Epistemic review, overclaim detection |
| Humanizer | `/Users/yuanyu/.codex/skills/humanizer/SKILL.md` | Final de-AI pass, lower AI detection score |
| LaTeX Output | `research-writing-skill/skills/latex-output/SKILL.md` | LaTeX formatting, compilation |
| Literature Review | `research-writing-skill/skills/literature-review/SKILL.md` | Literature search, citation verification |

### Post-edit checklist (run before returning output to user)
1. **AI word scan**: grep for leverage, delve, tapestry, underscore, pivotal, nuanced, foster, elucidate, intricate, paramount, utilize, facilitate, comprehensive, robust, streamline, cutting-edge, groundbreaking, novel (unless evidence-backed).
2. **Sentence pattern scan**: check for 3+ adjacent sentences with same opener structure (e.g., "The system...", "The planner...", "The profile...").
3. **Transition scan**: no "First/Second/Third/Finally" enumeration in prose paragraphs; no "Furthermore/Moreover/Additionally" stacking.
4. **Claim calibration**: every "shows/demonstrates/proves" must have a cited source or an evaluation result behind it.
5. **Compile check**: run `pdflatex -interaction=nonstopmode` and report errors.

## Standard Commands
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q

# Backend
uvicorn backend.app.api:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

## Engineering Notes
- Keep the profile schema identifier explicit (`accessibility_profile`).
- Preserve deterministic behavior for mock providers to keep tests stable.
- LangGraph `TypedDict` state uses `Annotated[list, operator.add]` for parallel-safe trace merging.
- Default Ollama model: `qwen3.5:4b` (text), `llava:7b` (vision).
- Keep documentation aligned with actual code paths and fallback behavior.
