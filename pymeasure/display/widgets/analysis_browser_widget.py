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

from ..browser import AnalysisBrowser
from ..Qt import QtGui

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class AnalysisBrowserWidget(QtGui.QWidget):
    """
    Widget wrapper for :class:`AnalysisBrowser<pymeasure.display.browser.AnalysisBrowser>` class
    """
    def __init__(self, *args, parent=None):
        super().__init__(parent)
        self.browser_args = args
        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        self.analysis_browser = AnalysisBrowser(*self.browser_args, parent=self)
        self.pause_button = QtGui.QPushButton('Pause Analysis', self)
        self.pause_button.setEnabled(False)

    def _layout(self):
        vbox = QtGui.QVBoxLayout(self)
        vbox.setSpacing(0)

        hbox = QtGui.QHBoxLayout()
        hbox.setSpacing(10)
        hbox.setContentsMargins(-1, 6, -1, 6)
        label = QtGui.QLabel(self)
        label.setText("Analysis Queue")
        hbox.addWidget(label)
        hbox.addStretch()
        hbox.addWidget(self.pause_button)

        vbox.addLayout(hbox)
        vbox.addWidget(self.analysis_browser)
        self.setLayout(vbox)
