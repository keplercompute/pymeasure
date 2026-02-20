#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2022 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

"""Flask/SocketIO-based replacement for the Qt display/manager.py and
display/listeners.py modules.  Zero Qt imports.
"""

import logging
import threading
import uuid
from os import remove as rmfile
from os.path import basename

from ..experiment import Procedure
from ..experiment.workers import Worker, Analyzer

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Experiment – plain dataclass, no QObject
# ---------------------------------------------------------------------------

class Experiment:
    """Groups a :class:`.Results` object with its experiment id and display
    color.  Acts as a plain data container with no Qt dependency.

    :param results: :class:`.Results` object produced before queuing.
    :param eid: Unique string identifier for this experiment.  A UUID4 is
        generated automatically when *eid* is ``None``.
    :param color: An arbitrary color token (e.g. ``"#1f77b4"``) used by the
        JS frontend to distinguish experiment traces.
    :param progress: Current progress value in the range 0–100.
    """

    def __init__(self, results, eid=None, color="#1f77b4", progress=0.0):
        self.results = results
        self.data_filename = results.data_filename
        self.procedure = results.procedure
        self.eid = eid if eid is not None else str(uuid.uuid4())
        self.color = color
        self.progress = float(progress)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self):
        """Return a JSON-serialisable dict describing this experiment.

        The dict is used as the payload for every ``experiment_queued``
        SocketIO event and may be requested at any time by the frontend.

        Returns
        -------
        dict
            Keys: ``experiment_id``, ``filename``, ``filepath``,
            ``status``, ``status_label``, ``progress``, ``color``,
            ``params``.
        """
        status = self.procedure.status
        status_label = Procedure.STATUS_STRINGS.get(status, str(status))
        return {
            "experiment_id": self.eid,
            "filename": basename(self.data_filename),
            "filepath": self.data_filename,
            "status": status,
            "status_label": status_label,
            "progress": self.progress,
            "color": self.color,
            "params": {k: str(v) for k, v in self.procedure.parameter_values().items()},
        }

    def __repr__(self):
        return "<Experiment(eid={}, status={}, file={})>".format(
            self.eid,
            Procedure.STATUS_STRINGS.get(self.procedure.status, self.procedure.status),
            basename(self.data_filename),
        )


# ---------------------------------------------------------------------------
# ExperimentQueue – plain Python class, no QObject
# ---------------------------------------------------------------------------

class ExperimentQueue:
    """A plain Python list-backed queue of :class:`Experiment` objects with
    convenience query methods that mirror the original Qt version.
    """

    def __init__(self):
        self.queue = []

    def append(self, experiment):
        """Append *experiment* to the end of the queue."""
        self.queue.append(experiment)

    def remove(self, experiment):
        """Remove *experiment* from the queue.

        Raises
        ------
        Exception
            If *experiment* is not in the queue or is currently running.
        """
        if experiment not in self.queue:
            raise Exception(
                "Attempting to remove an Experiment that is not in the ExperimentQueue"
            )
        if experiment.procedure.status == Procedure.RUNNING:
            raise Exception("Attempting to remove a running experiment")
        self.queue.pop(self.queue.index(experiment))

    def __contains__(self, value):
        if isinstance(value, Experiment):
            return value in self.queue
        if isinstance(value, str):
            for experiment in self.queue:
                if basename(experiment.data_filename) == basename(value):
                    return True
            return False
        return False

    def __getitem__(self, key):
        return self.queue[key]

    def __iter__(self):
        return iter(self.queue)

    def __len__(self):
        return len(self.queue)

    def next(self):
        """Return the next :class:`Experiment` with status ``QUEUED``.

        Raises
        ------
        StopIteration
            When no queued experiment is available.
        """
        for experiment in self.queue:
            if experiment.procedure.status == Procedure.QUEUED:
                return experiment
        raise StopIteration("There are no queued experiments")

    def has_next(self):
        """Return ``True`` if there is at least one queued experiment."""
        try:
            self.next()
        except StopIteration:
            return False
        return True

    def with_id(self, eid):
        """Return the experiment whose ``eid`` matches *eid*, or ``None``."""
        for experiment in self.queue:
            if experiment.eid == eid:
                return experiment
        return None


# ---------------------------------------------------------------------------
# WebMonitor – threading.Thread that drains the worker's monitor_queue
# ---------------------------------------------------------------------------

