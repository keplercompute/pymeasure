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

# import pytest
# from unittest import mock

# from pymeasure.display.Qt import QtWidgets, QtCore
# from pymeasure.display.plotter import Plotter
# from pymeasure.experiment.results import Results

# TODO: Repair this unit test
# class TestPlotter:
#     # TODO: More thorough unit (or integration?) tests.
#
#     @mock.patch('pymeasure.display.plotter.PlotterWindow')
#     @mock.patch('pymeasure.display.plotter.QtWidgets')
#     @mock.patch.object(Plotter, 'setup_plot')
#     def test_setup_plot_called_on_init(self, mock_sp, MockQtWidgets, MockPlotterWindow):
#         r = mock.MagicMock(spec=Results)
#         mockplot = mock.MagicMock()
#         MockPlotterWindow.return_value = mock.MagicMock(plot=mockplot)
#         p = Plotter(r)
#         p.run() # we don't care about starting the process, just check the run
#         mock_sp.assert_called_once_with(mockplot)
