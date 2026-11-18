# Knowledge graph (Neo4j)

Run from the repo root. Needs a running local Neo4j.

```bash
uv sync
export NEO4J_PASSWORD=yourpassword
```

## Option A: restore the saved graph

In Neo4j Desktop, create a new instance from the file
`career_coach/knowledge_graph/data/careercoach-demo.dump`, start it, then check it:

```bash
uv run --with neo4j python -m career_coach.knowledge_graph.validate_graph
```

## Option B: rebuild the graph
First Neo4j has to been from your Desktop machine, start any new instance

```bash
uv run --with neo4j python -m career_coach.knowledge_graph.load_neo4j career_coach/knowledge_graph/data/raw/resume-dataset/demo.json
uv run --with neo4j python -m career_coach.knowledge_graph.validate_graph
```

## Add one resume

```bash
uv run --with neo4j python -m career_coach.knowledge_graph.add_resume path/to/resume.pdf
```