class WebMonitor(threading.Thread):
    """Drains the ``monitor_queue`` produced by a :class:`.Worker` or
    :class:`.Analyzer` and translates each message into a SocketIO emission.

    Unlike the Qt ``Monitor``, this class is a plain ``threading.Thread``
    with no Qt dependency.  It also does *not* own a reference to the
    experiment; instead it receives the ``experiment_id`` so that the
    frontend can match events to the correct row.

    :param monitor_queue: The ``Queue`` object from the worker.
    :param socketio: A ``flask_socketio.SocketIO`` instance (or any object
        with a compatible ``emit(event, data)`` method).
    :param experiment_id: The ``eid`` string of the running experiment.
    :param callbacks: Optional dict mapping topic strings (``"running"``,
        ``"failed"``, ``"finished"``, ``"aborted"``) to zero-argument
        callables that are invoked *from this thread* when the
        corresponding status is received.  The :class:`WebManager` uses
        this to trigger its own state-machine transitions.
    """

    # Map from Procedure status integer → callback key
    _STATUS_CALLBACK = {
        Procedure.RUNNING:  "running",
        Procedure.FAILED:   "failed",
        Procedure.FINISHED: "finished",
        Procedure.ABORTED:  "aborted",
    }

    def __init__(self, monitor_queue, socketio, experiment_id, callbacks=None):
        super().__init__(daemon=True, name="WebMonitor-{}".format(experiment_id))
        self.queue = monitor_queue
        self.socketio = socketio
        self.experiment_id = experiment_id
        self.callbacks = callbacks or {}
        self.stop = False

    def run(self):
        log.debug("WebMonitor started for experiment %s", self.experiment_id)
        eid = self.experiment_id

        while not self.stop:
            item = self.queue.get()

            # Worker signals end-of-stream with a None sentinel
            if item is None:
                log.debug("WebMonitor received stop sentinel for %s", eid)
                break

            topic, data = item

            if topic == "status":
                self._emit("status", {"experiment_id": eid, "value": data})
                cb_key = self._STATUS_CALLBACK.get(data)
                if cb_key and cb_key in self.callbacks:
                    try:
                        self.callbacks[cb_key]()
                    except Exception:
                        log.exception(
                            "WebMonitor callback '%s' raised an exception", cb_key
                        )

            elif topic == "progress":
                self._emit("progress", {"experiment_id": eid, "value": data})

            elif topic == "log":
                record = data
                payload = {
                    "experiment_id": eid,
                    "message": record.getMessage() if hasattr(record, "getMessage") else str(record),
                    "levelname": getattr(record, "levelname", "INFO"),
                }
                self._emit("log", payload)

        log.debug("WebMonitor exiting for experiment %s", eid)

    def _emit(self, event, payload):
        """Emit *payload* as a SocketIO *event*, swallowing any errors."""
        try:
            self.socketio.emit(event, payload)
        except Exception:
            log.exception("WebMonitor failed to emit event '%s'", event)


# ---------------------------------------------------------------------------
# WebManager – thread-safe queue manager with SocketIO emissions
# ---------------------------------------------------------------------------

