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

"""
ManagedWebWindow — drop-in replacement for display/windows.py ManagedWindow.

Usage::

    from pymeasure.web import ManagedWebWindow
    from pymeasure.experiment import Results, unique_filename

    class MyWindow(ManagedWebWindow):
        procedure_class = MyProcedure
        x_axis = "Voltage (V)"
        y_axis = "Current (A)"
        inputs = ("voltage_start", "voltage_end", "num_points")
        displays = ("voltage_start", "voltage_end")

        def queue(self, procedure=None):
            filename = unique_filename("results", prefix="data")
            if procedure is None:
                procedure = self.make_procedure()
            results = Results(procedure, filename)
            experiment = self.new_experiment(results)
            self.manager.queue(experiment)

    if __name__ == "__main__":
        MyWindow().run()
"""

import logging
import os
import platform
import subprocess
import threading
import uuid
from collections import ChainMap

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO

from bokeh.embed import components
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource
from bokeh.resources import CDN

from ..experiment import Results, Procedure
from ..experiment.parameters import (
    FloatParameter, IntegerParameter, BooleanParameter,
    ListParameter, VectorParameter, Parameter,
)
from .manager import Experiment, WebManager
from .sequence import get_sequence, parse_sequence_file, SequenceEvaluationException

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Palette for auto-assigning curve colors (matches matplotlib tab10)
_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _param_to_dict(key, param):
    """Serialise a Parameter instance to a JSON-safe dict for the template."""
    d = {
        "key": key,
        "name": param.name,
        "default": param.default,
        "units": getattr(param, "units", None),
        "group_by": param.group_by if hasattr(param, "group_by") else {},
    }
    if isinstance(param, (FloatParameter, IntegerParameter)):
        d["type"] = "float" if isinstance(param, FloatParameter) else "integer"
        d["minimum"] = param.minimum
        d["maximum"] = param.maximum
        d["choices"] = None
    elif isinstance(param, BooleanParameter):
        d["type"] = "boolean"
        d["minimum"] = None
        d["maximum"] = None
        d["choices"] = None
    elif isinstance(param, ListParameter):
        d["type"] = "list"
        d["minimum"] = None
        d["maximum"] = None
        d["choices"] = list(param.choices) if param.choices else []
    elif isinstance(param, VectorParameter):
        d["type"] = "string"  # render as text, value is "[x,y,z]"
        d["minimum"] = None
        d["maximum"] = None
        d["choices"] = None
    else:
        d["type"] = "string"
        d["minimum"] = None
        d["maximum"] = None
        d["choices"] = None
    return d


