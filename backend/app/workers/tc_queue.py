import asyncio

# Dedicated queue for test case generation jobs (separate from US refinement and risk queues)
tc_job_queue: asyncio.Queue = asyncio.Queue()