class WebManager:
    """Controls the execution of :class:`Experiment` instances using a
    queue system and emits lifecycle events over SocketIO rather than Qt
    signals.

    The public API is intentionally close to the original Qt ``Manager``
    class so that application code can be migrated with minimal changes.

    :param socketio: A ``flask_socketio.SocketIO`` instance used to push
        events to connected browsers.
    :param port: ZMQ port passed through to the :class:`.Worker`.  Passing
        ``None`` disables ZMQ publishing.
    :param log_level: Python logging level forwarded to the worker.
    """

    _is_continuous = True
    _start_on_add = True

    def __init__(self, socketio, port=5888, log_level=logging.INFO):
        self._socketio = socketio
        self.port = port
        self.log_level = log_level

        self.experiments = ExperimentQueue()

        self._lock = threading.Lock()
        self._worker = None
        self._running_experiment = None
        self._monitor = None

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def is_running(self):
        """Return ``True`` when an experiment is currently executing."""
        return self._running_experiment is not None

    def running_experiment(self):
        """Return the currently running :class:`Experiment`.

        Raises
        ------
        Exception
            If no experiment is running.
        """
        if self.is_running():
            return self._running_experiment
        raise Exception("There is no Experiment running")

    # ------------------------------------------------------------------
    # Queue manipulation
    # ------------------------------------------------------------------

    def queue(self, experiment):
        """Append *experiment* to the queue and start it immediately if idle.

        Emits ``experiment_queued`` with the serialised experiment dict.
        """
        with self._lock:
            self.experiments.append(experiment)

        self._emit("experiment_queued", experiment.to_dict())
        log.debug("Experiment %s queued", experiment.eid)

        if self._start_on_add and not self.is_running():
            self._next()

    def load(self, experiment):
        """Append a previously-executed *experiment* without starting it.

        Use this when loading old result files into the queue for display
        purposes.  Emits ``experiment_queued`` so the frontend can render
        the row.
        """
        with self._lock:
            self.experiments.append(experiment)

        self._emit("experiment_queued", experiment.to_dict())
        log.debug("Experiment %s loaded (no auto-start)", experiment.eid)

    def remove(self, experiment):
        """Remove *experiment* from the queue and notify the frontend.

        Emits ``experiment_removed``.

        Raises
        ------
        Exception
            Propagated from :class:`ExperimentQueue` when the experiment
            cannot be removed (e.g. it is currently running).
        """
        with self._lock:
            self.experiments.remove(experiment)

        self._emit("experiment_removed", {"experiment_id": experiment.eid})
        log.debug("Experiment %s removed", experiment.eid)

    def clear(self):
        """Remove all experiments from the queue."""
        for experiment in list(self.experiments):
            try:
                self.remove(experiment)
            except Exception:
                log.warning(
                    "Could not remove experiment %s during clear()", experiment.eid
                )

    def clear_unfinished(self):
        """Remove all non-finished experiments and delete their data files.

        Experiments with status ``FINISHED`` and the currently running
        experiment are left untouched.
        """
        for experiment in list(reversed(self.experiments.queue)):
            status = experiment.procedure.status
            if status == Procedure.FINISHED:
                continue
            if experiment is self._running_experiment:
                continue
            pathtofile = experiment.results.data_filenames
            try:
                self.remove(experiment)
            except Exception:
                log.warning(
                    "Could not remove experiment %s during clear_unfinished()",
                    experiment.eid,
                )
                continue
            if len(pathtofile) != 1:
                raise ValueError(
                    "clear_unfinished() is not implemented for multiple recording locations"
                )
            try:
                rmfile(pathtofile[0])
                log.debug("Deleted data file %s", pathtofile[0])
            except OSError:
                log.warning("Could not delete data file %s", pathtofile[0])

    def abort(self):
        """Stop the currently running experiment.

        Sets continuous mode to ``False`` so that the next experiment does
        not start automatically.  Emits ``experiment_aborted``.

        Raises
        ------
        Exception
            If no experiment is currently running.
        """
        if not self.is_running():
            raise Exception("Attempting to abort when no experiment is running")

        self._start_on_add = False
        self._is_continuous = False

        self._worker.stop()

        self._emit(
            "experiment_aborted", {"experiment_id": self._running_experiment.eid}
        )
        log.debug("Abort signal sent to worker for %s", self._running_experiment.eid)

    def resume(self):
        """Re-enable continuous mode and start the next queued experiment."""
        self._start_on_add = True
        self._is_continuous = True
        self._next()

    # ------------------------------------------------------------------
    # Internal flow
    # ------------------------------------------------------------------

    def _next(self):
        """Start the next queued experiment if one exists and none is running."""
        with self._lock:
            if self.is_running():
                log.debug("_next() called while already running – ignoring")
                return
            if not self.experiments.has_next():
                log.debug("_next() called with empty queue – nothing to do")
                return

            self._running_experiment = self.experiments.next()

        eid = self._running_experiment.eid
        log.debug("WebManager starting experiment %s", eid)

        self._worker = Worker(
            self._running_experiment.results,
            port=self.port,
            log_level=self.log_level,
        )

        callbacks = {
            "running":  self._on_running,
            "failed":   self._on_failed,
            "finished": self._on_finished,
            "aborted":  self._on_abort_returned,
        }

        self._monitor = WebMonitor(
            self._worker.monitor_queue,
            self._socketio,
            eid,
            callbacks=callbacks,
        )
        self._monitor.start()
        self._worker.start()

    def _on_running(self):
        """Called by the monitor thread when the worker reports RUNNING."""
        if self.is_running():
            self._emit(
                "experiment_running", {"experiment_id": self._running_experiment.eid}
            )

    def _clean_up(self):
        """Join the worker thread and stop the monitor thread.

        Called from the monitor thread, so we must not join the monitor
        thread from within itself (that would deadlock).
        """
        if self._worker is not None:
            self._worker.join()

        if self._monitor is not None:
            self._monitor.stop = True
            # Only join from outside the monitor thread to avoid deadlock
            if self._monitor is not threading.current_thread():
                self._monitor.join(timeout=10.0)
                if self._monitor.is_alive():
                    log.warning("WebMonitor did not exit within 10 s for experiment %s",
                                self._running_experiment.eid if self._running_experiment else "?")

        self._worker = None
        self._monitor = None
        self._running_experiment = None
        log.debug("WebManager cleaned up after Worker")

    def _on_finished(self):
        """Called by the monitor thread when the worker reports FINISHED."""
        log.debug("WebManager: experiment finished")
        experiment = self._running_experiment
        self._clean_up()
        self._emit("experiment_finished", {"experiment_id": experiment.eid})
        if self._is_continuous:
            self._next()

    def _on_failed(self):
        """Called by the monitor thread when the worker reports FAILED."""
        log.debug("WebManager: experiment failed")
        experiment = self._running_experiment
        self._clean_up()
        self._emit("experiment_failed", {"experiment_id": experiment.eid})

    def _on_abort_returned(self):
        """Called by the monitor thread when the worker reports ABORTED."""
        log.debug("WebManager: experiment aborted and returned")
        experiment = self._running_experiment
        self._clean_up()
        self._emit("experiment_aborted", {"experiment_id": experiment.eid})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, event, payload):
        """Emit a SocketIO *event* with *payload*, swallowing errors."""
        try:
            self._socketio.emit(event, payload)
        except Exception:
            log.exception("WebManager failed to emit SocketIO event '%s'", event)
