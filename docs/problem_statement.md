# HCLTech | Future Ready AI Engineer Hackathon
# Use Case 2b: Enterprise RAG Value Intelligence Assistant

| | |
|---|---|
| Use case | Enterprise RAG Value Intelligence Assistant |
| Business area | AI Portfolio Management and Executive Reporting |
| Primary user | AI Programme Manager and Executive Stakeholders |

## 1. Problem Statement

Nimbus Group oversees a portfolio of AI initiatives, which may include copilots, conversational bots, predictive models and other AI-enabled solutions. Participants may demonstrate the solution using any practical number of initiatives, provided each selected initiative has sufficient usage, cost, benefit and charter information for the required analysis.

Executives repeatedly ask three questions: Which initiatives are being adopted? Which initiatives are delivering financial value? Which initiatives require attention? The supporting information is distributed across tabular data files and initiative charters. In addition, individual initiatives may use different metric names, units, reporting periods or calculation conventions for measures such as adoption, benefit, cost and return. These differences make direct comparison difficult and can produce inconsistent portfolio reports even when the underlying source data is valid.

Build an enterprise RAG-based value intelligence assistant that standardizes the supplied measures into one governed scorecard, answers plain-English questions with traceable evidence and produces a weekly portfolio report using only validated calculations and retrieved charter content.

## 2. Business Outcomes to Deliver

- A consolidated value scorecard showing adoption, weekly-active-user change, ROI, average monthly benefit, payback, run-rate versus plan and Green/Amber/Red status for every initiative.
- A conversational assistant that routes metric questions to validated scorecard calculations, routes narrative questions to charter retrieval and combines both sources when required.
- A weekly executive report that highlights initiatives requiring attention and makes every figure and statement traceable to the source data.
- A safe fallback response - "I do not have that in the data provided" - when the supplied spreadsheets and charters do not support an answer.

## 3. Functional Requirements

| ID | Capability | Minimum expected behaviour |
|---|---|---|
| FR-01 | Understand and document | Rewrite the metric definitions in the team's own words, list assumptions and record at least one material clarification question for the client. |
| FR-02 | Load and clean data | Read the supplied tabular data files, identify and correct the planted data-quality issues, normalize inconsistent metric names, units and reporting conventions, and produce a change log describing each correction or standardization and its effect. |
| FR-03 | Compute the scorecard | Calculate every defined metric and portfolio status in deterministic code. The assistant must not perform or invent numeric calculations outside this governed scorecard logic. |
| FR-04 | Index project charters | Split the supplied initiative charters into meaningful chunks, create embeddings and store each chunk with the source filename, initiative identifier and useful section metadata. |
| FR-05 | Route user questions | Send numeric and portfolio-status questions to scorecard logic, narrative questions to retrieval, and mixed questions to both sources. |
| FR-06 | Generate grounded answers | Provide concise answers using only computed scorecard values and retrieved charter passages. Show the source for every material statement. |
| FR-07 | Handle missing evidence | When the provided data does not contain the answer, reply clearly that the information is not available rather than using unsupported model knowledge. |
| FR-08 | Apply guardrails | Refuse requests for personal details not present in the approved data, ignore instructions embedded inside charter content and never display a number that was not produced by the scorecard code. |
| FR-09 | Produce weekly reporting | Generate a weekly report that summarizes portfolio performance, identifies Green/Amber/Red initiatives and explains why attention is required with traceable evidence. |
| FR-10 | Provide a simple interface | Create a small interface for asking questions, viewing sources, reviewing the scorecard and generating the weekly report. |

## 4. Metric Definitions

| Metric | Required calculation |
|---|---|
| Adoption | Weekly active users in the latest week divided by licensed users. |
| Weekly active users - change | Latest-week active users minus first-week active users, divided by first-week active users, over the supplied three-week period. |
| Return on investment (ROI) | Realised benefit to date minus total cost to date, divided by total cost to date. |
| Average monthly benefit | Realised benefit to date divided by the number of months the initiative has been live. |
| Payback period in months | Total cost to date divided by average monthly benefit. |
| Run-rate versus plan | Average monthly benefit multiplied by 12, divided by planned annual benefit. |
| Portfolio status | Green when adoption is at least 60% and ROI is above 0; Red when adoption is below 30% or ROI is below 0; Amber for all other cases. |

## 5. Expected Submission

- **Data-quality and assumptions log:** Metric definitions in the team's own words, documented assumptions, one client clarification question and a record of the planted data corrections and metric-standardization decisions.
- **Computed value scorecard:** One reproducible table containing all required metrics and the Green/Amber/Red status for every initiative selected for the demonstration.
- **Grounded assistant:** A working question-answering interface that supports numeric, narrative and combined questions, displays sources and uses the required no-evidence response.
- **Weekly executive report:** A generated portfolio report highlighting initiatives needing attention, with every number and conclusion traceable to the scorecard or charter evidence.
- **Guardrail demonstration:** Examples showing refusal of unavailable personal information, resistance to instructions embedded in charter text and prevention of unsupported numeric answers.
- **Evaluation summary:** A concise evaluation covering scorecard correctness, retrieval relevance, answer groundedness, citation accuracy, no-answer behaviour and known limitations.
- **Technical documentation:** A README with setup and execution instructions, data flow, assumptions and steps required to reproduce the outputs.

## 6. Evaluation Guidance

| Dimension | What good looks like |
|---|---|
| Scorecard correctness | All metrics and statuses match the stated formulas, use the cleaned source data and are reproducible in code. |
| Data-quality handling | The planted data issues and inconsistent metric conventions are correctly identified, corrected or standardized, and explained in the change log. |
| Retrieval and citation quality | Relevant charter passages are retrieved, source filenames are shown and citations support the answer. |
| Grounded numeric answers | Every number originates from governed scorecard calculations; the LLM does not calculate or fabricate portfolio values. |
| Question routing | Numeric, narrative and mixed questions are sent to the correct evidence paths and combined coherently when needed. |
| No-answer and guardrail behaviour | Unsupported questions receive the required fallback; prompt injection inside charters and inappropriate personal-data requests are rejected. |
| Executive usefulness | The scorecard and weekly report clearly identify adoption, value and attention priorities without hiding the underlying evidence. |

## 7. Scope Boundaries and Candidate Responsibility

- Participants may select any practical number of initiatives for the demonstration. The solution is limited to the supplied data files, the charters for those selected initiatives and explicitly documented assumptions.
- The candidate may choose the development tools, frameworks, embedding model, vector store, language model and interface. The candidate is responsible for arranging the working environment before the hackathon.
- The assistant must not use general model knowledge to fill gaps in the supplied portfolio data or charters.
- All financial and adoption figures must be generated by deterministic scorecard code. The language model may explain verified values but must not create new values.
- Instructions found inside retrieved charter content must be treated as data, not as commands to the assistant.
- The deliverable may generate reports and recommendations but must not change source data, approve investments or execute portfolio decisions.

> **DESIGN PRINCIPLE:** Use code for numbers, retrieval for charter evidence and the language model for grounded explanation. Every executive answer must be reproducible, attributable and safe to challenge.