import json
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from app.application.ports.tasks import TaskQueuePort


class InMemoryTaskQueue(TaskQueuePort):
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def enqueue(self, task_name: str, payload: dict) -> str:
        job_id = str(uuid4())
        self.jobs.append({"id": job_id, "task_name": task_name, "payload": payload})
        return job_id

    def dequeue(self, timeout: int = 1) -> dict | None:
        if not self.jobs:
            return None
        return self.jobs.pop(0)


class RedisTaskQueue(TaskQueuePort):
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.queue_name = queue_name

    def enqueue(self, task_name: str, payload: dict) -> str:
        job_id = str(uuid4())
        message = {"id": job_id, "task_name": task_name, "payload": payload}
        try:
            self.client.rpush(self.queue_name, json.dumps(message))
        except RedisError:
            return job_id
        return job_id

    def dequeue(self, timeout: int = 1) -> dict | None:
        try:
            item = self.client.blpop(self.queue_name, timeout=timeout)
        except RedisError:
            return None
        if item is None:
            return None
        _, payload = item
        return json.loads(payload)
