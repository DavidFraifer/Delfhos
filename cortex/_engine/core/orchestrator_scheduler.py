"""
OrchestratorSchedulerMixin

Background asyncio scheduler that drains an async message queue and spawns
_process_message_async tasks.  Intended to be mixed into the Orchestrator class.
"""

import asyncio
import threading
import uuid


class OrchestratorSchedulerMixin:
    """Mixin that adds the background-scheduler loop to the Orchestrator."""

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self):
        if not self.running:
            self.running = True
            self._scheduler_ready.clear()
            self.scheduler_thread = threading.Thread(
                target=self._scheduler_worker, daemon=True
            )
            self.scheduler_thread.start()
            self._scheduler_ready.wait(timeout=2.0)

    def stop(self):
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join()

    # ------------------------------------------------------------------ #
    #  Message intake                                                      #
    # ------------------------------------------------------------------ #

    def receive_message(self, message):
        if self.running and self._scheduler_loop and self._async_queue:
            self._scheduler_loop.call_soon_threadsafe(
                self._async_queue.put_nowait, message
            )
        elif self.running:
            if (
                self._scheduler_ready.wait(timeout=1.0)
                and self._scheduler_loop
                and self._async_queue
            ):
                self._scheduler_loop.call_soon_threadsafe(
                    self._async_queue.put_nowait, message
                )
        return self.running

    # ------------------------------------------------------------------ #
    #  Background worker                                                   #
    # ------------------------------------------------------------------ #

    def _cleanup_wait_times_if_needed(self):
        if len(self.wait_times) > self.MAX_WAIT_TIMES_ENTRIES:
            keep_count = self.MAX_WAIT_TIMES_ENTRIES // 2
            sorted_tasks = sorted(self.wait_times.keys())
            for task_id in sorted_tasks[:-keep_count] if len(sorted_tasks) > keep_count else []:
                self.wait_times.pop(task_id, None)

    def _scheduler_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._scheduler_loop = loop
        self._async_queue = asyncio.Queue()
        self._scheduler_ready.set()
        running_tasks: set = set()

        async def scheduler_loop():
            nonlocal running_tasks
            while self.running:
                # Drain any pre-enqueued messages (race-condition safety)
                while not self._async_queue.empty():
                    try:
                        message = self._async_queue.get_nowait()
                        task = asyncio.create_task(self._process_message_async(message))
                        running_tasks.add(task)
                        running_tasks -= {t for t in running_tasks if t.done()}
                    except asyncio.QueueEmpty:
                        break

                try:
                    message = await asyncio.wait_for(self._async_queue.get(), timeout=0.2)
                    task = asyncio.create_task(self._process_message_async(message))
                    running_tasks.add(task)
                    running_tasks -= {t for t in running_tasks if t.done()}
                except asyncio.TimeoutError:
                    pass  # Heartbeat to re-check self.running

        try:
            loop.run_until_complete(scheduler_loop())
            if running_tasks:
                loop.run_until_complete(
                    asyncio.gather(*running_tasks, return_exceptions=True)
                )
        except (RuntimeError, asyncio.CancelledError):
            pass  # normal shutdown path: loop stopped or tasks cancelled
        finally:
            self._scheduler_loop = None
            self._async_queue = None
            loop.close()
