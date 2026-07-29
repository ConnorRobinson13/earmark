"""Values baked into the schema, not configuration.

These are fixed at migration time — changing one requires a migration and a
re-embed, not an environment variable — so they live here rather than in
`Settings`, and importing them costs nothing.
"""

# Dimensionality of `mxbai-embed-large`, the model behind `transactions.embedding`.
EMBEDDING_DIM = 1024
