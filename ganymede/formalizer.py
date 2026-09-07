"""The Aristotle side: a thin async wrapper over aristotlelib, plus a fake for tests.

The orchestrator only sees TaskResult and the answer_question callback; everything about
projects, tasks, and SSE streams stays in here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger("ganymede.aristotle")

# Called when Aristotle asks a question. Gets (question, suggestions, recent event lines), returns the answer.
QuestionHandler = Callable[[str, list[str], list[str]], Awaitable[str]]


@dataclass
class TaskResult:
    task_id: str
    status: str                 # aristotlelib TaskStatus name: COMPLETE, COMPLETE_WITH_ERRORS, OUT_OF_BUDGET, FAILED, CANCELED, TIMEOUT
    summary: str | None
    events: list[str] = field(default_factory=list)
    questions_answered: int = 0


class Formalizer(Protocol):
    project_id: str | None

    async def create(self, prompt: str, project_dir: Path | None) -> str: ...
    async def instruct(self, prompt: str, files: list[Path] | None = None) -> str: ...
    async def run(self, task_id: str, on_question: QuestionHandler, max_hours: float) -> TaskResult: ...
    async def download(self, destination: Path) -> Path: ...
    async def cancel(self, task_id: str) -> None: ...


class AristotleFormalizer:
    def __init__(self, project_id: str | None = None, allow_questions: bool = True):
        from aristotlelib import AgentQuestionsSetting

        self.project_id = project_id
        self.questions = AgentQuestionsSetting.TIMEOUT_15_MIN if allow_questions else AgentQuestionsSetting.DISABLED

    async def _project(self):
        from aristotlelib import Project

        if not self.project_id:
            raise RuntimeError("no Aristotle project yet")
        return await Project.from_id(self.project_id)

    async def create(self, prompt: str, project_dir: Path | None) -> str:
        from aristotlelib import Project

        if project_dir is not None:
            project = await Project.create_from_directory(prompt, project_dir, agent_questions_setting=self.questions)
        else:
            project = await Project.create(prompt, agent_questions_setting=self.questions)
        self.project_id = project.project_id
        tasks, _ = await project.get_tasks(limit=1)
        if not tasks:
            raise RuntimeError(f"project {self.project_id} created but has no task")
        return tasks[0].agent_task_id

    async def instruct(self, prompt: str, files: list[Path] | None = None) -> str:
        from aristotlelib import FollowUpMode

        project = await self._project()
        task = await project.ask(prompt, mode=FollowUpMode.INSTRUCT, files=files or None, agent_questions_setting=self.questions)
        return task.agent_task_id

    async def run(self, task_id: str, on_question: QuestionHandler, max_hours: float) -> TaskResult:
        """Stream events until the task finishes. Answers AGENT_QUESTIONs via on_question. Cancels on timeout."""
        from aristotlelib import AgentTask, AristotleRequestClient, Event, EventStatus, EventType, TaskStatus

        task = await AgentTask.from_id(task_id)
        recent: list[str] = []
        answered = 0
        deadline = time.monotonic() + max_hours * 3600

        async def stream():
            nonlocal answered
            async with AristotleRequestClient() as client:
                async for data in client.stream_sse(f"/task/{task_id}/events-stream"):
                    try:
                        event = Event.model_validate(data)
                    except Exception:  # noqa: BLE001
                        continue
                    line = str(event)
                    recent.append(line)
                    del recent[:-40]
                    log.info("aristotle: %s", line[:300])
                    if event.event_type == EventType.AGENT_QUESTION and event.status == EventStatus.SENT and event.explanation is None:
                        try:
                            reply = await asyncio.wait_for(on_question(event.content, event.suggestions or [], list(recent)), timeout=13 * 60)
                            await event.answer(reply)
                            answered += 1
                            log.info("answered aristotle: %s", reply[:300])
                        except Exception as e:  # noqa: BLE001
                            log.error("failed to answer Aristotle's question: %s", e)

        try:
            await asyncio.wait_for(stream(), timeout=max(deadline - time.monotonic(), 1))
            status_name = None
        except asyncio.TimeoutError:
            log.warning("task %s exceeded %.1f h; cancelling", task_id, max_hours)
            await task.cancel()
            status_name = "TIMEOUT"

        await task.refresh()
        if status_name is None:
            status_name = task.status.name if isinstance(task.status, TaskStatus) else str(task.status)
        return TaskResult(task_id=task_id, status=status_name, summary=task.output_summary, events=list(recent), questions_answered=answered)

    async def download(self, destination: Path) -> Path:
        project = await self._project()
        return await project.get_files(destination)

    async def cancel(self, task_id: str) -> None:
        from aristotlelib import AgentTask

        task = await AgentTask.from_id(task_id)
        await task.cancel()


class FakeFormalizer:
    """Scripted Aristotle for tests. Each scripted step is a (status, tarball_path, question|None) tuple."""

    def __init__(self, script: list[tuple[str, Path | None, str | None]]):
        self.script = list(script)
        self.project_id: str | None = None
        self.prompts: list[str] = []
        self.answers: list[str] = []
        self.cancelled: list[str] = []
        self._n = 0
        self._current_tarball: Path | None = None

    async def create(self, prompt, project_dir):
        self.project_id = "fake-project"
        return await self.instruct(prompt)

    async def instruct(self, prompt, files=None):
        self.prompts.append(prompt)
        self._n += 1
        return f"task-{self._n}"

    async def run(self, task_id, on_question, max_hours):
        status, tarball, question = self.script.pop(0)
        answered = 0
        if question:
            self.answers.append(await on_question(question, ["yes", "no"], ["THINKING: hmm"]))
            answered = 1
        self._current_tarball = tarball
        return TaskResult(task_id=task_id, status=status, summary=f"fake summary for {task_id}", events=["FINISHED: done"], questions_answered=answered)

    async def download(self, destination):
        import shutil

        shutil.copy(self._current_tarball, destination)
        return destination

    async def cancel(self, task_id):
        self.cancelled.append(task_id)
