import asyncio

# Queue globale pour tous les jobs
job_queue: asyncio.Queue = asyncio.Queue()