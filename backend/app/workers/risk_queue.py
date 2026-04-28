import asyncio

# Queue dédiée aux jobs d'analyse de risques (séparée de la queue refinement)
risk_job_queue: asyncio.Queue = asyncio.Queue()
