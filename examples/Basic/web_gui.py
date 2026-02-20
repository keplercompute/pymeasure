"""
This example demonstrates how to make a web-based graphical interface, and
uses a random number generator to simulate data so that it does not require
an instrument to use.

It is the web equivalent of gui.py, using Flask + SocketIO + Bokeh instead
of Qt.  The Procedure definition is identical.

Run the program by changing to the directory containing this file and calling:

    python web_gui.py

Then open http://127.0.0.1:5000 in a browser.

Requirements (in addition to pymeasure):
    pip install flask flask-socketio bokeh
"""

import random
import tempfile
import logging
from time import sleep

from pymeasure.experiment import Procedure, IntegerParameter, Parameter, FloatParameter
from pymeasure.experiment import FeatherResults as Results
from pymeasure.web import ManagedWebWindow

log = logging.getLogger('')
log.addHandler(logging.NullHandler())


class TestProcedure(Procedure):

    iterations = IntegerParameter('Loop Iterations', default=100)
    delay = FloatParameter('Delay Time', units='s', default=0.2)
    seed = Parameter('Random Seed', default='12345')

    DATA_COLUMNS = ['Iteration', 'Random Number']

    def startup(self):
        log.info("Setting up random number generator")
        random.seed(self.seed)

    def execute(self):
        log.info("Starting to generate numbers")
        for i in range(self.iterations):
            data = {
                'Iteration': i,
                'Random Number': random.random()
            }
            log.debug("Produced numbers: %s" % data)
            self.emit('results', data)
            self.emit('progress', 100 * i / self.iterations)
            sleep(self.delay)
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                break

    def shutdown(self):
        log.info("Finished")


class MainWindow(ManagedWebWindow):

    procedure_class = TestProcedure
    inputs = ('iterations', 'delay', 'seed')
    displays = ('iterations', 'delay', 'seed')
    x_axis = 'Iteration'
    y_axis = 'Random Number'

    def queue(self, procedure=None):
        filename = tempfile.mktemp()

        if procedure is None:
            procedure = self.make_procedure()
        results = Results(procedure, filename)
        experiment = self.new_experiment(results)

        self.manager.queue(experiment)


if __name__ == "__main__":
    MainWindow().run()