class ManagedWebWindow:
    """
    Base class for web-based experiment management windows.

    Subclass this and define at minimum:
      - ``procedure_class``: the Procedure subclass to run
      - ``queue(self, procedure=None)``: create Results + Experiment, call
        ``self.manager.queue(experiment)``

    Optional class attributes:
      - ``x_axis``: default x-axis column name
      - ``y_axis``: default y-axis column name
      - ``inputs``: tuple of parameter attribute names to show in the form
      - ``displays``: tuple of parameter names to show in the browser table
      - ``port``: ZMQ port for Worker (default 5888, set None to disable)
      - ``log_level``: logging level (default logging.INFO)
      - ``sequencer``: bool, show sequencer panel (default False)
      - ``sequencer_inputs``: list of param keys for sequencer, or None for all inputs
    """

    procedure_class = None
    x_axis = None
    y_axis = None
    inputs = ()
    displays = ()
    port = 5888
    log_level = logging.INFO
    sequencer = False
    sequencer_inputs = None

    def __init__(self):
        if self.procedure_class is None:
            raise ValueError("ManagedWebWindow subclass must define procedure_class")

        # Default axes to first two DATA_COLUMNS if not specified
        cols = self.procedure_class.DATA_COLUMNS
        if self.x_axis is None and len(cols) > 0:
            self.x_axis = cols[0]
        if self.y_axis is None and len(cols) > 1:
            self.y_axis = cols[1]

        self._current_x = self.x_axis
        self._current_y = self.y_axis
        self._color_index = 0
        self._default_directory = os.getcwd()

        # Build Flask app pointing at this package's templates/static
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        self._app = Flask(
            __name__,
            template_folder=template_dir,
            static_folder=static_dir,
        )
        self._app.config["SECRET_KEY"] = os.urandom(24)

        self._socketio = SocketIO(
            self._app,
            async_mode="threading",
            cors_allowed_origins="*",
            logger=False,
            engineio_logger=False,
            manage_session=False,
        )

        self.manager = WebManager(
            self._socketio,
            port=self.port,
            log_level=self.log_level,
        )

        # Bokeh plot and per-experiment sources
        self._bokeh_sources = {}   # eid -> ColumnDataSource
        self._bokeh_figure = self._make_bokeh_figure()

        self._register_routes()
        self._register_socketio_events()

    # ------------------------------------------------------------------
    # Bokeh setup
    # ------------------------------------------------------------------

    def _make_bokeh_figure(self):
        cols = self.procedure_class.DATA_COLUMNS
        x_label = self._current_x or (cols[0] if cols else "x")
        y_label = self._current_y or (cols[1] if len(cols) > 1 else "y")
        p = figure(
            sizing_mode="stretch_both",
            x_axis_label=x_label,
            y_axis_label=y_label,
            tools="pan,wheel_zoom,box_zoom,reset,save",
            active_scroll="wheel_zoom",
        )
        p.background_fill_color = "#1e1e1e"
        p.border_fill_color = "#1e1e1e"
        p.grid.grid_line_color = "#333333"
        p.axis.axis_label_text_color = "#dddddd"
        p.axis.major_label_text_color = "#dddddd"
        p.axis.axis_line_color = "#555555"
        p.title.text_color = "#dddddd"
        return p

    def _add_bokeh_curve(self, eid, color):
        source = ColumnDataSource(data=dict(x=[], y=[]))
        self._bokeh_sources[eid] = source
        self._bokeh_figure.line(
            "x", "y",
            source=source,
            line_color=color,
            line_width=1.5,
            name=eid,
        )
        return source

    def _remove_bokeh_curve(self, eid):
        self._bokeh_sources.pop(eid, None)
        renderers = [r for r in self._bokeh_figure.renderers if r.name == eid]
        for r in renderers:
            self._bokeh_figure.renderers.remove(r)

    # ------------------------------------------------------------------
    # Public helpers (called from queue() override)
    # ------------------------------------------------------------------

    def make_procedure(self, params=None):
        """Instantiate procedure_class and set parameters from a dict."""
        procedure = self.procedure_class()
        if params:
            procedure.set_parameters(params)
        return procedure

    def new_experiment(self, results):
        """Wrap Results in an Experiment with a unique id and color."""
        eid = str(uuid.uuid4())[:8]
        color = _COLORS[self._color_index % len(_COLORS)]
        self._color_index += 1
        self._add_bokeh_curve(eid, color)
        return Experiment(results, eid, color)

    def queue(self, procedure=None):
        """Override in subclass to create Results and call manager.queue()."""
        raise NotImplementedError("Subclass must implement queue()")

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _register_routes(self):
        app = self._app

        @app.route("/")
        def index():
            # Build Bokeh embed components fresh each page load
            script, div = components(self._bokeh_figure)
            css = CDN.render_css()
            js = CDN.render_js()

            param_objects = self.procedure_class().parameter_objects()
            # Filter to only the declared inputs (or all if inputs is empty)
            if self.inputs:
                params = [
                    _param_to_dict(k, param_objects[k])
                    for k in self.inputs
                    if k in param_objects
                ]
            else:
                params = [_param_to_dict(k, p) for k, p in param_objects.items()]

            # Sequencer parameter names
            seq_inputs = self.sequencer_inputs or (
                [p["key"] for p in params] if self.sequencer else []
            )
            seq_param_names = {
                k: param_objects[k].name
                for k in seq_inputs
                if k in param_objects
            }

            return render_template(
                "index.html",
                procedure_params=params,
                data_columns=self.procedure_class.DATA_COLUMNS,
                x_axis=self._current_x,
                y_axis=self._current_y,
                bokeh_script=script,
                bokeh_div=div,
                bokeh_css=css,
                bokeh_js=js,
                use_sequencer=self.sequencer,
                seq_param_names=seq_param_names,
                default_directory=self._default_directory,
            )

        @app.route("/queue", methods=["POST"])
        def queue_experiment():
            data = request.get_json()
            params = data.get("params", {})
            directory = data.get("directory", self._default_directory)
            self._default_directory = directory
            try:
                procedure = self.make_procedure(params)
                self.queue(procedure=procedure)
                return jsonify({"status": "ok"})
            except Exception as e:
                log.exception("Error queuing experiment")
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/abort", methods=["POST"])
        def abort_experiment():
            try:
                self.manager.abort()
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/resume", methods=["POST"])
        def resume_experiment():
            try:
                self.manager.resume()
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/remove", methods=["POST"])
        def remove_experiment():
            data = request.get_json()
            eid = data.get("experiment_id")
            exp = self.manager.experiments.with_id(eid)
            if exp is None:
                return jsonify({"status": "error", "message": "Not found"}), 404
            try:
                self.manager.remove(exp)
                self._remove_bokeh_curve(eid)
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/clear_unfinished", methods=["POST"])
        def clear_unfinished():
            try:
                self.manager.clear_unfinished()
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/open_file", methods=["POST"])
        def open_file():
            data = request.get_json()
            filepath = data.get("filepath", "")
            _open_file_externally(filepath)
            return jsonify({"status": "ok"})

        @app.route("/set_axes", methods=["POST"])
        def set_axes():
            data = request.get_json()
            self._current_x = data.get("x_axis", self._current_x)
            self._current_y = data.get("y_axis", self._current_y)
            return jsonify({"status": "ok"})

        @app.route("/data/<eid>")
        def get_data(eid):
            """Return x/y data for an experiment, optionally from a row offset."""
            exp = self.manager.experiments.with_id(eid)
            if exp is None:
                return jsonify({"status": "error", "message": "Not found"}), 404
            after = int(request.args.get("after", 0))
            x_col = request.args.get("x", self._current_x)
            y_col = request.args.get("y", self._current_y)
            try:
                df = exp.results.data
                if df is None or df.empty:
                    return jsonify({"xs": [], "ys": [], "total": 0})
                total = len(df)
                new_rows = df.iloc[after:]
                xs = new_rows[x_col].tolist() if x_col in new_rows.columns else []
                ys = new_rows[y_col].tolist() if y_col in new_rows.columns else []
                return jsonify({"xs": xs, "ys": ys, "total": total})
            except Exception as e:
                log.exception("Error reading data for %s", eid)
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/experiments")
        def list_experiments():
            """Return current state of all experiments (for page reload recovery)."""
            return jsonify([
                exp.to_dict() for exp in self.manager.experiments
            ])

        @app.route("/parse_sequence", methods=["POST"])
        def parse_sequence():
            data = request.get_json()
            content = data.get("content", "")
            try:
                tree = parse_sequence_file(content)
                return jsonify({"status": "ok", "tree": tree})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        @app.route("/queue_sequence", methods=["POST"])
        def queue_sequence():
            data = request.get_json()
            tree = data.get("tree", [])
            directory = data.get("directory", self._default_directory)
            self._default_directory = directory

            param_objects = self.procedure_class().parameter_objects()
            names_inv = {p.name: k for k, p in param_objects.items()}

            try:
                flat = get_sequence(tree)
            except SequenceEvaluationException as e:
                return jsonify({"status": "error", "message": str(e)}), 400

            queued = 0
            for entry in flat:
                # entry is a tuple of dicts (one per depth level); merge them
                if isinstance(entry, tuple):
                    params = dict(ChainMap(*entry[::-1]))
                else:
                    params = entry
                # tree nodes may use display names; convert back to keys
                converted = {}
                for k, v in params.items():
                    key = names_inv.get(k, k)
                    converted[key] = v
                try:
                    procedure = self.make_procedure(converted)
                    self.queue(procedure=procedure)
                    queued += 1
                except Exception as e:
                    log.error("Failed to queue sequence entry %s: %s", params, e)

            return jsonify({"status": "ok", "queued": queued})

    # ------------------------------------------------------------------
    # SocketIO events
    # ------------------------------------------------------------------

    def _register_socketio_events(self):
        sio = self._socketio

        @sio.on("connect")
        def on_connect():
            log.debug("Browser client connected")
            # Send current experiment state to newly connected client
            for exp in self.manager.experiments:
                sio.emit("experiment_queued", exp.to_dict())

        @sio.on("disconnect")
        def on_disconnect():
            log.debug("Browser client disconnected")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, host="127.0.0.1", port=5000, debug=False, open_browser=True):
        """Start the Flask-SocketIO server.

        :param host: host to bind (default 127.0.0.1)
        :param port: HTTP port (default 5000)
        :param debug: Flask debug mode (do not use in production)
        :param open_browser: automatically open a browser tab on startup
        """
        if open_browser:
            import webbrowser
            url = f"http://{host}:{port}"
            # Delay slightly so the server is ready before the browser opens
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()

        log.info("Starting ManagedWebWindow on http://%s:%d", host, port)
        self._socketio.run(
            self._app,
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,   # reloader forks process, breaks ZMQ
            allow_unsafe_werkzeug=True,
        )


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _open_file_externally(filepath):
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["start", "", filepath], shell=True)
    elif system == "Linux":
        subprocess.Popen(["xdg-open", filepath])
    elif system == "Darwin":
        subprocess.Popen(["open", filepath])
    else:
        raise RuntimeError(f"Unsupported OS: {system}")
