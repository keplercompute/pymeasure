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

import logging

from ..browser import AnalysisBrowser, AnalysisBrowserItem
from ..Qt import QtGui
from ..manager import AnalyzerManager, Analysis

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class AnalysisBrowserWidget(QtGui.QWidget):
    """
    Widget wrapper for :class:`AnalysisBrowser<pymeasure.display.browser.AnalysisBrowser>` class
    """
    def __init__(self, *args, parent=None):
        super().__init__(parent)

        self._parent = parent
        self.browser_args = args
        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        self.analysis_browser = AnalysisBrowser(*self.browser_args, parent=self)
        self.abort_button = QtGui.QPushButton('Abort Analysis', self)
        self.abort_button.setEnabled(False)
        self.continue_button = QtGui.QPushButton('Continue Analysis', self)
        self.continue_button.setEnabled(False)

        self.abort_button.clicked.connect(self.abort_analysis)
        self.continue_button.clicked.connect(self.continue_analysis)

        self._parent.manager.finished.connect(self.experiment_finished)

        self.analysis_browser.itemChanged.connect(self.analysis_browser_item_changed)

        self.analysis_manager = AnalyzerManager(self.analysis_browser,
                                                port=self._parent.port,
                                                log_level=self._parent.log_level,
                                                parent=self._parent)

        self.analysis_manager.finished.connect(self.finished)

    def _layout(self):
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(0)

        hbox = QtGui.QHBoxLayout()
        hbox.setSpacing(10)
        hbox.setContentsMargins(-1, 6, -1, 6)
        label = QtGui.QLabel(self)
        label.setText("Analysis Queue")
        hbox.addWidget(label)
        hbox.addWidget(self.continue_button)
        hbox.addStretch()
        hbox.addWidget(self.abort_button)

        vbox.addLayout(hbox)
        vbox.addWidget(self.analysis_browser)
        self.setLayout(vbox)

    def analysis_browser_item_changed(self, item, column):
        """Relic of browser_item_changed. We don't update the plot for analyses so this is a place holder
        """
        if column == 0:
            state = item.checkState(0)
            analysis = self.analysis_manager.analyses.with_browser_item(item)

    def abort_analysis(self):
        self.abort_button.setEnabled(False)
        self.abort_button.setText("Restart Aborted/Failed")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.resume)
        try:
            self.analysis_manager.abort()
        except:  # noqa
            log.error('Failed to abort experiment', exc_info=True)
            self.abort_button.setText("Abort Analysis")
            self.abort_button.clicked.disconnect()
            self.abort_button.clicked.connect(self.abort_analysis)

    def resume(self):
        self.abort_button.setText("Abort Analysis")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.abort_analysis)
        if self.analysis_manager.analyses.has_next():
            self.analysis_manager.retry()
        else:
            self.abort_button.setEnabled(False)

    def continue_analysis(self):
        self.abort_button.setText("Abort Analysis")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.abort_analysis)
        if self.analysis_manager.experiments.has_next():
            self.analysis_manager.resume()
        else:
            self.abort_button.setEnabled(False)

    def new_analysis(self, results, curve_color):
        analysis_browser_item = AnalysisBrowserItem(results, curve_color)
        return Analysis(results, analysis_browser_item)

    def experiment_finished(self, experiment):
        # snippet to kick off the relevant analysis if routine present in results
        results = experiment.results
        color = experiment.browser_item.color
        if results.routine is not None:
            analysis = self.new_analysis(results, color)
            self.analysis_manager.queue(analysis)
            self.abort_button.setEnabled(True)

    def finished(self):
        self.abort_button.setText("Abort Analysis")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.abort_analysis)
        self.abort_button.setEnabled(False)
