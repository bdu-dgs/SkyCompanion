# TreeHacks 2026 → HackWashU: Project References and Initial Ideas

Research date: 2026-09-07 (America/Los_Angeles). These notes record the sources visited and our design judgments for further team discussion.

## Reading Scope and Evidence Limits

- Browsed all four pages of the project gallery linked by the user. The Google Cloud AI Track filter displayed 89 projects; this was not a winners list.
- Read the following 10 project detail pages closely. Features, technology, and performance descriptions primarily reflect the teams' own accounts; their products were not individually run.
- Recorded specific awards only when a detail page explicitly labeled the project a Winner. Likes, track filters, and marketing claims are not evidence of quality.
- The new ideas below are candidates developed for HackWashU. No comprehensive competitor search was conducted, and no claim of market novelty is made.

[Filtered TreeHacks project gallery](https://treehacks-2026.devpost.com/submissions/search?page=1&prize_filter%5Bprizes%5D%5B%5D=96824&utf8=%E2%9C%93)

## Confirmed HackWashU Requirements

The official page requires a working AI-powered prototype. Judging covers impact and relevance, technical execution, innovation and creativity, and user experience and presentation; weights have not been published. Only Overall Winner is currently listed. Prize details and judges are pending, with no announced sponsor tracks or industry restrictions.

Submissions should include the target users and problem, a prototype, technology and data sources, feature screenshots, reviewable demo or code materials, and an account of work completed within the official window. [Official homepage](https://hackwashu-fall-ai-2026.devpost.com/)

Projects must be developed primarily during the competition window. The rules explicitly permit advance research, sketches, and questions to explore. Existing models, APIs, datasets, and frameworks are allowed, but sources and team contributions must be disclosed. No team-size limit was found. [Rules](https://hackwashu-fall-ai-2026.devpost.com/rules)

The schedule is inconsistent: Rules and Schedule give September 25 at 10:00 through September 27 at 10:00 CT, totaling 48 hours; the homepage body gives a September 25 start at 17:00. The deadline agrees, but the start time needs confirmation with the organizers before the event. Work can conservatively be planned for 41 hours. [Schedule](https://hackwashu-fall-ai-2026.devpost.com/details/dates)

Official Resources emphasize three questions: Who is it for? What is the smallest version needed to demonstrate the idea? What can someone actually try on Sunday morning? [Resources](https://hackwashu-fall-ai-2026.devpost.com/resources)

## Lessons from 10 Projects

| Project | Features described on its page and confirmed awards | Design worth borrowing | What should not be copied or overstated |
|---|---|---|---|
| [Shepherd](https://devpost.com/software/raising-cane) | Combines iPhone LiDAR, vision, and motors to guide a white cane through physical force; detail page lists TreeHacks Grand Prize (1st) | Converts perception directly into an action the user can feel; hardware interaction closely matches the problem | Actual safety and latency are author claims; assembly, control tuning, and testing require substantial work |
| [Mira](https://devpost.com/software/mira-w65b0a) | Smart glasses, 3D room reconstruction, voice object finding, and care information; lists Most Impactful and OpenAI AI Track awards | Connects complex technology through one concrete question, “Where is my item?”; answers correspond to visible locations | The scene currently comes from one walkthrough reconstruction; continuous updates and a dedicated fall sensor are future work |
| [ContainOS](https://devpost.com/software/containos) | Wildfire decision support: physics models establish a baseline, AI analyzes it, and deterministic constraints check the result; lists an OpenAI AI Track award | Connects AI inference, rule checks, contradiction feedback, and failure fallback into a complete workflow | Claimed physical consistency does not establish validation for real emergency decisions |
| [Minerva](https://devpost.com/software/minerva-3sj6z0) | Voice-based virtual teacher invoking animations, graphics, and interactive demonstrations; lists Zoom Education Track and HeyGen awards | AI changes the teaching medium so people operate and observe rather than only read answers | The authors explicitly identify latency across multiple services as a challenge |
| [Golden Gate](https://devpost.com/software/golden-gate-l3f5xn) | Analyzes project materials, finds knowledge gaps, interviews departing staff, and produces handoff packages | Good questions arise from gaps between materials; interaction adds information absent from documents | The page also lists an automatic knowledge graph as future work; not every product description should be treated as implemented |
| [CHECKR](https://devpost.com/software/checkr-gw40jb) | Paper parsing, claim decomposition, code execution, and mathematical checking | Connects conclusions to inspectable evidence or execution results | No coverage or benchmark evidence sufficient to support “automatically verifies an entire paper” was found |
| [Savor](https://devpost.com/software/savor-2qn7ax) | Visually recognizes plate waste and connects it to menu and food-preparation recommendations | Moves from physical input to an operational decision, adding value beyond recognition alone | Accuracy is self-reported, cafeteria pilots are future work, and the public repository says empty databases are filled with demo data |
| [Rewind](https://devpost.com/software/rewind-2fyn30) | Reschedules tasks after a calendar disruption and offers an action that can start now | Targets the concrete moment when a plan stops working and demonstrates the before/after change | No need to copy six agents; product effectiveness and ADHD-related benefits have not been independently verified |
| [MCP-Forge](https://devpost.com/software/mcp-factory) | Explores websites, generates tools callable by agents, and deploys them | Makes tool discovery, generation, and invocation visible throughout; the output can be operated | Support for arbitrary websites is unverified; login and waiting are challenges, and the detail page differs from the current repository's stack |
| [Clarifyd](https://devpost.com/software/clarifyd) | Live classroom questions, explanation videos, quizzes, and a teacher dashboard | Student input changes classroom feedback, while teachers can observe understanding | The feature set is broad; a competition prototype should select one learning-feedback workflow |

These cases support our design judgment: choose a concrete moment of failure and make the AI output cause a visible, verifiable change. There is no need to copy every feature, model count, or hardware scale.

## Priority Candidate 1: ClaimTrace—Make Research Conclusions Recomputable

**Moment of use:** A student preparing a lab meeting or course report writes “improved by 35%,” but the chart, original CSV, sample scope, or baseline may disagree.

**Core change:** AI maps a natural-language conclusion to data columns, units, samples, and operations; program execution determines the number. Each conclusion retains its source, calculation definition, and a rerunnable record.

**90-second demo:** Upload a CSV and one report page → identify a denominator error → click to inspect the original text and calculation → user confirms the correct definition → replace the CSV with a newer version → automatically show whether the old conclusion still holds.

**The MVP does only three things:**

1. Extract conclusions and suggest corresponding data columns for user confirmation.
2. Support two or three restricted calculations, such as sum, mean, and percentage change.
3. Generate verification cards with sources and recompute them after data replacement.

Borrow CHECKR's evidence checking and ContainOS's rule checks. The distinction should be actual recomputation from the user's original data and invalidation of earlier conclusions when data changes, rather than merely labeling sentences true or false.

**Key risk:** The formula may be correct while the statistical definition is wrong. The interface must explicitly show the baseline, units, and population. Unmatched data should be marked unverifiable. The first version excludes causal inference, complex statistical proofs, and whole-paper review.

**Acceptance method:** Use a small, manually labeled set of report cases covering correct conclusions, arithmetic errors, unit mismatches, and insufficient evidence. Record detections and false positives; every improvement number in the demo must come from an actual run.

**Recommendation:** The safest choice while team backgrounds remain unknown, because the problem, implementation, and validation can all be narrowed easily.

## Priority Candidate 2: LabRelay—Handoff Until the Successor Can Reproduce the Result

**Moment of use:** A graduating lab member leaves a notebook, CSV, and README. A new member still cannot reproduce a key figure because a filter, parameter, or path exists only in the former member's memory.

**Core change:** A concrete reproduction task serves as the acceptance test for knowledge transfer. Run computations in a restricted environment, locate missing conditions, ask the original author a source-grounded question, save the answer, and rerun.

**90-second demo:** Select a figure → execution fails or produces a different result → AI identifies a missing filter in the README and asks about it → original author answers → generate a sourced change proposal → successor confirms and reproduces the result successfully.

**The MVP does only three things:**

1. Support one fixed Python environment and one notebook/CSV/README project.
2. Generate targeted clarification questions from execution logs and materials.
3. Save user-confirmed steps, rerun one specified result, and produce a handoff record.

Borrow Golden Gate's knowledge-gap interviews and add the acceptance condition “Can the result be reproduced?” This demonstrates a clearer distinction than generating a question-answer knowledge base from uploaded materials.

**Key risk:** Environment compatibility and automatic repair can quickly expand the scope. Support only familiar dependencies and one result in the first version. Do not promise to repair arbitrary repositories or automate wet-lab operations. Without a real, shareable handoff case, credibility will be weaker than ClaimTrace's.

**Acceptance method:** Ask a teammate unfamiliar with the original project to reproduce the specified chart independently from the handoff output. Check that previously missing parameters have explicit sources.

**Recommendation:** Prioritize this with research teammates and a real case; the technical story is deeper, but implementation risk is also higher.

## Priority Candidate 3: Counterexample Lab—Have Students Demonstrate Understanding Through Predictions

**Moment of use:** A student says “I understand” after an explanation but still believes, for example, that a classifier with higher accuracy must be better.

**Core change:** AI extracts a testable claim from the student's explanation. The student first predicts, then operates a constrained simulation, and finally answers a new transfer question.

**90-second demo:** A judge selects the better of two classifiers → change the class ratio to 99:1 → show a classifier with 99% accuracy that misses the entire minority class → the judge explains the issue → change the numbers and scenario, then test again.

**The MVP does only three things:**

1. Collect and confirm the student's own explanation.
2. Select a suitable counterexample from three prepared interactive experiments.
3. Save the difference between prediction and observation and generate one transfer question.

Borrow Minerva's interactive explanations and Clarifyd's immediate feedback. The distinction is making prior student prediction and transfer validation the main workflow. AI interprets the student; programs generate the experimental numbers.

**Key risk:** This can degrade into chat plus animation, or AI can misinterpret the student's intended claim. Confirm the claim first. Cover only one topic familiar to the team in version one, without claiming demonstrated long-term learning benefits.

**Acceptance method:** Have several students actually try it and observe whether they can apply the concept to a new example. A single pre/post test serves only as prototype validation.

**Recommendation:** Suitable for software, frontend, and design-oriented teams; judges can participate live, and external data dependencies are small.

## Three Alternative Directions

| Direction | Concrete problem and minimum prototype | Demo moment | Risks and required distinction |
|---|---|---|---|
| EventProof: Student organization event conflict checking | Input venue policies, vendor quotes, and a run-of-show; extract sourced time constraints and find conflicts with rules | Three individually reasonable files reveal that vendor entry precedes venue handover when combined; dragging a start time immediately rechecks constraints | Distinguish required, recommended, and unknown; retain cross-document constraint validation instead of becoming a summary tool |
| LastPlate: From Event Leftovers to the Next Food Order | Photograph leftover food categories, manually confirm portions, and combine registrations with attendance to plan the next order | Use an actual plate as input and immediately see which categories should change and why | A photo cannot reliably establish weight or portions; allow manual correction and avoid promising precise prediction from one photograph |
| KitRight: Assemble Donations into Complete Supply Kits | Align differently named inventories and needs, confirm substitutions, and allocate items to complete more kits | The total supply stays constant while a different allocation completes more kits; remove one item and immediately update the shortage | Confirm quantities and substitutions; compute before/after counts from actual demo data without predetermining the improvement |

EventProof extends ContainOS's constraint checks; LastPlate and KitRight extend Savor's connection from perception to operational decisions. These are design proposals, not verified needs of WashU users.

## Selecting an Idea and Controlling Workload

- Estimates provisionally assume a small software team; team skills, size, and available equipment are still unknown.
- **Safest priority: ClaimTrace.** First demonstrate reliable checking of one report page and one CSV.
- **With a real research handoff case: LabRelay.** First demonstrate that a newcomer can reproduce one figure.
- **For live participation: Counterexample Lab.** First demonstrate that a counterexample exposes one common misconception.
- **With existing student organization users: EventProof.** Materials are easier to obtain, and validation is direct.
- With hardware teammates, borrow Shepherd's and Mira's input/output design, but confirm equipment availability and a sufficiently narrow user task before adding hardware.

Before the event, complete interviews, problem prioritization, interaction sketches, public-data and API availability checks, and dependency/license research. Keep the main product implementation within the competition window.

Conservatively allocate 41 hours: first 4 hours to fix one user and acceptance scenario; next 14 hours to connect the core workflow; another 10 hours for uncertain inputs and failure recovery; 7 hours for user trials and adjustments; final 6 hours to freeze features and prepare the demo and submission.

The demo should include concrete input, AI processing, visible evidence, one user correction, and a usable final result. Before selecting an idea, answer: Which step becomes impossible without AI? How will an incorrect AI judgment be discovered? What can the judges actually operate on Sunday?
